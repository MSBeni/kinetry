TF.comp("numbered_steps", (c) => {
  const M = c.M, n = c.n.steps || 0;
  M.head(c.$("h2"), c.at("headline"));
  const accent = TF.v(c.root, "--accent");
  for (let i = 0; i < n; i++) {
    const at = c.at("steps." + i);
    TF.preview(c.$(".sp-" + i), c.at("headline") + 0.5 + i * 0.08, at, { opacity: 0, y: 20 }, 0.5, 0.45);
    TF.tl.to(c.$(".sp-" + i + " .sfill"), { scaleX: 1, duration: 0.7, ease: "power2.out" }, at);
    // A filled badge waits as an outline (accent number, readable while the row is dimmed) and fills when
    // its step is said; outline badges (editorial, minimal) are left as they are.
    const b = document.querySelector(c.$(".sp-" + i + " .badge"));
    if (b) {
      const cs = getComputedStyle(b);
      if (!/rgba\(.*,\s*0\)|transparent/.test(cs.backgroundColor)) {
        TF.tl.fromTo(
          b,
          { backgroundColor: "rgba(0,0,0,0)", color: accent, outline: `2px solid ${accent}`, outlineOffset: "-2px" },
          { backgroundColor: cs.backgroundColor, color: cs.color, outlineColor: "rgba(0,0,0,0)", duration: 0.35, ease: "power1.out" },
          at
        );
      }
    }
    M.emph(c.$(".sp-" + i + " .badge"), at);
  }
});
