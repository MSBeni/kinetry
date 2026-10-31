TF.comp("title", (c) => {
  const M = c.M;
  if (c.layout === "band") M.card(c.$(".tblock"), c.start + 0.2);
  M.head(c.$("h1"), c.at("headline"));
  if (c.has(".kicker")) M.text(c.$(".kicker"), c.at("kicker"));
  for (let i = 0; i < (c.n.chips || 0); i++) M.item(c.$(".chip-" + i), c.at("chips." + i));
  if (c.has(".hero-ic")) { M.mark(c.$(".hero-ic"), c.at("icon")); TF.draw(c.$(".hero-ic svg"), c.at("icon") + 0.1, 1.3); }
});
