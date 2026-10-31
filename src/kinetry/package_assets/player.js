/* Kinetry lesson player: chapters, a live transcript, progress that only counts what was watched, and an
   optional knowledge check. Reports to the LMS through lms.js; works the same with no LMS at all. */
(function () {
  const L = window.KINETRY_LESSON, T = L.ui;
  const $ = (id) => document.getElementById(id);
  const v = $("video");
  const hasQuiz = L.quiz && L.quiz.length > 0;
  const lms = window.KinetryLMS ? window.KinetryLMS(L.standard) : null;
  const t0 = Date.now();

  // ---------------------------------------------------------------- state (resumed from the LMS)
  let state = { w: [], a: [], s: 0, p: 0 };  // watched ranges, answers, submitted, passed
  if (lms) {
    try {
      const raw = lms.get(lms.keys.suspend);
      if (raw) state = Object.assign(state, JSON.parse(raw));
    } catch (e) { /* first visit or unreadable: start fresh */ }
    lms.incomplete();
  }
  const save = () => { if (lms) { lms.set(lms.keys.suspend, JSON.stringify(state)); lms.set(lms.keys.location, Math.floor(v.currentTime || 0)); } };

  // ---------------------------------------------------------------- watched ranges
  function merge(r) {
    r.sort((x, y) => x[0] - y[0]);
    const out = [];
    for (const [a, b] of r) {
      if (out.length && a <= out[out.length - 1][1] + 0.5) out[out.length - 1][1] = Math.max(out[out.length - 1][1], b);
      else out.push([a, b]);
    }
    return out;
  }
  const dur = () => (isFinite(v.duration) && v.duration > 0 ? v.duration : L.duration);
  const share = () => Math.min(1, state.w.reduce((n, [a, b]) => n + (b - a), 0) / dur());
  const watchedEnough = () => share() >= L.watched;

  let last = null, lastSave = 0;
  v.addEventListener("timeupdate", () => {
    const t = v.currentTime;
    if (last !== null && !v.seeking && t > last && t - last < 1 + 1.5 * Math.max(1, v.playbackRate)) state.w = merge(state.w.concat([[last, t]]).map((x) => x.slice()));
    last = t;
    paint();
    if (Date.now() - lastSave > 15000) { lastSave = Date.now(); save(); if (lms) lms.commit(); }
  });
  v.addEventListener("seeking", () => { last = null; });
  v.addEventListener("seeked", () => { last = v.currentTime; });
  v.addEventListener("ended", () => { paint(); save(); if (lms) lms.commit(); });
  v.addEventListener("loadedmetadata", () => {
    if (lms) {
      const at = parseFloat(lms.get(lms.keys.location));
      if (at > 2 && at < dur() - 2) v.currentTime = at;
    }
  });

  // ---------------------------------------------------------------- chapters and transcript
  $("ch-h").textContent = T.chapters;
  $("tr-h").textContent = T.transcript;
  $("download").textContent = T.download;
  const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const chapters = L.scenes.map((sc) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = `<span class="t"></span><span class="l"></span>`;
    b.querySelector(".t").textContent = clock(sc.start);
    b.querySelector(".l").textContent = sc.label;
    b.addEventListener("click", () => { v.currentTime = sc.start + 0.05; v.play().catch(() => {}); });
    li.appendChild(b);
    $("chapters").appendChild(li);
    return li;
  });
  const tr = $("transcript");
  const cues = L.cues.map((c, i) => {
    if (i === 0 || L.cues[i - 1].scene !== c.scene) {
      const h = document.createElement("h3");
      h.textContent = L.scenes[c.scene].label;
      tr.appendChild(h);
    }
    const s = document.createElement("span");
    s.className = "cue";
    s.tabIndex = 0;
    s.textContent = c.text + " ";
    const go = () => { v.currentTime = c.start + 0.02; v.play().catch(() => {}); };
    s.addEventListener("click", go);
    s.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    tr.appendChild(s);
    return s;
  });

  let onCue = -1, onCh = -1;
  function paint() {
    const t = v.currentTime;
    const ci = L.cues.findIndex((c) => t >= c.start && t < c.end + 0.15);
    if (ci !== onCue) {
      if (onCue >= 0) cues[onCue].classList.remove("on");
      if (ci >= 0) {
        cues[ci].classList.add("on");
        const box = tr.getBoundingClientRect(), r = cues[ci].getBoundingClientRect();
        if (r.top < box.top || r.bottom > box.bottom) tr.scrollTop += r.top - box.top - box.height / 3;
      }
      onCue = ci;
    }
    let ch = -1;
    L.scenes.forEach((sc, i) => { if (t >= sc.start) ch = i; });
    if (ch !== onCh) {
      chapters.forEach((li, i) => li.classList.toggle("on", i === ch));
      onCh = ch;
    }
    $("meter").style.width = `${Math.round(share() * 100)}%`;
    $("status").textContent = `${T.progress}: ${Math.round(share() * 100)}%`;
    if (watchedEnough()) unlock();
  }

  // ---------------------------------------------------------------- completion and the knowledge check
  let completed = false;
  function complete() {
    if (completed) return;
    completed = true;
    if (lms) { lms.progress(true, share()); save(); lms.commit(); }
  }

  const quiz = $("quiz");
  function unlock() {
    if (!hasQuiz) {
      if (!completed) { complete(); $("status").textContent = T.done; }
      return;
    }
    if (lms && L.standard === "scorm2004") lms.progress(true, share());
    $("q-lock").hidden = true;
    $("q-form").hidden = false;
  }
  if (hasQuiz) {
    quiz.hidden = false;
    $("q-h").textContent = T.check;
    $("q-lock").textContent = T.locked;
    const form = $("q-form");
    form.hidden = true;
    L.quiz.forEach((q, qi) => {
      const fs = document.createElement("fieldset");
      fs.innerHTML = `<legend></legend>`;
      fs.querySelector("legend").textContent = `${qi + 1}. ${q.question}`;
      q.options.forEach((o, oi) => {
        const lab = document.createElement("label");
        lab.innerHTML = `<input type="radio" name="q${qi}" value="${oi}"><span></span>`;
        lab.querySelector("span").textContent = o;
        if (state.a[qi] === oi) lab.querySelector("input").checked = true;
        fs.appendChild(lab);
      });
      const fb = document.createElement("p");
      fb.className = "fb";
      fb.id = `fb${qi}`;
      fs.appendChild(fb);
      form.appendChild(fs);
    });
    const btn = document.createElement("button");
    btn.type = "submit";
    btn.className = "go";
    btn.textContent = T.submit;
    form.appendChild(btn);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (btn.dataset.retry) { reset(); return; }
      const picks = L.quiz.map((q, qi) => { const c = form.querySelector(`input[name=q${qi}]:checked`); return c ? +c.value : -1; });
      if (picks.includes(-1)) { $("q-result").textContent = T.pick; return; }
      let right = 0;
      L.quiz.forEach((q, qi) => {
        const ok = picks[qi] === q.answer;
        right += ok ? 1 : 0;
        const fb = $(`fb${qi}`);
        fb.textContent = `${ok ? T.right : T.wrong} ${q.why}`;
        fb.className = "fb " + (ok ? "ok" : "no");
        form.querySelectorAll(`input[name=q${qi}]`).forEach((r) => (r.disabled = true));
      });
      const scaled = right / L.quiz.length, passed = scaled >= L.mastery;
      state.a = picks; state.s = 1; state.p = passed ? 1 : 0;
      $("q-result").textContent = `${T.score.replace("{n}", right).replace("{m}", L.quiz.length)} ${passed ? T.passed : T.failed}`;
      if (lms) { lms.score(scaled, passed); lms.progress(true, share()); save(); lms.commit(); }
      completed = true;
      if (!passed) { btn.textContent = T.retry; btn.dataset.retry = "1"; } else { btn.hidden = true; }
    });
    function reset() {
      form.querySelectorAll("input").forEach((r) => { r.disabled = false; r.checked = false; });
      form.querySelectorAll(".fb").forEach((p) => { p.textContent = ""; p.className = "fb"; });
      $("q-result").textContent = "";
      btn.textContent = T.submit;
      delete btn.dataset.retry;
    }
  }

  paint();
  if (watchedEnough()) unlock();

  // ---------------------------------------------------------------- leaving
  let gone = false;
  function leave() {
    if (gone || !lms) return;
    gone = true;
    save();
    lms.time((Date.now() - t0) / 1000);
    lms.exit(completed && (!hasQuiz || state.p === 1));
    lms.commit();
    lms.finish();
  }
  window.addEventListener("pagehide", leave);
  window.addEventListener("beforeunload", leave);
  window.KinetryPlayer = { leave, share, state: () => state };  // for tests and hosting pages
})();
