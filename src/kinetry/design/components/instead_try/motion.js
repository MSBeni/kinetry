TF.comp("instead_try", (c) => {
  const M = c.M, ti = c.at("instead"), tt = c.at("try");
  M.card(c.$(".was"), ti - 0.1);
  TF.draw(c.$(".strike"), Math.max(c.at("strike"), ti + 0.9), 0.45, "power2.out");
  TF.tl.fromTo(c.$(".was"), { opacity: 1 }, { opacity: 0.6, duration: 0.3, immediateRender: false }, tt);
  TF.draw(c.$(".arrow"), tt - 0.25, 0.5);
  M.card(c.$(".now"), tt + 0.1);
  M.emph(c.$(".now"), tt + 1.6);
});
