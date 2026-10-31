TF.comp("statement", (c) => {
  const M = c.M;
  if (c.has(".eyebrow")) M.text(c.$(".eyebrow"), c.at("lead"));
  // with kinetic type on, the words land across the sentence that speaks them; otherwise a normal headline
  const w = (c.sc.W || {}).text;
  if (M.say && w) M.say(c.$("h1"), w[0], w[1]);
  else M.head(c.$("h1"), c.at("text"));
  if (c.has(".sub")) M.text(c.$(".sub"), c.at("sub"));
});
