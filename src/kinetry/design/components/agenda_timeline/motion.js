TF.comp("agenda_timeline", (c) => {
  const M = c.M, n = c.n.stops || 0, vert = c.layout === "vertical";
  const ax = vert ? "scaleY" : "scaleX", ink = TF.v(c.root, "--ink"), bg = TF.v(c.root, "--bg");
  M.head(c.$("h2"), c.at("headline"));
  TF.tl.fromTo(c.$(".trk"), { opacity: 0 }, { opacity: 1, duration: 0.6 }, c.at("headline") + 0.3);
  TF.tl.set(c.$(".prog"), { [ax]: 0 }, c.start);
  let last = 0, lastAt = c.start;
  for (let i = 0; i < n; i++) {
    const at = c.at("stops." + i), v = (i + 0.5) / n, t0 = Math.max(at - 0.3, lastAt);
    TF.tl.fromTo(c.$(".prog"), { [ax]: last }, { [ax]: v, duration: 0.8, ease: "power3.inOut", immediateRender: false }, t0);
    last = v; lastAt = t0 + 0.8;
    M.mark(c.$(".st-" + i + " .dot"), at);
    TF.tl.to(c.$(".st-" + i + " .dot"), { backgroundColor: ink, color: bg, duration: 0.3 }, at + 0.25);
    M.item(c.$(".st-" + i + " .sb"), at + 0.1);
  }
  if (n) TF.tl.fromTo(c.$(".prog"), { [ax]: last }, { [ax]: 1, duration: 1.0, ease: "power2.inOut", immediateRender: false }, Math.max(lastAt, c.at("stops." + (n - 1)) + 1.4));
});
