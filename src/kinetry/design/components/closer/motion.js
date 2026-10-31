TF.comp("closer", (c) => {
  const M = c.M;
  if (c.has(".pre")) M.text(c.$(".pre"), c.at("pre"));
  M.head(c.$("h2"), c.at("headline"));
  M.line(c.$(".rule"), c.at("headline") + 0.5);
  if (c.has(".meta")) M.text(c.$(".meta"), c.at("meta"));
  if (c.has(".ci")) { M.mark(c.$(".ci"), c.at("icon")); TF.draw(c.$(".ci svg"), c.at("icon") + 0.1, 1.0); }
});
