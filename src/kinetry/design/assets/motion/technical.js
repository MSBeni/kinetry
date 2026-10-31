/* technical: clip wipes, crisp timing, hard cuts. */
TF.motion("technical", {
  head(s, at) { TF.tl.fromTo(s, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: 0.65, ease: "power3.inOut" }, at); },
  text(s, at) { TF.tl.fromTo(s, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: 0.5, ease: "power2.inOut" }, at); },
  item(s, at) { TF.tl.fromTo(s, { clipPath: "inset(100% 0 0 0)", y: 24 }, { clipPath: "inset(0% 0 0 0)", y: 0, duration: 0.5, ease: "power4.out" }, at); },
  card(s, at) { TF.tl.fromTo(s, { clipPath: "inset(100% 0 0 0)", y: 30 }, { clipPath: "inset(0% 0 0 0)", y: 0, duration: 0.6, ease: "power4.out" }, at); },
  mark(s, at) { TF.tl.fromTo(s, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: 0.35, ease: "back.out(3)" }, at); },
  emph(s, at) { TF.tl.fromTo(s, { opacity: 0.25 }, { opacity: 1, duration: 0.09, repeat: 4, yoyo: true, ease: "none" }, at); }, // odd play count: ends lit
  line(s, at, d = 0.5) { TF.tl.fromTo(s, { scaleX: 0 }, { scaleX: 1, duration: d, ease: "power2.out" }, at); },
  out(s, end) { TF.tl.set(s, { opacity: 0 }, end - 0.02); },
});
