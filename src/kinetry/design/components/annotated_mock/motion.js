TF.comp("annotated_mock", (c) => {
  const M = c.M, n = c.n.callouts || 0, targets = (c.sc.data && c.sc.data.targets) || [];
  M.card(c.$(".mock"), c.at("mock"));
  for (let i = 0; i < n; i++) {
    const at = c.at("callouts." + i), tg = c.$(".tg-" + String(targets[i] || "").replace(".", "-"));
    if (TF.exists(tg)) {
      TF.tl.fromTo(tg, { outlineColor: "rgba(229,72,77,0)" }, { outlineColor: "rgba(229,72,77,1)", duration: 0.3 }, at + 0.1);
      TF.tl.fromTo(tg, { outlineColor: "rgba(229,72,77,1)" }, { outlineColor: "rgba(255,197,66,1)", duration: 0.15, repeat: 3, yoyo: true, immediateRender: false }, at + 0.45);
    }
    M.mark(c.$(".fl-" + i), at + 0.15);
    M.item(c.$(".nt-" + i), at + 0.3);
    if (i > 0) {
      TF.tl.fromTo(c.$(".nt-" + (i - 1)), { opacity: 1 }, { opacity: 0.4, duration: 0.3, immediateRender: false }, at);
      const prev = c.$(".tg-" + String(targets[i - 1] || "").replace(".", "-"));
      if (TF.exists(prev) && prev !== tg) TF.tl.fromTo(prev, { outlineColor: "rgba(229,72,77,1)" }, { outlineColor: "rgba(229,72,77,0.35)", duration: 0.3, immediateRender: false }, at);
    }
  }
});
