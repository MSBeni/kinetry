// Plays a Kinetry LMS package in headless Chrome against a mock SCORM API, and checks what it reports.
//   node tests/js/lms_harness.mjs PACKAGE.zip [scorm12|scorm2004]
// Needs: unzip, ffmpeg (makes a WebM stand-in, since test Chromium builds can't decode H.264), Chrome
// (KINETRY_BROWSER_PATH or PUPPETEER_EXECUTABLE_PATH), and puppeteer-core (from `kinetry setup`'s tooling).
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const [, , zip, standard = "scorm12"] = process.argv;
const home = process.env.KINETRY_HOME || path.join(os.homedir(), ".cache", "kinetry");
const require = createRequire(path.join(process.env.KINETRY_TOOL_DIR || path.join(home, "tooling"), "noop.js"));
const puppeteer = require("puppeteer-core");
const chrome = process.env.KINETRY_BROWSER_PATH || process.env.PUPPETEER_EXECUTABLE_PATH;
if (!chrome || !fs.existsSync(chrome)) {
  console.error(`No Chrome at "${chrome || ""}". Set KINETRY_BROWSER_PATH (\`kinetry doctor\` shows the one Kinetry uses).`);
  process.exit(2);
}

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kinetry-lms-"));
execFileSync("unzip", ["-q", zip, "-d", dir]);
const lesson = JSON.parse(fs.readFileSync(path.join(dir, "lesson.js"), "utf8").replace(/^window\.KINETRY_LESSON = /, "").replace(/;\s*$/, ""));
const dur = Math.max(4, Math.ceil(lesson.duration));
execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "lavfi", "-i", `color=c=gray:s=320x180:d=${dur}`, "-c:v", "libvpx-vp9", "-b:v", "50k", path.join(dir, "media", "video.webm")]);
fs.renameSync(path.join(dir, "media", "video.webm"), path.join(dir, "media", "video.mp4"));

const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".vtt": "text/vtt", ".mp4": "video/webm", ".jpg": "image/jpeg", ".txt": "text/plain" };
const srv = http.createServer((q, r) => {
  const f = path.join(dir, decodeURIComponent(q.url.split("?")[0]).replace(/^\/+/, "") || "index.html");
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); } else { r.writeHead(200, { "content-type": types[path.extname(f)] || "application/octet-stream" }); r.end(d); } });
}).listen(0);
const port = srv.address().port;

const b = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", "--autoplay-policy=no-user-gesture-required"] });
const p = await b.newPage();
const errors = [];
p.on("pageerror", (e) => errors.push(String(e)));
await p.evaluateOnNewDocument((std) => {
  const data = {}, calls = [];
  const rec = (n) => (...a) => { calls.push([n, ...a]); return n.includes("Get") ? (data[a[0]] || "") : "true"; };
  const api = std === "scorm12"
    ? { LMSInitialize: rec("LMSInitialize"), LMSGetValue: rec("LMSGetValue"), LMSCommit: rec("LMSCommit"), LMSFinish: rec("LMSFinish"),
        LMSSetValue: (k, v) => { calls.push(["LMSSetValue", k, v]); data[k] = v; return "true"; }, LMSGetLastError: () => "0" }
    : { Initialize: rec("Initialize"), GetValue: rec("GetValue"), Commit: rec("Commit"), Terminate: rec("Terminate"),
        SetValue: (k, v) => { calls.push(["SetValue", k, v]); data[k] = v; return "true"; }, GetLastError: () => "0" };
  window[std === "scorm12" ? "API" : "API_1484_11"] = api;
  window.__lms = { data, calls };
}, standard);
await p.goto(`http://localhost:${port}/index.html`, { waitUntil: "load" });

const fail = [];
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) fail.push(what); };
const data = () => p.evaluate(() => ({ ...window.__lms.data }));

check(await p.evaluate(() => window.__lms.calls.some((c) => c[0] === "LMSInitialize" || c[0] === "Initialize")), "initializes the LMS session");
const statusKey = standard === "scorm12" ? "cmi.core.lesson_status" : "cmi.completion_status";
check((await data())[statusKey] === "incomplete", "starts as incomplete");

// skipping to the end doesn't count as watching
await p.evaluate(() => { const v = document.getElementById("video"); v.muted = true; v.currentTime = v.duration - 1; });
await new Promise((r) => setTimeout(r, 800));
check(await p.evaluate(() => window.KinetryPlayer.share() < 0.2), "seeking ahead doesn't count as watched");

// watch it all, fast
await p.evaluate(() => { const v = document.getElementById("video"); v.currentTime = 0; v.playbackRate = 8; return v.play(); });
await p.waitForFunction(() => document.getElementById("video").ended, { timeout: 60000 });
await new Promise((r) => setTimeout(r, 400));
check(await p.evaluate(() => window.KinetryPlayer.share() >= 0.9), "watching the whole video counts");
check(await p.evaluate(() => document.querySelectorAll("#chapters li").length) === lesson.scenes.length, "lists every chapter");
check(await p.evaluate(() => document.querySelectorAll("#transcript .cue").length) === lesson.cues.length, "shows every transcript line");

if (lesson.quiz.length) {
  check(await p.evaluate(() => !document.getElementById("q-form").hidden), "the knowledge check unlocks after watching");
  // answer one wrong first, then all right
  await p.evaluate((qz) => { qz.forEach((q, i) => { const pick = i === 0 ? (q.answer + 1) % q.options.length : q.answer; document.querySelector(`input[name=q${i}][value="${pick}"]`).click(); }); }, lesson.quiz);
  await p.click("#q-form button.go");
  const d1 = await data();
  const failed = standard === "scorm12" ? d1["cmi.core.lesson_status"] === "failed" : d1["cmi.success_status"] === "failed";
  const below = (lesson.quiz.length - 1) / lesson.quiz.length < lesson.mastery;
  check(failed === below, `one wrong answer reports ${below ? "failed" : "passed"} (mastery ${Math.round(lesson.mastery * 100)}%)`);
  await p.click("#q-form button.go");  // try again
  await p.evaluate((qz) => qz.forEach((q, i) => document.querySelector(`input[name=q${i}][value="${q.answer}"]`).click()), lesson.quiz);
  await p.click("#q-form button.go");
  const d2 = await data();
  if (standard === "scorm12") {
    check(d2["cmi.core.score.raw"] === "100" && d2["cmi.core.lesson_status"] === "passed", "all right reports score 100 and passed");
  } else {
    check(d2["cmi.score.scaled"] === "1.00" && d2["cmi.success_status"] === "passed" && d2["cmi.completion_status"] === "completed", "all right reports scaled 1.00, passed and completed");
  }
} else {
  const d = await data();
  check(d[statusKey] === "completed", "no quiz: watching completes the lesson");
}

await p.evaluate(() => window.KinetryPlayer.leave());
const end = await p.evaluate(() => ({ calls: window.__lms.calls.map((c) => c[0]), data: window.__lms.data }));
check(end.calls.includes(standard === "scorm12" ? "LMSFinish" : "Terminate"), "ends the session when the page closes");
check(!!end.data[standard === "scorm12" ? "cmi.core.session_time" : "cmi.session_time"], "reports the session time");
check(JSON.parse(end.data["cmi.suspend_data"] || "{}").w?.length > 0, "saves progress for resuming");
check(errors.length === 0, `no script errors${errors.length ? ": " + errors.join("; ") : ""}`);

await b.close();
srv.close();
fs.rmSync(dir, { recursive: true, force: true });
process.exit(fail.length ? 1 : 0);
