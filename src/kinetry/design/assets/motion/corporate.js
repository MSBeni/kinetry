/* corporate: confident slides, even rhythm, no surprises. */
TF.motion("corporate", {
  head(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.8, ease: "power3.out" }, at); },
  text(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.7, ease: "power3.out" }, at); },
  item(s, at) { TF.tl.fromTo(s, { opacity: 0, x: -28 }, { opacity: 1, x: 0, duration: 0.6, ease: "power3.out" }, at); },
  card(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.7, ease: "power3.out" }, at); },
  mark(s, at) { TF.tl.fromTo(s, { opacity: 0, scale: 0.7 }, { opacity: 1, scale: 1, duration: 0.5, ease: "power2.out" }, at); },
  emph(s, at) { TF.tl.fromTo(s, { scale: 1 }, { scale: 1.04, duration: 0.22, yoyo: true, repeat: 1, ease: "power2.inOut" }, at); },
  line(s, at, d = 0.9) { TF.tl.fromTo(s, { scaleX: 0 }, { scaleX: 1, duration: d, ease: "power3.inOut" }, at); },
  out(s, end) { TF.tl.to(s, { opacity: 0, y: -10, duration: 0.45, ease: "power2.in" }, end - 0.5); },
});
