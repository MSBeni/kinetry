TF.comp("checklist", (c) => {
  const M = c.M, n = c.n.items || 0;
  M.head(c.$("h2"), c.at("headline"));
  for (let i = 0; i < n; i++) {
    const at = c.at("items." + i);
    TF.preview(c.$(".ck-" + i), c.at("headline") + 0.5 + i * 0.1, at, { opacity: 0, x: 30 }, 0.45, 0.6);
    TF.draw(c.$(".ck-" + i + " path"), at + 0.1, 0.5, "power2.out");
  }
});
