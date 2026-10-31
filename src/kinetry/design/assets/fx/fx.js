/* Motion layers (opt-in): camera moves, kinetic type, ambient light. Seek-safe: every tween is placed
   at an absolute time with explicit start values, and "random" placement comes from a PRNG seeded by
   the scene id, so every render (and every parallel render worker) produces the same frames. */
(function () {
  const tl = TF.tl;
  const seeded = (str) => {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    let a = h >>> 0;
    return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  };
  const words = (s) => (TF.exists(s + " .w") ? s + " .w > span" : null);

  // -------------------------------------------------------------- kinetic type
  // Wraps the style's motion pack: headlines (word-split text) move word by word; everything else is the pack's own.
  TF.fxMotion = function (M, S) {
    const lvl = (S.fx || {}).kinetic || "off";
    if (lvl === "off") return M;
    const K = Object.assign({}, M);
    K.head = function (s, at) {
      const w = words(s);
      if (!w) return M.head(s, at);
      if (lvl === "subtle") {
        tl.fromTo(w, { yPercent: 118, rotation: 5, transformOrigin: "0% 100%" },
          { yPercent: 0, rotation: 0, duration: 0.85, ease: "back.out(1.4)", stagger: 0.065 }, at);
      } else {
        tl.fromTo(w, { opacity: 0, yPercent: 45, rotationX: -88, scale: 1.08, transformPerspective: 900, transformOrigin: "50% 100%" },
          { opacity: 1, yPercent: 0, rotationX: 0, scale: 1, duration: 0.8, ease: "back.out(1.7)", stagger: 0.075 }, at);
      }
      const n = TF.q(w).length;
      if (TF.exists(s + " .hlw")) K.pop(s + " .hlw", at + 0.35 + n * (lvl === "rich" ? 0.075 : 0.065) + 0.45);
    };
    // emphasis words: a short scale punch (plus a lift in rich), on the word's outer box so it never
    // fights the entrance tween on the inner span
    K.pop = function (sel, at) {
      const big = lvl === "rich" ? 1.14 : 1.07;
      tl.fromTo(sel, { scale: 1, y: 0 }, { scale: big, y: lvl === "rich" ? -6 : 0, duration: 0.18, ease: "power2.out", immediateRender: false }, at);
      tl.fromTo(sel, { scale: big, y: lvl === "rich" ? -6 : 0 }, { scale: 1, y: 0, duration: 0.5, ease: "elastic.out(1, 0.5)", immediateRender: false }, at + 0.18);
    };
    // kinetic line: words land one by one across a spoken window [a, b] (statement scenes)
    K.say = function (s, a, b) {
      const w = words(s);
      if (!w) return M.head(s, a);
      const els = TF.q(w), n = els.length, span = Math.max(0.6, (b - a) * 0.8);
      els.forEach((el, i) => {
        const t = a + (n > 1 ? (span * i) / (n - 1) : 0);
        if (lvl === "rich") {
          tl.fromTo(el, { opacity: 0, scale: 1.9, yPercent: -18 }, { opacity: 1, scale: 1, yPercent: 0, duration: 0.32, ease: "power4.out" }, t);
        } else {
          tl.fromTo(el, { opacity: 0, yPercent: 70 }, { opacity: 1, yPercent: 0, duration: 0.45, ease: "power3.out" }, t);
        }
        if (el.parentElement.classList.contains("hlw")) K.pop(el.parentElement, t + 0.4);
      });
    };
    return K;
  };

  // -------------------------------------------------------------- camera + ambient (after the scenes are built)
  TF.fxAfter = function (S) {
    const fx = S.fx || {};
    const dark = TF.exists("#root.dark");
    S.scenes.forEach((sc, i) => {
      const root = "#" + sc.id, d = Math.max(1, sc.end - sc.start), rnd = seeded(sc.id + "|" + S.total);
      // camera
      if (fx.camera && fx.camera !== "off") {
        const rich = fx.camera === "rich", dir = i % 2 ? 1 : -1;
        // small numbers on purpose: content must stay inside the safe area at the end of the move
        tl.fromTo(root + " .cam", { scale: 1, xPercent: rich ? -0.5 * dir : 0 },
          { scale: rich ? 1.035 : 1.025, xPercent: rich ? 0.5 * dir : 0, duration: d, ease: "none" }, sc.start);
        tl.fromTo(root + " .ground", { scale: rich ? 1.07 : 1.04, xPercent: rich ? 1.2 * dir : 0 },
          { scale: 1, xPercent: rich ? -1.2 * dir : 0, duration: d, ease: "none" }, sc.start);
        const f = sc.focus;
        if (rich && f && f.key in sc.R) {
          const at = sc.R[f.key] + 0.15, hold = Math.min(1.6, Math.max(0.6, sc.end - at - 1.6));
          const el = document.querySelector(root + " " + f.sel), box = document.querySelector(root + " .cam2");
          let origin = "50% 46%";
          if (el && box) {
            const r = el.getBoundingClientRect(), c = box.getBoundingClientRect();
            if (r.width && c.width) {
              const ox = Math.min(85, Math.max(15, ((r.left + r.width / 2 - c.left) / c.width) * 100));
              const oy = Math.min(85, Math.max(15, ((r.top + r.height / 2 - c.top) / c.height) * 100));
              origin = ox.toFixed(1) + "% " + oy.toFixed(1) + "%";
            }
          }
          if (at + hold + 1.2 < sc.end) {
            tl.fromTo(root + " .cam2", { scale: 1, transformOrigin: origin }, { scale: 1.045, duration: 0.6, ease: "power3.out" }, at);
            tl.fromTo(root + " .cam2", { scale: 1.045 }, { scale: 1, duration: 1.2, ease: "power2.inOut", immediateRender: false }, at + 0.6 + hold);
          }
        }
      }
      // ambient light
      if (fx.ambient && fx.ambient !== "off") {
        const rich = fx.ambient === "rich";
        // peaks are contrast-capped by the renderer for this scene's ground (see ambient_light)
        const amb = document.querySelector(root + " .amb"), cs = amb ? getComputedStyle(amb) : null;
        const p1 = cs ? parseFloat(cs.getPropertyValue("--amb-a1")) || 0 : 0;
        const p2 = cs ? parseFloat(cs.getPropertyValue("--amb-a2")) || 0 : 0;
        TF.q(root + " .amb .ab").forEach((el, k) => {
          const x0 = (rnd() * 0.9 - 0.25) * S.W, y0 = (rnd() * 0.9 - 0.25) * S.H;
          const dx = (rnd() - 0.5) * 0.3 * S.W, dy = (rnd() - 0.5) * 0.25 * S.H;
          const s0 = 0.85 + rnd() * 0.3, s1 = s0 * (1.1 + rnd() * 0.2);
          tl.fromTo(el, { x: x0, y: y0, scale: s0 }, { x: x0 + dx, y: y0 + dy, scale: s1, duration: d, ease: "sine.inOut" }, sc.start);
          tl.fromTo(el, { opacity: 0 }, { opacity: k % 2 ? p2 : p1, duration: 1.4, ease: "sine.out" }, sc.start);
        });
        TF.q(root + " .amb .ag").forEach((el) => {
          const y = (0.15 + rnd() * 0.4) * S.H;
          tl.fromTo(el, { x: -0.5 * S.W, y: y }, { x: 0.65 * S.W, y: y + (rnd() - 0.5) * 0.3 * S.H, duration: d, ease: "sine.inOut" }, sc.start);
          tl.fromTo(el, { opacity: 0 }, { opacity: p1, duration: 1.2 }, sc.start);
        });
        TF.q(root + " .amb .pt").forEach((el) => {
          const x = rnd() * S.W, y0 = (0.55 + rnd() * 0.55) * S.H, rise = (0.25 + rnd() * 0.35) * S.H;
          const delay = rnd() * Math.min(3, d * 0.3), a = Math.min(0.6, (0.25 + rnd() * 0.35) * (dark ? 1.2 : 1)) * (p1 > 0.05 ? 1 : 0.4);
          tl.fromTo(el, { x: x, y: y0 }, { x: x + (rnd() - 0.5) * 120, y: y0 - rise, duration: d, ease: "none" }, sc.start);
          tl.fromTo(el, { opacity: 0 }, { opacity: a, duration: 1.2, ease: "sine.out" }, sc.start + delay);
          tl.fromTo(el, { opacity: a }, { opacity: 0, duration: 1.0, ease: "sine.in", immediateRender: false }, Math.max(sc.start + delay + 1.3, sc.end - 1.0));
        });
      }
    });
  };
})();
