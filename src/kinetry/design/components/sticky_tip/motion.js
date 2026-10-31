TF.comp("sticky_tip", (c) => {
  const M = c.M, at = c.at("tip");
  if (c.layout === "note") TF.tl.fromTo(c.$(".tipbox"), { opacity: 0, scale: 1.45, rotation: -10 }, { opacity: 1, scale: 1, rotation: 0, duration: 0.55, ease: "back.out(1.6)" }, at - 0.3);
  else M.card(c.$(".tipbox"), at - 0.2);
  M.text(c.$(".tt"), at + 0.3);
  if (c.has(".tic")) TF.draw(c.$(".tic svg"), c.at("icon") + 0.2, 0.9);
  if (c.has(".tn")) M.text(c.$(".tn"), c.at("note"));
});
