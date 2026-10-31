/* Adapted from the HyperFrames registry's decline-chart and data-chart (https://github.com/heygen-com/hyperframes, Apache-2.0). */
TF.comp("line_chart", (c) => {
  const M = c.M, n = c.n.points || ((c.sc.data && c.sc.data.points) || []).length;
  M.head(c.$("h2"), c.at("headline"));
  const at = c.at("points"), D = 1.8;
  TF.tl.fromTo(c.$(".grid"), { opacity: 0 }, { opacity: 1, duration: 0.4 }, at - 0.3);
  TF.tl.fromTo(c.$(".lines"), { clipPath: "inset(-10% 100% -10% 0)" }, { clipPath: "inset(-10% 0% -10% 0)", duration: D, ease: "none" }, at);
  for (let i = 0; i < n; i++) {
    const t = at + D * (n > 1 ? i / (n - 1) : 0);
    M.mark(c.$(".p-" + i), t - 0.05);
    if (c.has(".pv-" + i)) TF.tl.fromTo(c.$(".pv-" + i), { opacity: 0 }, { opacity: 1, duration: 0.3 }, t);
    M.text(c.$(".xli:nth-child(" + (i + 1) + ")"), t - 0.1);
  }
  if (c.has(".pv.hi")) M.emph(c.$(".pv.hi"), at + D + 0.2);
  if (c.has(".note")) M.text(c.$(".note"), c.at("note"));
});
