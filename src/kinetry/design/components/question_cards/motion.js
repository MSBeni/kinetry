TF.comp("question_cards", (c) => {
  const M = c.M;
  M.head(c.$("h2"), c.at("headline"));
  for (let i = 0; i < (c.n.cards || 0); i++) { M.card(c.$(".qc-" + i), c.at("cards." + i)); M.mark(c.$(".qc-" + i + " .qic"), c.at("cards." + i) + 0.2); }
});
