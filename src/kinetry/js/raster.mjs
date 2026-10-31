// Draw an SVG file to a transparent PNG in headless Chrome (for cutting a logo's symbol out of it).
// usage: node raster.mjs <in.svg> <chrome-path> <out.png> [width]
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";

const require = createRequire(path.join(process.env.KINETRY_TOOL_DIR || process.cwd(), "noop.js"));
const puppeteer = require("puppeteer-core");
const [, , svgPath, chromePath, outPath, width = "1200"] = process.argv;
const svg = readFileSync(svgPath, "utf8");
const browser = await puppeteer.launch({
  executablePath: chromePath,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});
try {
  const page = await browser.newPage();
  // offline: the SVG may not reach the network
  await page.setRequestInterception(true);
  page.on("request", (req) => (req.url().startsWith("data:") || req.url() === "about:blank" ? req.continue() : req.abort()));
  await page.setViewport({ width: Number(width), height: 1200 });
  await page.setContent("<html><body style='margin:0;background:transparent'></body></html>");
  const box = await page.evaluate(async (text, W) => {
    const img = new Image();
    img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(text)));
    await img.decode();
    const ratio = (img.naturalHeight || 1) / (img.naturalWidth || 1);
    img.style.cssText = `display:block;width:${W}px;height:${Math.round(W * ratio)}px`;
    document.body.appendChild(img);
    return { width: W, height: Math.max(1, Math.round(W * ratio)) };
  }, svg, Number(width));
  await page.setViewport({ width: box.width, height: Math.min(box.height, 4000) });
  await page.screenshot({ path: outPath, omitBackground: true, clip: { x: 0, y: 0, ...box } });
} finally {
  await browser.close();
}
