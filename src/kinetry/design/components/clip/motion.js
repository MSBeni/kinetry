/* Video clip: the hoisted layer (#h<n>) fades in with its scene and out at its end; in the framed layout it is
   first laid exactly over the scene's .vslot. The clip's own playback is timed by HyperFrames. */
TF.comp("clip", (c) => {
  const T = TF.tl, M = c.M;
  const layer = "#h" + c.id.slice(1);
  if (!TF.exists(layer)) return;
  const slot = document.querySelector(c.$(".vslot"));
  const vl = document.querySelector(layer + " .vlayer");
  if (slot && vl) {
    const r = slot.getBoundingClientRect(), root = document.getElementById("root").getBoundingClientRect();
    Object.assign(vl.style, { left: r.left - root.left + "px", top: r.top - root.top + "px", width: r.width + "px", height: r.height + "px", right: "auto", bottom: "auto" });
  }
  T.fromTo(layer, { opacity: 0 }, { opacity: 1, duration: 0.35, ease: "power1.out" }, c.start);
  T.fromTo(layer + " .vlayer", { scale: 1.05 }, { scale: 1, duration: 1.2, ease: "power2.out" }, c.start);
  T.fromTo(layer, { opacity: 1 }, { opacity: 0, duration: 0.3, ease: "power1.in", immediateRender: false }, c.end - 0.3);
  // full frame: the chrome at the bottom (scene counter, progress) sits on the clip's dark fade, so it turns white
  if (TF.exists(layer + ".l-full")) {
    TF.q(".chrome .bottom, .chrome .bottom *").forEach((el) => {
      const was = getComputedStyle(el).color;
      T.fromTo(el, { color: was }, { color: "#ffffff", duration: 0.3, immediateRender: false }, c.start);
      T.fromTo(el, { color: "#ffffff" }, { color: was, duration: 0.3, immediateRender: false }, c.end - 0.3);
    });
  }
  const head = TF.exists(layer + " .hl") ? layer + " .hl" : c.$(".hl");
  const cap = TF.exists(layer + " .ccap") ? layer + " .ccap" : c.$(".ccap");
  const eb = layer + " .eyebrow";
  if (TF.exists(eb)) M.text(eb, c.start + 0.2);
  if (TF.exists(head)) M.head(head, c.at("headline"));
  if (TF.exists(cap)) M.text(cap, c.at("caption"));
});
