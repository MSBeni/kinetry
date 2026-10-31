// The brand probe's proxy, with a real browser: a page on an allowed host tries to load things from a blocked
// one (by name, by a name that resolves to it, and by IP). Only the allowed host may ever be reached.
//   node tests/js/public_proxy_test.mjs        (needs Chrome: KINETRY_BROWSER_PATH, and puppeteer-core from setup)
// "Public" here is faked: 127.0.0.1 counts as public, 127.0.0.2 as internal, and names resolve through a table.
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { startPublicProxy } = await import(path.join(here, "..", "..", "src", "kinetry", "js", "public_proxy.mjs"));
const home = process.env.KINETRY_HOME || path.join(os.homedir(), ".cache", "kinetry");
const require = createRequire(path.join(process.env.KINETRY_TOOL_DIR || path.join(home, "tooling"), "noop.js"));
const puppeteer = require("puppeteer-core");
const chrome = process.env.KINETRY_BROWSER_PATH || process.env.PUPPETEER_EXECUTABLE_PATH;

const internalHits = [];
const internal = http.createServer((req, res) => { internalHits.push(req.url); res.end("secret"); });
await new Promise((r) => internal.listen(0, "127.0.0.2", r));
const ip = internal.address().port;

const page = (p) => `<!doctype html><title>ok</title><body>
  <img src="http://internal.test:${ip}/by-name.png">
  <img src="http://rebind.test:${ip}/by-rebinding-name.png">
  <img src="http://127.0.0.2:${ip}/by-ip.png">
  <script>fetch("http://internal.test:${ip}/by-fetch").catch(() => {});</script>
  <p id="p">public page ${p}</p></body>`;
const site = http.createServer((req, res) => { res.setHeader("content-type", "text/html"); res.end(page(req.url)); });
await new Promise((r) => site.listen(0, "127.0.0.1", r));
const sp = site.address().port;

const table = { "site.test": "127.0.0.1", "internal.test": "127.0.0.2", "rebind.test": "127.0.0.2" };
const lookupFn = (host, opts, cb) => (table[host] ? cb(null, [{ address: table[host], family: 4 }]) : cb(new Error("ENOTFOUND")));
const proxy = await startPublicProxy({ isPublicIp: (a) => a === "127.0.0.1", lookupFn });

const b = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", `--proxy-server=http://127.0.0.1:${proxy.port}`, "--proxy-bypass-list=<-loopback>"],
});
const fail = [];
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) fail.push(what); };
try {
  const p = await b.newPage();
  const r = await p.goto(`http://site.test:${sp}/home`, { waitUntil: "networkidle0", timeout: 30000 });
  check(r && r.status() === 200, "the allowed site loads through the proxy, by name");
  check((await p.$eval("#p", (e) => e.textContent)) === "public page /home", "and its content is the real page");
  const bad = await p.goto(`http://internal.test:${ip}/direct`, { timeout: 15000 }).then((x) => x && x.status(), () => "refused");
  check(bad !== 200, "navigating to an internal host is refused");
  await new Promise((r) => setTimeout(r, 500));
  check(internalHits.length === 0, `the internal host was never reached${internalHits.length ? ": " + internalHits.join(", ") : ""}`);
} finally {
  await b.close();
  proxy.server.close();
  site.close();
  internal.close();
}
process.exit(fail.length ? 1 : 0);
