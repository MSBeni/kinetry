TF.comp("journey", (c) => {
  const M = c.M, vert = c.layout === "ladder";
  M.head(c.$("h2"), c.at("headline"));
  if (c.has(".question")) M.text(c.$(".question"), c.at("question"));
  const t0 = c.at("steps");
  if (vert) TF.tl.fromTo(c.$(".trk"), { scaleY: 0 }, { scaleY: 1, duration: 0.9, ease: "power2.inOut" }, t0);
  else M.line(c.$(".trk"), t0, 0.9);
  for (let i = 0; i < (c.n.steps || 0); i++) M.item(c.$(".nd-" + i), t0 + 0.15 + i * 0.12);
  const tp = c.at("progress"), d = Math.max(1.2, Math.min(3, c.end - tp - 1));
  if (vert) TF.tl.fromTo(c.$(".prog"), { scaleY: 0 }, { scaleY: 1, duration: d, ease: "power1.inOut" }, tp);
  else TF.tl.fromTo(c.$(".prog"), { scaleX: 0 }, { scaleX: 1, duration: d, ease: "power1.inOut" }, tp);
  M.emph(c.$(".now .dn"), tp + 0.3);
});
