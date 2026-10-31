/* bold: words slam in, fast slides, punchy emphasis. */
(function () {
  const W = (s) => (TF.exists(s + " .w") ? s + " .w > span" : null);
  TF.motion("bold", {
    head(s, at) {
      const w = W(s);
      if (w) TF.tl.fromTo(w, { yPercent: 105, skewY: 8 }, { yPercent: 0, skewY: 0, duration: 0.55, ease: "power4.out", stagger: 0.06 }, at);
      else TF.tl.fromTo(s, { opacity: 0, scale: 1.25 }, { opacity: 1, scale: 1, duration: 0.5, ease: "power4.out" }, at);
    },
    text(s, at) { TF.tl.fromTo(s, { opacity: 0, x: -60 }, { opacity: 1, x: 0, duration: 0.5, ease: "power4.out" }, at); },
    item(s, at) { TF.tl.fromTo(s, { opacity: 0, x: 90 }, { opacity: 1, x: 0, duration: 0.45, ease: "power4.out" }, at); },
    card(s, at) { TF.tl.fromTo(s, { opacity: 0, scale: 0.85, y: 30 }, { opacity: 1, scale: 1, y: 0, duration: 0.5, ease: "power4.out" }, at); },
    mark(s, at) { TF.tl.fromTo(s, { opacity: 0, scale: 0 }, { opacity: 1, scale: 1, duration: 0.45, ease: "back.out(4)" }, at); },
    emph(s, at) { TF.tl.fromTo(s, { scale: 1 }, { scale: 1.08, duration: 0.16, yoyo: true, repeat: 1, ease: "power2.out" }, at); },
    line(s, at, d = 0.45) { TF.tl.fromTo(s, { scaleX: 0 }, { scaleX: 1, duration: d, ease: "power4.out" }, at); },
    out(s, end) { TF.tl.to(s, { opacity: 0, scale: 1.06, duration: 0.32, ease: "power2.in" }, end - 0.35); },
  });
})();
