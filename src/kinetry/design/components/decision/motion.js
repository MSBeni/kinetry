/* Adapted from the HyperFrames registry's flowchart and hw-pipeline (https://github.com/heygen-com/hyperframes, Apache-2.0). */
TF.comp("decision", (c) => {
  const M = c.M, tree = c.layout === "tree";
  M.card(c.$(".q"), c.at("question") - 0.1);
  M.head(c.$(".q h2"), c.at("question"));
  const ay = c.at("yes"), an = c.at("no");
  if (tree) {
    TF.tl.fromTo(c.$(".stem"), { scaleY: 0 }, { scaleY: 1, duration: 0.3, ease: "power2.in" }, ay - 0.6);
    TF.tl.fromTo(c.$(".bar"), { scaleX: 0 }, { scaleX: 1, duration: 0.35, ease: "power2.out" }, ay - 0.3);
    TF.tl.fromTo(c.$(".d-yes"), { scaleY: 0 }, { scaleY: 1, duration: 0.25, ease: "power2.out" }, ay - 0.05);
    TF.tl.fromTo(c.$(".d-no"), { scaleY: 0 }, { scaleY: 1, duration: 0.25, ease: "power2.out" }, an - 0.3);
  }
  M.card(c.$(".p-yes"), ay + (tree ? 0.15 : 0));
  M.card(c.$(".p-no"), an);
  if (!tree) {
    TF.draw(c.$(".p-yes .arr path"), ay + 0.1, 0.5);
    TF.draw(c.$(".p-no .arr path"), an + 0.1, 0.5);
  }
  if (c.has(".note")) M.text(c.$(".note"), c.at("note"));
});
