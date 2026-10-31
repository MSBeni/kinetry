/* Illustrations animate part by part from class names: a-pop (scale in), a-rise (slide up), a-grow / a-grow-x
   (grow from an edge), a-draw (stroke draws on), a-fly (arrives from the side). With the layer on rich, parts
   marked a-float, a-swing and a-spin keep moving gently for the rest of the scene, in finite, seek-safe loops.
   A caller's Lottie is driven from the same clock (see TF.lottie in fx.js). */
TF.comp("illustration", (c) => {
  const M = c.M, at = c.at("art"), rich = TF.exists("#root.fx-ill-rich");
  const q = (s) => TF.q(c.$(".art " + s));
  let t = at;
  q(".a-pop, .a-rise, .a-grow, .a-grow-x, .a-fly").forEach((el, i) => {
    const k = el.classList;
    const origin = k.contains("a-grow") ? "50% 100%" : k.contains("a-grow-x") ? "0% 50%" : "50% 50%";
    const from = k.contains("a-rise") ? { opacity: 0, y: 40 } : k.contains("a-grow") ? { scaleY: 0 } :
      k.contains("a-grow-x") ? { scaleX: 0 } : k.contains("a-fly") ? { opacity: 0, x: -160, y: 100 } : { opacity: 0, scale: 0 };
    from.transformOrigin = origin;
    const to = { opacity: 1, x: 0, y: 0, scale: 1, scaleX: 1, scaleY: 1, duration: k.contains("a-fly") ? 0.5 : 0.55,
      ease: k.contains("a-pop") ? "back.out(2)" : "power3.out" };
    TF.tl.fromTo(el, from, to, at + Math.min(1.6, i * 0.07));
    t = Math.max(t, at + Math.min(1.6, i * 0.07) + 0.55);
  });
  const draws = q(".a-draw");
  draws.forEach((el, i) => {
    el.setAttribute("data-d", String(i));  // TF.draw takes a selector
    TF.draw(c.$('.art [data-d="' + i + '"]'), at + 0.3 + i * 0.12, 0.6);
  });
  const settle = Math.max(t, at + 0.3 + draws.length * 0.12 + 0.6);
  if (rich) {
    const span = Math.max(0, c.end - settle - 0.2);
    const loop = (els, from, to, period) => {
      const reps = Math.floor(span / period);
      if (reps < 1) return;
      els.forEach((el) => TF.tl.fromTo(el, from, { ...to, duration: period / 2, yoyo: true, repeat: reps * 2 - 1, ease: "sine.inOut", immediateRender: false }, settle));
    };
    loop(q(".a-float"), { y: 0 }, { y: -10 }, 2.4);
    loop(q(".a-swing"), { rotation: -4, transformOrigin: "50% 100%" }, { rotation: 4 }, 2.8);
    const spins = q(".a-spin"), slow = q(".a-spin-slow");
    if (span > 0.5) {
      spins.forEach((el) => TF.tl.fromTo(el, { rotation: 0, transformOrigin: el.classList.contains("hand-m") ? "50% 100%" : "50% 50%" }, { rotation: 360 * Math.max(1, Math.round(span / 6)), duration: span, ease: "none", immediateRender: false }, settle));
      slow.forEach((el) => TF.tl.fromTo(el, { rotation: 0, transformOrigin: "50% 100%" }, { rotation: 30 * Math.max(1, Math.round(span / 6)), duration: span, ease: "none", immediateRender: false }, settle));
    }
  }
  if (c.has(".lot")) {
    M.card(c.$(".ill"), at - 0.1);
    if (TF.lottie) TF.lottie(c.$(".lot"), at, c.end, rich);
  }
  M.head(c.$("h2"), c.at("headline"));
  if (c.has(".body")) M.text(c.$(".body"), c.at("body"));
});
