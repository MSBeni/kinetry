TF.comp("chapter", (c) => {
  const M = c.M;
  if (c.has(".num")) M.mark(c.$(".num"), c.at("number"));
  if (c.layout === "band") M.card(c.$(".tb"), c.at("title") - 0.15);
  M.head(c.$("h2"), c.at("title"));
  if (c.has(".sub")) M.text(c.$(".sub"), c.at("sub"));
});
