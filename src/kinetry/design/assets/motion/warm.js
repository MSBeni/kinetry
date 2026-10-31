/* warm: things pop and settle, a little wobble, scenes bounce away. */
(function () {
  const W = (s) => (TF.exists(s + " .w") ? s + " .w > span" : null);
  const B = "back.out(2.2)";
  TF.motion("warm", {
    head(s, at) {
      const w = W(s);
      if (w) TF.tl.fromTo(w, { opacity: 0, scale: 0.3, rotation: -8, yPercent: 30 }, { opacity: 1, scale: 1, rotation: 0, yPercent: 0, duration: 0.6, ease: B, stagger: 0.1 }, at);
      else TF.tl.fromTo(s, { opacity: 0, scale: 0.6, rotation: -4 }, { opacity: 1, scale: 1, rotation: 0, duration: 0.6, ease: B }, at);
    },
    text(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 46 }, { opacity: 1, y: 0, duration: 0.6, ease: B }, at); },
    item(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 40, rotation: -3 }, { opacity: 1, y: 0, rotation: 0, duration: 0.6, ease: B }, at); },
    card(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 80, rotation: 5 }, { opacity: 1, y: 0, rotation: 0, duration: 0.7, ease: "back.out(1.8)" }, at); },
    mark(s, at) { TF.tl.fromTo(s, { opacity: 0, scale: 0.3, rotation: -12 }, { opacity: 1, scale: 1, rotation: 0, duration: 0.6, ease: B }, at); },
    emph(s, at) {
      // a little wiggle that settles back to level
      [[0, -3, 0.1], [-3, 3, 0.16], [3, -2, 0.14], [-2, 0, 0.12]].reduce((t, [a, b, d]) => {
        TF.tl.fromTo(s, { rotation: a }, { rotation: b, duration: d, ease: "sine.inOut", immediateRender: false }, t);
        return t + d;
      }, at);
    },
    line(s, at, d = 0.7) { TF.tl.fromTo(s, { scaleX: 0 }, { scaleX: 1, duration: d, ease: "back.out(1.6)" }, at); },
    out(s, end) { TF.tl.to(s, { opacity: 0, scale: 0.93, rotation: -2, duration: 0.45, ease: "back.in(2)" }, end - 0.5); },
  });
})();
