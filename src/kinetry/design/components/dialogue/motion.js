TF.comp("dialogue", (c) => {
  const M = c.M, n = c.n.lines || 0, focus = c.layout === "focus";
  M.item(c.$(".who-a"), c.start + 0.25);
  M.item(c.$(".who-b"), c.start + 0.4);
  for (let i = 0; i < n; i++) {
    const at = c.at("lines." + i);
    if (focus) {
      TF.tl.fromTo(c.$(".ln-" + i), { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }, at - 0.1);
      if (i < n - 1) TF.tl.fromTo(c.$(".ln-" + i), { opacity: 1, y: 0 }, { opacity: 0, y: -20, duration: 0.35, ease: "power2.in", immediateRender: false }, Math.max(at + 0.5, c.at("lines." + (i + 1)) - 0.4));
    } else {
      M.card(c.$(".ln-" + i), at - 0.12);
      if (i >= 2) TF.tl.fromTo(c.$(".ln-" + (i - 2)), { opacity: 1 }, { opacity: 0.45, duration: 0.4, immediateRender: false }, at - 0.1);
    }
  }
  c.speak.forEach(([role, a, b]) => {
    const ring = c.$(".who-" + role + " .ring");
    TF.tl.fromTo(ring, { opacity: 0, scale: 0.9 }, { opacity: 1, scale: 1, duration: 0.25 }, a);
    const reps = Math.max(1, Math.round((b - a) / 0.6));
    TF.tl.fromTo(ring, { scale: 1 }, { scale: 1.08, duration: 0.3, yoyo: true, repeat: reps * 2 - 1, ease: "sine.inOut", immediateRender: false }, a + 0.25);
    TF.tl.fromTo(ring, { opacity: 1 }, { opacity: 0, duration: 0.25, immediateRender: false }, b);
  });
});
