TF.comp("pull_quote", (c) => {
  const M = c.M;
  M.mark(c.$(".marks"), c.start + 0.3);
  if (c.has(".lead")) M.text(c.$(".lead"), c.at("lead"));
  M.head(c.$("blockquote"), c.at("quote"));
  // the marker sweeps once the words are in: right away when the phrase has its own beat,
  // after the quote's word reveal when both arrive together
  const hlAt = Math.max(c.at("highlight") + 0.15, c.at("quote") + 1.1);
  if (c.has(".hl")) TF.tl.fromTo(c.$(".hl"), { backgroundSize: "0% 32%" }, { backgroundSize: "100% 32%", duration: 0.7, ease: "power2.inOut" }, hlAt);
  if (c.has(".attr")) M.text(c.$(".attr"), c.at("attribution"));
});
