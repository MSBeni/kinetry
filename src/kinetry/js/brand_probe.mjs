// Run brand_probe.js against a live URL in headless Chrome.
// usage: node brand_probe.mjs <url> <chrome-path> <out.json>
// Writes the probe result (colors, CSS variables, fonts, roles, logo SVG/data URL).
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { lookup } from "node:dns/promises";
import net from "node:net";
import { startPublicProxy } from "./public_proxy.mjs";

const require = createRequire(path.join(process.env.KINETRY_TOOL_DIR || process.cwd(), "noop.js"));
const puppeteer = require("puppeteer-core");
const here = path.dirname(fileURLToPath(import.meta.url));
const [, , url, chromePath, outPath] = process.argv;

// Service mode: every request the page makes (redirects, subresources, fetches) must go to a public
// address, so a caller's site can't make the probe reach internal hosts. Mirrors netguard.py.
const PUBLIC_ONLY = process.env.KINETRY_PUBLIC_URLS_ONLY === "1";
const v4num = (a) => a.split(".").reduce((n, x) => n * 256 + Number(x), 0);
const V4_BLOCKED = [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8], ["169.254.0.0", 16], ["172.16.0.0", 12],
  ["192.0.0.0", 24], ["192.0.2.0", 24], ["192.88.99.0", 24], ["192.168.0.0", 16], ["198.18.0.0", 15],
  ["198.51.100.0", 24], ["203.0.113.0", 24], ["224.0.0.0", 4], ["240.0.0.0", 4],
].map(([a, bits]) => [v4num(a), bits]);
function publicV4(a) {
  const n = v4num(a);
  return !V4_BLOCKED.some(([base, bits]) => Math.floor(n / 2 ** (32 - bits)) === Math.floor(base / 2 ** (32 - bits)));
}
function publicIp(ip) {
  if (net.isIPv4(ip)) return publicV4(ip);
  const s = ip.toLowerCase();
  const tail = s.match(/(\d+\.\d+\.\d+\.\d+)$/); // ::ffff:1.2.3.4, 64:ff9b::1.2.3.4
  if (tail && (s.startsWith("::ffff:") || s.startsWith("64:ff9b:"))) return publicV4(tail[1]);
  if (s.startsWith("::ffff:") || s.startsWith("64:ff9b:") || s.startsWith("2002:")) return false; // hex-embedded v4: refuse
  if (s === "::" || s === "::1" || /^f[cd]/.test(s) || /^fe[89ab]/.test(s) || s.startsWith("ff")) return false;
  return true;
}
const seen = new Map();
async function allowed(u) {
  let url;
  try { url = new URL(u); } catch { return false; }
  if (url.protocol === "data:" || url.protocol === "blob:") return true;
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  const host = url.hostname.replace(/^\[|\]$/g, "");
  if (!seen.has(host)) {
    seen.set(host, (async () => {
      if (net.isIP(host)) return publicIp(host);
      try { return (await lookup(host, { all: true })).every((r) => publicIp(r.address)); } catch { return false; }
    })());
  }
  return seen.get(host);
}

// In service mode the browser reaches the web only through a local proxy that connects to checked addresses
// (see public_proxy.mjs); "<-loopback>" stops Chrome from going around it for local names.
const proxy = PUBLIC_ONLY ? await startPublicProxy({ isPublicIp: publicIp }) : null;
const args = ["--no-sandbox", "--disable-dev-shm-usage"];
if (proxy) args.push(`--proxy-server=http://127.0.0.1:${proxy.port}`, "--proxy-bypass-list=<-loopback>");
const browser = await puppeteer.launch({ executablePath: chromePath, headless: true, args });
try {
  const page = await browser.newPage();
  // desktop layout: mobile layouts often hide the header logo behind a menu
  await page.setViewport({ width: 1440, height: 900 });
  if (PUBLIC_ONLY) {
    await page.setRequestInterception(true);
    page.on("request", async (req) => {
      if (req.isInterceptResolutionHandled()) return;
      if (await allowed(req.url())) req.continue();
      else req.abort("blockedbyclient");
    });
    if (!(await allowed(url))) throw new Error("brand URL resolves to a non-public address");
  }
  // 3D models the page loads by script (three.js, model-viewer), not only the ones in its markup
  const loaded = new Set();
  page.on("response", (r) => {
    const type = (r.headers()["content-type"] || "").toLowerCase();
    if (/\.glb(?:[?#]|$)/i.test(r.url()) || type.includes("model/gltf-binary")) loaded.add(r.url());
  });
  await page.setUserAgent("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36");
  await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
  await page.evaluate(() => document.fonts.ready);
  await page.addScriptTag({ content: readFileSync(path.join(here, "brand_probe.js"), "utf8") });
  const result = await page.evaluate(() => window.__brandProbe());
  result.models = [...new Set([...(result.models || []), ...loaded])].filter((u) => /^https?:/.test(u)).slice(0, 6);
  writeFileSync(outPath, JSON.stringify(result, null, 2));
} finally {
  await browser.close();
  if (proxy) proxy.server.close();
}
