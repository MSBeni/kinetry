TF.comp("steps_path", (c) => {
  const M = c.M, n = c.n.steps || 0;
  M.head(c.$("h2"), c.at("headline"));
  for (let i = 0; i < n; i++) {
    const at = c.at("steps." + i);
    if (i > 0) TF.tl.fromTo(c.$(".cn-" + (i - 1)), { clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0% 0)", duration: 0.7, ease: "power1.inOut" }, at - 0.4);
    M.mark(c.$(".ps-" + i + " .badge"), at);
    M.item(c.$(".ps-" + i + " .pt"), at + 0.15);
  }
});
