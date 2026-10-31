TF.comp("icon_grid", (c) => {
  const M = c.M;
  M.head(c.$("h2"), c.at("headline"));
  for (let i = 0; i < (c.n.items || 0); i++) {
    const at = c.at("items." + i);
    M.mark(c.$(".ig-" + i + " .igi"), at);
    TF.draw(c.$(".ig-" + i + " .igi svg"), at + 0.1, 0.9);
    M.item(c.$(".ig-" + i + " .igt"), at + 0.15);
  }
});
