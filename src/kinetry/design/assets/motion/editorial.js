/* editorial: words rise out of masks, rules draw, nothing bounces. */
(function () {
  const W = (s) => (TF.exists(s + " .w") ? s + " .w > span" : null);
  TF.motion("editorial", {
    head(s, at) {
      const w = W(s);
      if (w) TF.tl.fromTo(w, { yPercent: 115 }, { yPercent: 0, duration: 1.1, ease: "expo.out", stagger: 0.045 }, at);
      else TF.tl.fromTo(s, { opacity: 0, y: 26 }, { opacity: 1, y: 0, duration: 1.0, ease: "expo.out" }, at);
    },
    text(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.9, ease: "expo.out" }, at); },
    item(s, at) { TF.tl.fromTo(s, { opacity: 0, x: 34 }, { opacity: 1, x: 0, duration: 0.8, ease: "expo.out" }, at); },
    card(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 34 }, { opacity: 1, y: 0, duration: 0.9, ease: "expo.out" }, at); },
    mark(s, at) { TF.tl.fromTo(s, { opacity: 0, scale: 0.4 }, { opacity: 1, scale: 1, duration: 0.7, ease: "back.out(2)" }, at); },
    emph(s, at) {
      if (TF.exists(s + " .hl")) TF.tl.fromTo(s + " .hl", { backgroundSize: "0% 32%" }, { backgroundSize: "100% 32%", duration: 0.9, ease: "power2.inOut" }, at);
      else TF.tl.fromTo(s, { opacity: 0.55 }, { opacity: 1, duration: 0.6, ease: "power1.out" }, at);
    },
    line(s, at, d = 1.0) { TF.tl.fromTo(s, { scaleX: 0 }, { scaleX: 1, duration: d, ease: "power3.inOut" }, at); },
    out(s, end) { TF.tl.to(s, { opacity: 0, y: -14, duration: 0.5, ease: "power2.in" }, end - 0.55); },
  });
})();
