/* Characters: they walk into frame, breathe, blink, look at each other, change expression on cue, and their
   mouths move while their own lines are voiced (c.speak holds each speaker's audio windows). Bubbles appear
   one at a time. Seek-safe: every tween is placed at an absolute time with explicit from-values, loops are
   finite, and the "random" mouth shapes and blink gaps come from a fixed hash, so any worker can render any
   frame and get the same picture. */
TF.comp("character", (c) => {
  const T = TF.tl, start = c.start, end = c.end;
  const has = (s) => TF.exists(c.$(s));
  const keys = ["a", "b"].filter((k) => has(".who-" + k));
  const duo = keys.length > 1;
  const S = (k, s) => c.$(".who-" + k + " " + s);
  const hash = (i, seed) => { const x = Math.sin(i * 12.9898 + seed * 78.233) * 43758.5453; return x - Math.floor(x); };

  // ---- the set and the cast arrive
  T.fromTo(c.$(".frame"), { opacity: 0, y: 40, scale: 0.97 }, { opacity: 1, y: 0, scale: 1, duration: 0.6, ease: "power3.out" }, start + 0.05);
  if (has(".hl")) c.M.head(c.$(".hl"), c.at("headline"));
  const castAt = c.at("cast");
  keys.forEach((k, i) => {
    T.fromTo(c.$(".who-" + k), { opacity: 0, y: 180 }, { opacity: 1, y: 0, duration: 0.8, ease: "back.out(1.3)" }, castAt + i * 0.2);
    T.fromTo(c.$(".who-" + k + " .tag"), { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.4, ease: "power3.out" }, castAt + 0.45 + i * 0.2);
  });

  // ---- expressions
  const MOODS = {
    neutral: { bl: 0, br: 0, by: 0, eye: 1, gx: 0, gy: 0, m: "flat", ch: 0, tilt: 0 },
    happy: { bl: -5, br: 5, by: -6, eye: 0.82, gx: 0, gy: 0, m: "smile", ch: 0.55, tilt: -2 },
    worried: { bl: -17, br: 17, by: -3, eye: 1.05, gx: 0, gy: 2, m: "frown", ch: 0, tilt: 3 },
    annoyed: { bl: 17, br: -17, by: 4, eye: 0.62, gx: 0, gy: 0, m: "flat", ch: 0, tilt: 0 },
    thinking: { bl: -12, br: 6, by: -5, eye: 1, gx: 5, gy: -6, m: "flat", ch: 0, tilt: -4 },
    shocked: { bl: -4, br: 4, by: -13, eye: 1.25, gx: 0, gy: 0, m: "frown", ch: 0, tilt: 0 },
    calm: { bl: 0, br: 0, by: -1, eye: 0.6, gx: 0, gy: 0, m: "smile", ch: 0.3, tilt: -2 },
  };
  const look = { a: duo ? 4 : 0, b: duo ? -4 : 0 }; // in a duo they look at each other
  const params = (k, mood) => { const p = MOODS[mood] || MOODS.neutral; return { ...p, gx: p.gx + look[k] }; };
  const parts = (p) => [
    [".brow-l", { rotation: p.bl, y: p.by }],
    [".brow-r", { rotation: p.br, y: p.by }],
    [".eye", { scaleY: p.eye }],
    [".gaze", { x: p.gx, y: p.gy }],
    [".m-flat", { opacity: p.m === "flat" ? 1 : 0 }],
    [".m-smile", { opacity: p.m === "smile" ? 1 : 0 }],
    [".m-frown", { opacity: p.m === "frown" ? 1 : 0 }],
    [".cheek", { opacity: p.ch }],
    [".head", { rotation: p.tilt }],
  ];
  const ORIGIN = { ".head": "50% 92%", ".eye": "50% 50%", ".brow-l": "50% 50%", ".brow-r": "50% 50%" };
  const state = {};
  const mood = (k, name, at) => {
    const next = params(k, name), prev = state[k];
    parts(next).forEach(([sel, to], i) => {
      const o = ORIGIN[sel] ? { transformOrigin: ORIGIN[sel] } : {};
      if (!prev) T.fromTo(S(k, sel), { ...to, ...o }, { ...to, duration: 0.01 }, start);
      else T.fromTo(S(k, sel), { ...parts(prev)[i][1], ...o }, { ...to, duration: 0.35, ease: "power2.inOut", immediateRender: false }, at);
    });
    state[k] = next;
  };
  keys.forEach((k) => mood(k, TF.q(c.$(".who-" + k))[0]?.dataset.mood || "neutral", start));

  // ---- bubbles, one at a time; a bubble's mood lands as it appears
  const events = [];
  TF.q(c.$(".bub")).forEach((el) => {
    const m = el.className.match(/\b(ln|th)-(\d+)\b/);
    if (!m) return;
    const key = (m[1] === "ln" ? "lines." : "thoughts.") + m[2];
    events.push({ sel: c.$("." + m[1] + "-" + m[2]), at: c.at(key), who: el.dataset.who, mood: el.dataset.mood, gesture: el.dataset.gesture || "" });
  });
  events.sort((x, y) => x.at - y.at);
  events.forEach((e, i) => {
    const origin = !duo ? "50% 100%" : e.who === "a" ? "20% 100%" : "80% 100%";
    T.fromTo(e.sel, { opacity: 0, scale: 0.8, y: 26, transformOrigin: origin }, { opacity: 1, scale: 1, y: 0, duration: 0.42, ease: "back.out(1.8)" }, e.at - 0.05);
    const nx = events[i + 1];
    if (nx) T.fromTo(e.sel, { opacity: 1, y: 0 }, { opacity: 0, y: -14, duration: 0.25, ease: "power2.in", immediateRender: false }, Math.max(e.at + 0.4, nx.at - 0.3));
    if (e.mood && state[e.who]) mood(e.who, e.mood, e.at - 0.1);
  });

  // ---- talking. With analysed audio (c.sc.mouth), the mouth takes the shape of each sound (kinetry.visemes);
  // otherwise it opens and closes on a fixed hash. Either way only inside the speaker's own audio windows.
  const cues = (c.sc && c.sc.mouth) || {};
  c.speak.forEach(([role, a, b], si) => {
    if (!has(".who-" + role)) return;
    const closed = S(role, ".mc");
    T.fromTo(closed, { opacity: 1 }, { opacity: 0, duration: 0.05, immediateRender: false }, a);
    T.fromTo(closed, { opacity: 0 }, { opacity: 1, duration: 0.08, immediateRender: false }, b + 0.05);
    const mine = (cues[role] || []).filter(([t]) => t >= a - 0.05 && t <= b + 0.3);
    if (mine.length) {
      mine.forEach(([t, v], i) => {
        const el = S(role, ".v-" + (v === "X" ? "A" : v));
        const until = i + 1 < mine.length ? mine[i + 1][0] : b + 0.05;
        T.fromTo(el, { opacity: 0 }, { opacity: 1, duration: 0.02, immediateRender: false }, t);
        T.fromTo(el, { opacity: 1 }, { opacity: 0, duration: 0.02, immediateRender: false }, Math.max(t + 0.03, until));
      });
    } else {
      const open = S(role, ".m-open");
      T.fromTo(open, { opacity: 0, scaleY: 0.2, transformOrigin: "50% 30%" }, { opacity: 1, scaleY: 0.5, duration: 0.06, immediateRender: false }, a);
      let t = a + 0.06, prev = 0.5, i = 0;
      while (t < b - 0.08) {
        const d = 0.08 + 0.07 * hash(i, si + 1);
        const nxt = hash(i + 7, si + 3) < 0.18 ? 0.12 : 0.3 + 0.7 * hash(i + 3, si + 5);
        T.fromTo(open, { scaleY: prev }, { scaleY: nxt, duration: d, ease: "sine.inOut", immediateRender: false }, t);
        prev = nxt; t += d; i++;
      }
      T.fromTo(open, { opacity: 1, scaleY: prev }, { opacity: 0, scaleY: 0.2, duration: 0.08, immediateRender: false }, b);
    }
    const nod = Math.max(1, Math.floor((b - a) / 0.8));
    T.fromTo(S(role, ".breath"), { y: 0 }, { y: -5, duration: 0.4, yoyo: true, repeat: nod * 2 - 1, ease: "sine.inOut", immediateRender: false }, a);
    // the other person listens: two slow nods
    keys.filter((k) => k !== role).forEach((k) => {
      if (b - a > 1.6) T.fromTo(S(k, ".head"), { y: 0 }, { y: 5, duration: 0.35, yoyo: true, repeat: 3, ease: "sine.inOut", immediateRender: false }, a + 0.6);
    });
  });

  // ---- gestures: a forearm and hand rise into frame for the line, then drop away
  const ARM = { "arm-r": "230 452", "arm-l": "70 452" };
  const REST = { y: 190, rotation: 0 };
  const POSE = {
    explain: { "arm-r": { y: 26, rotation: -14 } },
    chest: { "arm-r": { y: 34, rotation: -44 } },
    wave: { "arm-r": { y: -6, rotation: 8 } },
    shrug: { "arm-r": { y: 56, rotation: 22 }, "arm-l": { y: 56, rotation: -22 } },
  };
  keys.forEach((k) => Object.keys(ARM).forEach((arm) => {
    if (has(".who-" + k + " ." + arm)) T.fromTo(S(k, "." + arm), { ...REST, svgOrigin: ARM[arm] }, { ...REST, duration: 0.01 }, start);
  }));
  events.forEach((e) => {
    const pose = POSE[e.gesture];
    if (!pose || !has(".who-" + e.who)) return;
    const win = c.speak.find(([r, a]) => r === e.who && Math.abs(a - e.at) < 0.6);
    const a = win ? win[1] : e.at, b = win ? win[2] : e.at + 1.5;
    Object.entries(pose).forEach(([arm, to]) => {
      if (!has(".who-" + e.who + " ." + arm)) return;
      const sel = S(e.who, "." + arm);
      T.fromTo(sel, { ...REST, svgOrigin: ARM[arm] }, { ...to, duration: 0.4, ease: "back.out(1.4)", immediateRender: false }, a - 0.15);
      const amp = e.gesture === "wave" ? 14 : 5, per = e.gesture === "wave" ? 0.36 : 0.8;
      const reps = Math.floor((b - a - 0.4) / per);
      if (reps >= 1) T.fromTo(sel, { rotation: to.rotation }, { rotation: to.rotation + amp, duration: per / 2, yoyo: true, repeat: reps * 2 - 1, ease: "sine.inOut", immediateRender: false }, a + 0.3);
      T.fromTo(sel, { ...to }, { ...REST, duration: 0.45, ease: "power2.in", immediateRender: false }, b + 0.1);
    });
    if (e.gesture === "shrug") {
      T.fromTo(S(e.who, ".torso"), { y: 0 }, { y: -8, duration: 0.3, yoyo: true, repeat: 1, ease: "sine.inOut", immediateRender: false }, a);
      T.fromTo(S(e.who, ".head"), { y: 0 }, { y: -6, duration: 0.3, yoyo: true, repeat: 1, ease: "sine.inOut", immediateRender: false }, a);
    }
  });

  // ---- life: blinks, breathing, a floating figure in someone's head, a buzzing phone
  keys.forEach((k, ki) => {
    let t = start + 1.1 + ki * 0.9, n = 0;
    while (t < end - 0.4) {
      T.fromTo(S(k, ".blink"), { scaleY: 1, transformOrigin: "50% 50%" }, { scaleY: 0.08, duration: 0.07, ease: "power1.in", immediateRender: false }, t);
      T.fromTo(S(k, ".blink"), { scaleY: 0.08 }, { scaleY: 1, duration: 0.1, ease: "power1.out", immediateRender: false }, t + 0.07);
      t += 2.4 + 2.2 * hash(n++, ki + 11);
    }
    const span = end - start - 1.2, per = 3.4, reps = Math.floor(span / per);
    if (reps >= 1) T.fromTo(S(k, ".rig"), { scaleY: 1, transformOrigin: "50% 100%" }, { scaleY: 1.012, duration: per / 2, yoyo: true, repeat: reps * 2 - 1, ease: "sine.inOut", immediateRender: false }, start + 1);
    if (has(".who-" + k + ".imagined")) {
      const fr = Math.floor(span / 3);
      if (fr >= 1) T.fromTo(c.$(".who-" + k + " .float"), { y: 0, rotation: -1.5 }, { y: -18, rotation: 1.5, duration: 1.5, yoyo: true, repeat: fr * 2 - 1, ease: "sine.inOut", immediateRender: false }, start + 1);
    }
    if (has(".who-" + k + " .phone")) {
      const at = castAt + 1.0;
      T.fromTo(S(k, ".phone"), { rotation: -4, transformOrigin: "60% 80%" }, { rotation: 4, duration: 0.06, yoyo: true, repeat: 9, ease: "none", immediateRender: false }, at);
      T.fromTo(S(k, ".screen"), { opacity: 0.6 }, { opacity: 1, duration: 0.3, immediateRender: false }, at);
    }
  });

  // ---- the set keeps moving: twinkling stars, running water, drifting steam
  const span = end - start;
  TF.q(c.$(".star")).forEach((el, i) => {
    const reps = Math.floor(span / 1.6);
    if (reps >= 1) T.fromTo(el, { opacity: 0.3 }, { opacity: 1, duration: 0.8, yoyo: true, repeat: reps * 2 - 1, ease: "sine.inOut", immediateRender: false }, start + 0.2 * i);
  });
  TF.q(c.$(".drop")).forEach((el, i) => {
    const reps = Math.floor(span / 0.5) - 1;
    if (reps >= 1) T.fromTo(el, { y: 0, opacity: 0.85 }, { y: 120, opacity: 0, duration: 0.5, ease: "power1.in", repeat: reps, immediateRender: false }, start + 0.05 * i);
  });
  TF.q(c.$(".steam-c, .steam")).forEach((el, i) => {
    const reps = Math.floor(span / 4);
    if (reps >= 1) T.fromTo(el, { x: -14, y: 0 }, { x: 14, y: -10, duration: 2, yoyo: true, repeat: reps * 2 - 1, ease: "sine.inOut", immediateRender: false }, start + 0.3 * i);
  });
});
