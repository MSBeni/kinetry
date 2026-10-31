// Brand probe: runs inside a loaded page (headless Chrome via brand_probe.mjs,
// or any browser) and returns brand evidence as JSON. Uses computed styles, so
// it works on JS-rendered sites where scraping CSS text would miss things.
// Defines window.__brandProbe(); call it and JSON.stringify the result.
window.__brandProbe = async function brandProbe() {
  const toHex = (c) => {
    const m = c && c.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?/);
    if (!m) return null;
    if (m[4] !== undefined && parseFloat(m[4]) < 0.5) return null; // mostly transparent
    return "#" + [m[1], m[2], m[3]].map((v) => (+v).toString(16).padStart(2, "0")).join("");
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity > 0.1;
  };
  const firstFamily = (ff) => (ff || "").split(",")[0].trim().replace(/^["']|["']$/g, "");

  // weighted color usage: text by characters, backgrounds by painted area
  const text = {}, bg = {}, border = {}, fonts = {}, headingFonts = {};
  const els = Array.from(document.querySelectorAll("body *")).slice(0, 4000);
  for (const el of els) {
    if (!visible(el)) continue;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const own = Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.data.trim()).join("");
    if (own.length) {
      const c = toHex(cs.color);
      if (c) text[c] = (text[c] || 0) + own.length;
      const f = firstFamily(cs.fontFamily);
      fonts[f] = (fonts[f] || 0) + own.length;
      if (/^H[1-3]$/.test(el.tagName)) headingFonts[f] = (headingFonts[f] || 0) + own.length;
    }
    const b = toHex(cs.backgroundColor);
    if (b) bg[b] = (bg[b] || 0) + Math.min(r.width * r.height, 1920 * 1200) / 1000;
    if (parseFloat(cs.borderTopWidth) > 0) {
      const bc = toHex(cs.borderTopColor);
      if (bc) border[bc] = (border[bc] || 0) + 1;
    }
  }
  const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n).map(([k, v]) => [k, Math.round(v)]);

  // role samples: what the brand uses for calls to action, links, headings, header
  const sample = (sel, n = 6) => Array.from(document.querySelectorAll(sel)).filter(visible).slice(0, n).map((el) => {
    const cs = getComputedStyle(el);
    return { text: (el.innerText || "").trim().slice(0, 40), bg: toHex(cs.backgroundColor), color: toHex(cs.color),
             gradient: cs.backgroundImage.includes("gradient") ? cs.backgroundImage.slice(0, 160) : null,
             font: firstFamily(cs.fontFamily), radius: cs.borderTopLeftRadius };
  });
  const roles = {
    body: (() => { const cs = getComputedStyle(document.body); return { bg: toHex(cs.backgroundColor), color: toHex(cs.color), font: firstFamily(cs.fontFamily) }; })(),
    headings: sample("h1, h2", 6),
    buttons: sample("button, a[class*='btn' i], a[class*='button' i], [role='button'], input[type='submit']", 10),
    links: sample("main a, header a, nav a", 8),
    header: sample("header, [class*='header' i], nav", 2),
  };

  // CSS custom properties on :root (same-origin sheets + computed)
  const vars = {};
  const rootCs = getComputedStyle(document.documentElement);
  for (let i = 0; i < rootCs.length; i++) {
    const p = rootCs[i];
    if (p.startsWith("--")) {
      const v = rootCs.getPropertyValue(p).trim();
      if (/^#[0-9a-f]{3,8}$/i.test(v) || /^rgba?\(/i.test(v)) vars[p] = v;
    }
  }

  // logo candidates: header/nav imgs or svgs that look like a logo
  // Site's own logo: top-left, links home, named after the site. Customer/partner
  // logo walls ("trusted by") also say "logo", so carousels and grids are penalised.
  const host = location.hostname.replace(/^www\./, "").split(".")[0].toLowerCase();
  const siteWord = (document.querySelector("meta[property='og:site_name']")?.content || host).toLowerCase().replace(/\s+/g, "");
  const cls = (n) => (n && (n.className && n.className.baseVal !== undefined ? n.className.baseVal : n.className)) || "";
  const logoScore = (el) => {
    const link = el.closest("a");
    const s = [cls(el), el.id, el.getAttribute("alt"), el.getAttribute("src"), el.getAttribute("aria-label"),
               el.querySelector && el.querySelector("title")?.textContent,
               link && cls(link), link && link.id, link && link.getAttribute("aria-label")]
      .filter(Boolean).join(" ").toLowerCase();
    let score = /logo/.test(s) ? 4 : 0;
    if (s.replace(/[\s_-]+/g, "").includes(siteWord) || s.includes(host)) score += 3;
    if (el.closest("header, nav, [class*='site-header' i], [class*='navbar' i]")) score += 3;
    const href = link && link.getAttribute("href");
    if (href) {
      try {
        const u = new URL(href, location.href);
        if (u.hostname.replace(/^www\./, "") === location.hostname.replace(/^www\./, "") && (u.pathname === "/" || u.pathname === "")) score += 4;
      } catch (e) {}
    }
    if (el.closest("[class*='swiper' i], [class*='slider' i], [class*='carousel' i], [class*='marquee' i], [class*='client' i], [class*='customer' i], [class*='partner' i], [class*='logos' i], [class*='module' i], footer")) score -= 8;
    const r = el.getBoundingClientRect();
    if (r.top < 160 && r.left < 400) score += 2;
    if (r.width < 40 || r.height < 12) score -= 4;
    return score;
  };
  const logos = [];
  for (const el of document.querySelectorAll("img, svg")) {
    if (!visible(el) || (el.tagName === "svg" && el.closest("button"))) continue;
    const sc = logoScore(el);
    if (sc < 7) continue;
    const r = el.getBoundingClientRect();
    const behind = (() => { let n = el.parentElement; while (n) { const c = toHex(getComputedStyle(n).backgroundColor); if (c) return c; n = n.parentElement; } return toHex(getComputedStyle(document.body).backgroundColor) || "#ffffff"; })();
    const item = { score: sc, tag: el.tagName.toLowerCase(), width: Math.round(r.width), height: Math.round(r.height), background: behind };
    if (el.tagName === "IMG") {
      item.src = el.currentSrc || el.src;
      try {
        const res = await fetch(item.src, { credentials: "omit" });
        const type = res.headers.get("content-type") || "";
        if (type.includes("svg")) item.svg = await res.text();
        else if (res.ok) {
          const blob = await res.blob();
          if (blob.size < 600000) item.dataUrl = await new Promise((ok) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.readAsDataURL(blob); });
        }
      } catch (e) { item.fetchError = String(e).slice(0, 120); }
    } else {
      const clone = el.cloneNode(true);
      // bake computed fills so CSS-colored logos survive outside the page
      const src = el.querySelectorAll("*"), dst = clone.querySelectorAll("*");
      src.forEach((n, i) => { const cs = getComputedStyle(n); if (cs.fill && cs.fill !== "none") dst[i].setAttribute("fill", cs.fill); });
      if (!clone.getAttribute("viewBox") && r.width) clone.setAttribute("viewBox", `0 0 ${r.width} ${r.height}`);
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      item.svg = clone.outerHTML;
    }
    logos.push(item);
  }
  logos.sort((a, b) => b.score - a.score);
  // a raster copy of the best logos, drawn the size they appear (up to 4x), so the symbol can be cut out of a
  // logo that pairs one with a wordmark
  for (const item of logos.slice(0, 2)) {
    const src = item.svg ? URL.createObjectURL(new Blob([item.svg], { type: "image/svg+xml" })) : item.dataUrl;
    if (!src) continue;
    try {
      const img = new Image();
      img.src = src;
      await img.decode();
      const k = Math.min(4, 1200 / Math.max(item.width, 1));
      const c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(item.width * k));
      c.height = Math.max(1, Math.round(item.height * k));
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      item.png = c.toDataURL("image/png");
    } catch (e) { item.rasterError = String(e).slice(0, 120); }
  }

  // 3D models the site shows or links to (glTF binary only: a .gltf needs its other files)
  const models = [...new Set([...document.querySelectorAll("model-viewer[src], [src], [href], [data-src], [data-model]")]
    .map((el) => el.getAttribute("src") || el.getAttribute("href") || el.getAttribute("data-src") || el.getAttribute("data-model"))
    .filter((u) => u && /\.glb(?:[?#]|$)/i.test(u))
    .map((u) => { try { return new URL(u, location.href).href; } catch (e) { return null; } })
    .filter((u) => u && /^https?:/.test(u)))].slice(0, 6);

  const meta = (sel, attr = "content") => { const m = document.querySelector(sel); return m ? m.getAttribute(attr) : null; };
  return {
    url: location.href,
    site_name: meta("meta[property='og:site_name']") || document.title,
    title: document.title,
    theme_color: meta("meta[name='theme-color']"),
    // the images a site publishes to represent itself (social previews), absolute URLs
    images: [...new Set([...document.querySelectorAll("meta[property^='og:image'], meta[name^='twitter:image']")]
      .filter((m) => !/:(width|height|type|alt)$/.test(m.getAttribute("property") || m.getAttribute("name") || ""))
      .map((m) => { try { return new URL(m.content, location.href).href; } catch (e) { return null; } })
      .filter((u) => u && /^https?:/.test(u)))].slice(0, 6),
    og_image: meta("meta[property='og:image']"),
    icon: meta("link[rel~='icon']", "href"),
    css_variables: vars,
    text_colors: top(text, 10),
    background_colors: top(bg, 10),
    border_colors: top(border, 6),
    fonts: top(fonts, 6),
    heading_fonts: top(headingFonts, 4),
    loaded_fonts: Array.from(new Set(Array.from(document.fonts).filter((f) => f.status === "loaded").map((f) => f.family.replace(/["']/g, "")))).slice(0, 12),
    roles,
    logos: logos.slice(0, 3),
    models,
  };
};
