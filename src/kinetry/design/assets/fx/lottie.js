/* A caller's Lottie, played on its scene's clock: a tween on the same paused GSAP timeline as everything else
   moves the animation's frame from the moment the scene reveals it (held on its last frame after it ends, or
   looped while the scene lasts when the illustration layer is rich). Every frame follows from the timeline
   position alone, so frames render the same in any order. HyperFrames' own Lottie discovery is kept away from
   these players (it would play them on the composition clock from 0). */
TF.lottie = function (sel, at, end, loop) {
  const el = document.querySelector(sel);
  const L = window.__tfLottie;
  if (!el || !L) return;
  const src = document.getElementById(el.dataset.lottie);
  if (!src) return;
  const data = JSON.parse(src.textContent);
  const anim = L.loadAnimation({ container: el, renderer: "svg", loop: false, autoplay: false, animationData: data,
    rendererSettings: { preserveAspectRatio: "xMidYMid meet" } });
  const fr = Number(data.fr) || 30, n = Math.max(1, (Number(data.op) || 1) - (Number(data.ip) || 0));
  const len = n / fr, p = { f: 0 };
  anim.goToAndStop(0, true);
  const reps = loop ? Math.max(0, Math.floor(Math.max(0, end - at) / len) - 1) : 0;
  TF.tl.fromTo(p, { f: 0 }, {
    f: n - 1, duration: len, ease: "none", repeat: reps,
    onUpdate: () => anim.goToAndStop(p.f, true),
  }, at);
};
