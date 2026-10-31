TF.comp("big_stat", (c) => {
  const M = c.M, at = c.at("value");
  const el = document.querySelector(c.$(".val"));
  let frac = 1;
  if (el) {
    // count up only a plain number ("72%", "$40", "3.5x"); "1,200" or "24/7" stay as written
    const m = el.textContent.match(/^([^\d,]*?)(\d+(?:\.\d+)?)([^\d,/:]*)$/);
    if (m) {
      const num = parseFloat(m[2]), dec = (m[2].split(".")[1] || "").length;
      const span = document.createElement("span");
      span.className = "cnum";
      span.textContent = m[2];
      el.textContent = "";
      el.append(m[1], span, m[3]);  // text nodes: nothing is parsed as markup
      TF.count(c.$(".val .cnum"), num, at, 1.4, dec);
      if (/%/.test(m[3]) && num <= 100) frac = num / 100;
    }
  }
  M.mark(c.$(".val"), at - 0.1);
  if (c.has(".ring")) {
    TF.tl.fromTo(c.$(".ring"), { opacity: 0 }, { opacity: 1, duration: 0.4 }, at - 0.2);
    TF.tl.fromTo(c.$(".ring .rf"), { strokeDashoffset: 100 }, { strokeDashoffset: 100 - frac * 100, duration: 1.6, ease: "power2.inOut" }, at);
  }
  M.head(c.$("h2"), c.at("label"));
  if (c.has(".sub")) M.text(c.$(".sub"), c.at("sub"));
});
