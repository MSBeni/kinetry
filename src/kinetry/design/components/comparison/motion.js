TF.comp("comparison", (c) => {
  const M = c.M;
  M.head(c.$("h2"), c.at("headline"));
  for (let i = 0; i < (c.n.columns || 0); i++) {
    const at = c.at("columns." + i);
    M.card(c.$(".cc-" + i), at);
    TF.q(c.$(".cc-" + i + " .cp")).forEach((el, j) => M.item(c.$(".cc-" + i + " .cp:nth-of-type(" + (j + 2) + ")"), at + 0.25 + j * 0.15));
    if (c.has(".cc-" + i + ".pick .pk")) M.mark(c.$(".cc-" + i + " .pk"), at + 0.5);
  }
});
