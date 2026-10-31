/* Kinetry runtime: builds one paused GSAP timeline from the scene spec the renderer writes.
   Seek-safe by construction: no timers, no randomness, every tween placed at an absolute time.
   Components, motion packs, transitions and chrome register themselves on window.TF. */
(function () {
  const tl = gsap.timeline({ paused: true });
  const TF = (window.TF = { tl, comps: {}, motions: {}, trans: {}, chromes: {} });
  TF.comp = (id, fn) => (TF.comps[id] = fn);
  TF.motion = (id, m) => (TF.motions[id] = m);
  TF.transition = (id, fn) => (TF.trans[id] = fn);
  TF.chrome = (id, fn) => (TF.chromes[id] = fn);
  TF.q = (sel) => Array.from(document.querySelectorAll(sel));
  TF.exists = (sel) => !!document.querySelector(sel);
  // resolved value of a design token on an element (GSAP can't tween var(--x) itself)
  TF.v = (sel, name) => { const el = document.querySelector(sel) || document.documentElement; return getComputedStyle(el).getPropertyValue(name).trim(); };
  const SHAPES = "path,circle,rect,line,polyline,polygon,ellipse";

  // stroke draw-on for SVG paths (icons, ticks, underlines, arrows)
  TF.draw = function (sel, at, d = 0.8, ease = "power1.inOut", stagger = 0.08) {
    let n = 0;
    TF.q(sel).forEach((el) => {
      const shapes = el.matches(SHAPES) ? [el] : Array.from(el.querySelectorAll(SHAPES));
      shapes.forEach((p) => {
        let len = 120;
        try { len = Math.ceil(p.getTotalLength()) + 2; } catch (e) { /* non-geometry */ }
        tl.fromTo(p, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: d, ease }, at + n * stagger);
        n++;
      });
    });
  };

  // numeric count-up on an element holding just the number
  TF.count = function (sel, to, at, d = 1.6, decimals = 0) {
    TF.q(sel).forEach((el) => {
      tl.fromTo(el, { innerText: 0 }, { innerText: to, duration: d, ease: "power2.out", snap: { innerText: decimals ? 1 / Math.pow(10, decimals) : 1 } }, at);
    });
  };

  // An item that shows dimmed ("coming up") and then lights up when it's spoken. If it's spoken before the
  // dim preview would finish, it simply appears. Explicit from-values keep every frame independent of
  // seek order (parallel render workers must agree).
  TF.preview = function (sel, previewAt, at, from, dim, pd = 0.5) {
    const to = {};
    Object.keys(from).forEach((k) => { if (k !== "opacity") to[k] = 0; });
    if (at <= previewAt + pd) {
      tl.fromTo(sel, from, { ...to, opacity: 1, duration: Math.max(0.3, pd), ease: "power3.out" }, at);
    } else {
      tl.fromTo(sel, from, { ...to, opacity: dim, duration: pd, ease: "power3.out" }, previewAt);
      tl.fromTo(sel, { opacity: dim }, { opacity: 1, duration: 0.3, ease: "power1.out", immediateRender: false }, at);
    }
  };

  TF.run = function (S) {
    let M = (TF.M = TF.motions[S.motion] || TF.motions.minimal);
    if (S.fx && TF.fxMotion) M = TF.M = TF.fxMotion(M, S); // kinetic type wraps the style's motion pack
    S.scenes.forEach((sc) => {
      const root = "#" + sc.id;
      const ctx = {
        id: sc.id, root, sc, tl, M, S, fmt: S.fmt, W: S.W, H: S.H, layout: sc.layout,
        start: sc.start, end: sc.end, n: sc.n || {}, speak: sc.speak || [],
        $: (s) => root + " " + s,
        has: (s) => TF.exists(root + " " + s),
        at: (k) => {
          if (k in sc.R) return sc.R[k];
          const base = k.split(".")[0];
          return base in sc.R ? sc.R[base] : sc.start + 0.4;
        },
        beat: (k) => (sc.B || []).includes(k),  // a beat reveals exactly this key
      };
      const fn = TF.comps[sc.type];
      if (fn) fn(ctx);
      if (sc.eyebrow) M.text(root + " .eyebrow", sc.start + 0.15);
    });
    if (S.fx && TF.fxAfter) TF.fxAfter(S); // camera moves and ambient light
    S.trans.forEach((t) => (TF.trans[t.name] || TF.trans.exit)(t, S));
    (TF.chromes[S.chrome] || TF.chromes.none || (() => {}))(S);
    // chrome fades in on the first scene that isn't on the brand color, and steps aside during those scenes
    if (S.chrome !== "none" && TF.exists(".chrome")) {
      tl.set(".chrome", { opacity: 0 }, 0);
      let shown = false, ever = false;
      S.scenes.forEach((sc) => {
        if (!sc.inv && !shown) {
          tl.fromTo(".chrome", { opacity: 0 }, { opacity: 1, duration: ever ? 0.4 : 0.7, ease: "power1.out", immediateRender: false }, sc.start + 0.15);
          shown = ever = true;
        } else if (sc.inv && shown) {
          tl.fromTo(".chrome", { opacity: 1 }, { opacity: 0, duration: 0.3, immediateRender: false }, sc.start);
          shown = false;
        }
      });
    }
    S.caps.forEach((c) => {
      tl.fromTo("#" + c.id, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.25, ease: "power2.out" }, c.a);
      tl.to("#" + c.id, { opacity: 0, duration: 0.15 }, c.b);
    });
    tl.to("#root", { opacity: 0, duration: 0.5 }, S.total - 0.5);
    window.__timelines = window.__timelines || {};
    window.__timelines["main"] = tl;
    tl.seek(0);
  };

  // -------------------------------------------------------------- transitions
  const sc = (id) => "#" + id + " > .sc";
  TF.transition("exit", (t) => TF.M.out(sc(t.from), t.at));
  TF.transition("cut", () => {});
  TF.transition("fade", (t) => {
    tl.to(sc(t.from), { opacity: 0, duration: t.d, ease: "none" }, t.at);
    tl.fromTo(sc(t.to), { opacity: 0 }, { opacity: 1, duration: t.d * 0.7, ease: "power1.out" }, t.at);
  });
  TF.transition("push", (t, S) => {
    const dx = S.W * 0.35;
    tl.to(sc(t.from), { x: -dx, opacity: 0, duration: t.d, ease: "power3.inOut" }, t.at);
    tl.fromTo(sc(t.to), { x: dx, opacity: 0 }, { x: 0, opacity: 1, duration: t.d, ease: "power3.inOut" }, t.at);
  });
  TF.transition("rise", (t, S) => {
    const dy = S.H * 0.25;
    tl.to(sc(t.from), { y: -dy, opacity: 0, duration: t.d, ease: "power3.inOut" }, t.at);
    tl.fromTo(sc(t.to), { y: dy, opacity: 0 }, { y: 0, opacity: 1, duration: t.d, ease: "power3.inOut" }, t.at);
  });
  TF.transition("iris", (t) => {
    tl.fromTo(sc(t.to), { clipPath: "circle(0% at 50% 50%)" }, { clipPath: "circle(75% at 50% 50%)", duration: t.d, ease: "power2.inOut" }, t.at);
  });
  TF.transition("wipe", (t) => {
    const p = "#tr-" + t.k;
    tl.fromTo(p, { scaleX: 0, transformOrigin: "left center" }, { scaleX: 1, duration: t.d / 2, ease: "power3.in" }, t.at - t.d / 2);
    tl.fromTo(p, { scaleX: 1, transformOrigin: "right center" }, { scaleX: 0, duration: t.d / 2, ease: "power3.out", immediateRender: false }, t.at);
  });
  TF.transition("scan", (t, S) => {
    const p = "#tr-" + t.k;
    tl.fromTo(p, { y: -10, opacity: 1 }, { y: S.H + 10, opacity: 1, duration: t.d, ease: "power2.in", immediateRender: false }, t.at);
    tl.set(p, { opacity: 0 }, t.at + t.d + 0.01);
  });
  TF.transition("scribble", () => {}); // sub-composition: runs its own timeline

  // -------------------------------------------------------------- chrome
  TF.chrome("none", () => {});
  const intro = () => {}; // chrome opacity is scheduled once in TF.run
  const ticks = (S) => S.scenes.forEach((s, i) => tl.fromTo(".chrome .tk" + i, { scaleX: 0 }, { scaleX: 1, duration: s.end - s.start, ease: "none" }, s.start));
  const counter = (S) => S.scenes.forEach((s, i) => { tl.set(".chrome .cn" + i, { opacity: 1 }, s.start); tl.set(".chrome .cn" + i, { opacity: 0 }, s.end - 0.01); });
  TF.chrome("rule", (S) => { intro(S); tl.fromTo(".chrome .hair", { scaleX: 0 }, { scaleX: 1, duration: 1.3, ease: "power3.inOut" }, 0.3); counter(S); });
  TF.chrome("status", (S) => { intro(S); ticks(S); });
  TF.chrome("wordmark", (S) => { intro(S); });
  TF.chrome("corner", (S) => { intro(S); counter(S); });
  TF.chrome("line", (S) => { intro(S); tl.fromTo(".chrome .pl", { scaleX: 0 }, { scaleX: 1, duration: S.total, ease: "none" }, 0); });
  TF.chrome("navbar", (S) => {
    intro(S);
    S.scenes.forEach((s, i) => {
      tl.fromTo(".chrome .nf" + i, { scaleX: 0 }, { scaleX: 1, duration: s.end - s.start, ease: "none" }, s.start);
      tl.to(".chrome .nl" + i, { opacity: 1, duration: 0.3 }, s.start);
    });
  });
  TF.chrome("bar", (S) => { intro(S); ticks(S); });
})();
