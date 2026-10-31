TF.comp("definition", (c) => {
  const M = c.M;
  M.head(c.$("h2"), c.at("term"));
  if (c.has(".kind")) M.text(c.$(".kind"), c.at("term") + 0.5);
  if (c.has(".rule")) M.line(c.$(".rule"), c.at("term") + 0.4);
  if (c.layout === "card") M.card(c.$(".def"), c.at("definition") - 0.15);
  M.text(c.$(".def .r-h3"), c.at("definition"));
  if (c.has(".ex")) M.text(c.$(".ex"), c.at("example"));
});
