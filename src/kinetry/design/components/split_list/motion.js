TF.comp("split_list", (c) => {
  const M = c.M;
  M.head(c.$("h2"), c.at("headline"));
  if (c.has(".aside")) M.text(c.$(".aside"), c.at("aside"));
  for (let i = 0; i < (c.n.tags || 0); i++) M.mark(c.$(".tag-" + i), c.at("tags." + i));
  M.card(c.$(".panel"), c.at("panel"));
  for (let i = 0; i < (c.n.items || 0); i++) M.item(c.$(".item-" + i), c.at("items." + i));
});
