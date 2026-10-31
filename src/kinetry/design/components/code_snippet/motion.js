/* Typing adapted from the HyperFrames registry's code-typing (Apache-2.0): each line is uncovered one character
   at a time (a stepped clip, seek-safe) with the caret on the frontier. In the terminal layout only commands are
   typed; output lines appear when the command before them finishes. */
TF.comp("code_snippet", (c) => {
  const M = c.M, term = c.layout === "terminal";
  if (c.has(".hd")) M.head(c.$(".hd"), c.start + 0.3);
  M.card(c.$(".win"), c.start + 0.15);
  const rows = TF.q(c.$(".cl"));
  const at = Math.max(c.at("code"), c.start + 0.6);
  const noteAt = c.has(".note") ? c.at("note") : c.end - 0.6;
  const typed = rows.filter((r) => !term || r.classList.contains("cmd"));
  const chars = typed.reduce((s, r) => s + Math.max(1, (r.querySelector(".ln") || r).textContent.length), 0) || 1;
  const span = Math.max(1.2, (noteAt > at + 1 ? noteAt - at : c.end - at - 0.8) * 0.85);
  const per = Math.min(0.045, Math.max(0.012, span / (chars + rows.length * 4)));
  let t = at;
  rows.forEach((r, i) => {
    const sel = c.$(".cl-" + i), ln = sel + " .ln", cur = sel + " .cur";
    if (!term || r.classList.contains("cmd")) {
      const n = Math.max(1, (r.querySelector(".ln") || r).textContent.length), d = n * per;
      TF.tl.fromTo(sel, { opacity: 0 }, { opacity: 1, duration: 0.01 }, t);
      TF.tl.fromTo(ln, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: d, ease: "steps(" + n + ")" }, t);
      // the caret's box spans the line, so moving it by its own width walks the caret along (transforms only)
      TF.tl.fromTo(sel + " .cw", { xPercent: 0 }, { xPercent: 100, duration: d, ease: "steps(" + n + ")" }, t);
      TF.tl.fromTo(cur, { opacity: 0 }, { opacity: 1, duration: 0.01 }, t);
      TF.tl.fromTo(cur, { opacity: 1 }, { opacity: 0, duration: 0.01, immediateRender: false }, t + d + 0.12);
      t += d + per * 4;
    } else {
      TF.tl.fromTo(sel, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.18, ease: "power1.out" }, t + 0.1);
      t += 0.16;
    }
  });
  if (c.has(".cl.hi")) {
    const hiAt = c.has(".note") ? noteAt - 0.1 : t + 0.3;
    TF.tl.fromTo(c.$(".cl.hi"), { "--hi": 0 }, { "--hi": 1, duration: 0.45, ease: "power2.out" }, hiAt);
    rows.forEach((r, i) => {
      if (!r.classList.contains("hi"))
        TF.tl.fromTo(c.$(".cl-" + i), { opacity: 1 }, { opacity: 0.5, duration: 0.45, immediateRender: false }, hiAt);
    });
  }
  if (c.has(".note")) M.text(c.$(".note"), noteAt);
});
