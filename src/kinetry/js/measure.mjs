// Measure rendered text layout of a composed HyperFrames project.
// usage: node measure.mjs <index.html> <chrome-path> <out.json> [width height]
// Reports, for every [data-field] element: rendered line count vs data-max-lines,
// widows (a lone word on the last line), horizontal overflow of its container,
// and per-scene vertical overflow of the .stage box.
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(path.join(process.env.KINETRY_TOOL_DIR || process.cwd(), "noop.js"));
const puppeteer = require("puppeteer-core");

const [, , indexPath, chromePath, outPath, W = "1920", H = "1080"] = process.argv;
const browser = await puppeteer.launch({
  executablePath: chromePath,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--allow-file-access-from-files", "--disable-gpu"],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: Number(W), height: Number(H) });
  await page.goto(pathToFileURL(path.resolve(indexPath)).href, { waitUntil: "load" });
  await page.evaluate(async () => { await document.fonts.ready; });
  const report = await page.evaluate(() => {
    // neutralise animation offsets so we measure final layout
    document.querySelectorAll("*").forEach((e) => { e.style.transform = "none"; e.style.opacity = "1"; });
    const lineTops = (el) => {
      const r = document.createRange();
      r.selectNodeContents(el);
      const tops = [];
      for (const rect of r.getClientRects()) {
        if (rect.width < 1) continue;
        if (!tops.some((t) => Math.abs(t - rect.top) < rect.height * 0.5)) tops.push(rect.top);
      }
      return tops.sort((a, b) => a - b);
    };
    const words = (el) => {
      const r = document.createRange();
      const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const out = [];
      let n;
      while ((n = tw.nextNode())) {
        const re = /\S+/g; let m;
        while ((m = re.exec(n.data))) {
          r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
          const rect = r.getBoundingClientRect();
          out.push({ w: m[0], top: rect.top });
        }
      }
      return out;
    };
    const container = (el) => el.parentElement.closest(".box, .card, .pill, .chip, .tag, .stage, .node, .strip, .chrome .top > *, .nav, .sitem, .cap") || el.parentElement;
    const rtl = !!document.querySelector("#root.rtl");  // right-to-left videos overflow on the left
    const fields = [];
    for (const el of document.querySelectorAll("[data-field]")) {
      if (!el.textContent.trim()) continue;
      const tops = lineTops(el);
      const ws = words(el);
      const lastTop = tops[tops.length - 1];
      const lastLineWords = ws.filter((w) => Math.abs(w.top - lastTop) < 4).length;
      const box = el.getBoundingClientRect();
      const c = container(el).getBoundingClientRect();
      const cs = getComputedStyle(container(el));
      const padR = parseFloat(cs.paddingRight) || 0;
      const padL = parseFloat(cs.paddingLeft) || 0;
      const fs = parseFloat(getComputedStyle(el).fontSize);
      // word masks (.w) pad each word by 0.04em so descenders and italics aren't cut; that isn't overflow
      const slack = el.querySelector(".w") ? 0.06 * fs : 0;
      const rawX = Math.max(
        rtl ? (c.left + padL - 1) - box.left : box.right - (c.right - padR + 1),
        el.scrollWidth - el.clientWidth,
      );
      fields.push({
        field: el.dataset.field,
        lines: tops.length,
        maxLines: Number(el.dataset.maxLines || 99),
        widow: tops.length > 1 && lastLineWords === 1,
        overflowX: Math.max(0, Math.round(rawX - slack)),
        fontSize: fs,
        text: el.textContent.trim().slice(0, 120),
      });
    }
    const stages = [];
    document.querySelectorAll("section.scene").forEach((sec, i) => {
      const st = sec.querySelector(".stage").getBoundingClientRect();
      let bottom = st.top, top = st.bottom, right = st.left, left = st.right;
      sec.querySelectorAll(".stage *").forEach((e) => {
        if (e.closest("[data-layout-allow-overlap], svg")) return;
        const b = e.getBoundingClientRect();
        if (b.height && b.width) {
          bottom = Math.max(bottom, b.bottom); top = Math.min(top, b.top);
          right = Math.max(right, b.right); left = Math.min(left, b.left);
        }
      });
      stages.push({ scene: i, overflowY: Math.max(0, Math.round(bottom - st.bottom)), overflowTop: Math.max(0, Math.round(st.top - top)),
                    overflowX: Math.max(0, Math.round(rtl ? st.left - left : right - st.right)) });
    });
    return { fields, stages };
  });
  writeFileSync(outPath, JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
