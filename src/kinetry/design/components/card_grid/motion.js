TF.comp("card_grid", (c) => {
  const M = c.M;
  M.head(c.$("h2"), c.at("headline"));
  if (c.has(".sub")) M.text(c.$(".sub"), c.at("sub"));
  for (let i = 0; i < (c.n.cards || 0); i++) M.card(c.$(".gc-" + i), c.at("cards." + i));
  if (c.has(".strip")) {
    M.card(c.$(".strip"), c.at("strip"));
    for (let i = 0; i < (c.n.strip_items || 0); i++) M.item(c.$(".si-" + i), c.at("strip." + i));
  }
});
