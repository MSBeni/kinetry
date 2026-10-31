TF.comp("bar_chart", (c) => {
  const M = c.M, rows = c.layout === "rows", vals = (c.sc.data && c.sc.data.bars) || [];
  M.head(c.$("h2"), c.at("headline"));
  const at = c.at("bars");
  for (let i = 0; i < vals.length; i++) {
    const t = at + 0.15 * i;
    if (rows) TF.tl.fromTo(c.$(".bc-" + i + " .bar"), { scaleX: 0 }, { scaleX: 1, duration: 1.1, ease: "power3.out" }, t);
    else TF.tl.fromTo(c.$(".bc-" + i + " .bar"), { scaleY: 0 }, { scaleY: 1, duration: 1.1, ease: "power3.out" }, t);
    TF.tl.fromTo(c.$(".bc-" + i + " .bv"), { opacity: 0 }, { opacity: 1, duration: 0.3 }, t);
    const dec = String(vals[i]).includes(".") ? 1 : 0;
    TF.count(c.$(".bc-" + i + " .cnum"), vals[i], t, 1.1, dec);
    M.text(c.$(".bc-" + i + " .bl"), t);
  }
  if (c.has(".hi")) M.emph(c.$(".hi .bv"), at + 0.15 * vals.length + 1.0);
  if (c.has(".note")) M.text(c.$(".note"), c.at("note"));
});
