TF.comp("do_dont", (c) => {
  const M = c.M;
  if (c.has("h2")) M.head(c.$("h2"), c.at("headline"));
  ["do", "dont"].forEach((side) => {
    const at = c.at(side);
    M.card(c.$(".dd-" + side), at - 0.15);
    M.mark(c.$(".dd-" + side + " .dic"), at + 0.15);
    for (let i = 0; i < (c.n[side] || 0); i++) {
      const k = side + "." + i, t = c.beat(k) ? c.at(k) : at + 0.5 + i * 0.9;  // own beat, or a paced stagger
      M.item(c.$(".dr-" + side + "-" + i), t);
    }
  });
  if (c.n.dont) TF.tl.fromTo(c.$(".dd-do"), { opacity: 1 }, { opacity: 0.6, duration: 0.3, immediateRender: false }, c.at("dont"));
});
