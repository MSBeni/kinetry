/* Message arrival adapted from the HyperFrames registry's chat-message (Apache-2.0): each message scales up
   from its sender's corner; on a phone the other person's replies are preceded by typing dots in their place. */
TF.comp("chat_thread", (c) => {
  const M = c.M, n = c.n.messages || 0, rtl = TF.exists("#root.rtl");
  if (c.has(".hd")) M.head(c.$(".hd"), c.start + 0.3);
  M.card(c.$(".app"), c.start + 0.15);
  for (let i = 0; i < n; i++) {
    const at = c.at("messages." + i), sel = c.$(".m-" + i);
    const end = TF.exists(sel + ".me") !== rtl;  // the bubble's corner nearest its sender
    if (c.has(".m-" + i + " .typing")) {
      const ty = sel + " .typing", a = Math.max(c.start + 0.4, at - 0.8);
      TF.tl.fromTo(ty, { opacity: 0, scale: 0.7, transformOrigin: "0% 100%" }, { opacity: 1, scale: 1, duration: 0.2 }, a);
      TF.tl.fromTo(ty + " i", { y: 0 }, { y: -6, duration: 0.16, yoyo: true, repeat: 3, stagger: 0.08, ease: "sine.inOut" }, a + 0.05);
      TF.tl.fromTo(ty, { opacity: 1 }, { opacity: 0, duration: 0.1, immediateRender: false }, at - 0.08);
    }
    TF.tl.fromTo(sel + " .mb, " + sel + " .av", { opacity: 0, scale: 0.8, transformOrigin: end ? "100% 100%" : "0% 100%" },
      { opacity: 1, scale: 1, duration: 0.32, ease: "back.out(1.6)" }, at - 0.08);
  }
  if (c.has(".note")) M.text(c.$(".note"), c.at("note"));
});
