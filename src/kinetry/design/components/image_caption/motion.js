TF.comp("image_caption", (c) => {
  const M = c.M, at = c.at("image");
  // the picture arrives, then drifts slowly for the rest of the scene (Ken Burns), seek-safe
  M.card(c.$(".ph"), at - 0.25);
  const drift = c.layout === "split" ? -1.2 : 1.2;
  TF.tl.fromTo(c.$(".kb"), { scale: 1.0, xPercent: 0 },
    { scale: 1.08, xPercent: drift, duration: Math.max(1.5, c.end - at + 0.25), ease: "none", immediateRender: false }, at - 0.25);
  if (c.layout === "full") M.card(c.$(".txt"), c.at("caption") - 0.1);
  if (c.has(".hd")) M.head(c.$(".hd"), c.at("headline"));
  M.text(c.$(".ct"), c.at("caption"));
  if (c.has(".cr")) M.text(c.$(".cr"), c.at("credit"));
});
