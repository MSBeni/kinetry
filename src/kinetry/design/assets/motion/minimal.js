/* minimal: quiet fades, generous timing. Also the fallback every other pack can lean on. */
TF.motion("minimal", {
  head(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 1.1, ease: "sine.out" }, at); },
  text(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.9, ease: "sine.out" }, at); },
  item(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.8, ease: "sine.out" }, at); },
  card(s, at) { TF.tl.fromTo(s, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.9, ease: "sine.out" }, at); },
  mark(s, at) { TF.tl.fromTo(s, { opacity: 0, scale: 0.92 }, { opacity: 1, scale: 1, duration: 0.8, ease: "sine.out" }, at); },
  emph(s, at) { TF.tl.fromTo(s, { scale: 1 }, { scale: 1.03, duration: 0.35, yoyo: true, repeat: 1, ease: "sine.inOut" }, at); },
  line(s, at, d = 1.2) { TF.tl.fromTo(s, { scaleX: 0 }, { scaleX: 1, duration: d, ease: "sine.inOut" }, at); },
  out(s, end) { TF.tl.to(s, { opacity: 0, duration: 0.6, ease: "sine.in" }, end - 0.6); },
});
