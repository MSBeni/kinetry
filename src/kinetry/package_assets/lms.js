/* Kinetry LMS bridge: SCORM 1.2 and SCORM 2004, behind one small interface.
   Finds the LMS's API the standard way (walking up parent frames, then the opener). Without an LMS
   (the "web" package, or a file opened directly) every call is a harmless no-op. */
(function () {
  function find(win, name) {
    for (let i = 0; win && i < 10; i++) {
      try { if (win[name]) return win[name]; } catch (e) { return null; }  // a cross-origin frame: stop
      if (win.parent === win) break;
      win = win.parent;
    }
    return null;
  }
  function locate(name) {
    return find(window, name) || (window.opener ? find(window.opener, name) : null) ||
      (window.top && window.top.opener ? find(window.top.opener, name) : null);
  }
  const pad = (n, w) => String(Math.floor(n)).padStart(w, "0");

  function make(standard) {
    if (standard === "scorm12") {
      const api = locate("API");
      if (!api) return null;
      return {
        kind: "SCORM 1.2",
        start: () => { const r = api.LMSInitialize(""); return r === "true" || r === true; },
        get: (k) => api.LMSGetValue(k),
        set: (k, v) => api.LMSSetValue(k, String(v)),
        commit: () => api.LMSCommit(""),
        finish: () => api.LMSFinish(""),
        keys: { location: "cmi.core.lesson_location", suspend: "cmi.suspend_data", entry: "cmi.core.entry" },
        progress(done, watched) {  // a passed/failed score outranks "completed"
          const s = this.get("cmi.core.lesson_status");
          if (done && s !== "passed" && s !== "failed") this.set("cmi.core.lesson_status", "completed");
        },
        incomplete() { const s = this.get("cmi.core.lesson_status"); if (!s || s === "not attempted") this.set("cmi.core.lesson_status", "incomplete"); },
        score(scaled, passed) {
          this.set("cmi.core.score.min", 0); this.set("cmi.core.score.max", 100);
          this.set("cmi.core.score.raw", Math.round(scaled * 100));
          this.set("cmi.core.lesson_status", passed ? "passed" : "failed");
        },
        time(sec) { this.set("cmi.core.session_time", `${pad(sec / 3600, 4)}:${pad((sec % 3600) / 60, 2)}:${pad(sec % 60, 2)}`); },
        exit(complete) { this.set("cmi.core.exit", complete ? "" : "suspend"); },
      };
    }
    if (standard === "scorm2004") {
      const api = locate("API_1484_11");
      if (!api) return null;
      return {
        kind: "SCORM 2004",
        start: () => { const r = api.Initialize(""); return r === "true" || r === true; },
        get: (k) => api.GetValue(k),
        set: (k, v) => api.SetValue(k, String(v)),
        commit: () => api.Commit(""),
        finish: () => api.Terminate(""),
        keys: { location: "cmi.location", suspend: "cmi.suspend_data", entry: "cmi.entry" },
        progress(done, watched) {
          this.set("cmi.progress_measure", Math.min(1, watched).toFixed(2));
          this.set("cmi.completion_status", done ? "completed" : "incomplete");
        },
        incomplete() { if (this.get("cmi.completion_status") !== "completed") this.set("cmi.completion_status", "incomplete"); },
        score(scaled, passed) {
          this.set("cmi.score.min", 0); this.set("cmi.score.max", 100);
          this.set("cmi.score.raw", Math.round(scaled * 100));
          this.set("cmi.score.scaled", scaled.toFixed(2));
          this.set("cmi.success_status", passed ? "passed" : "failed");
        },
        time(sec) { this.set("cmi.session_time", `PT${Math.round(sec)}S`); },
        exit(complete) { this.set("cmi.exit", complete ? "normal" : "suspend"); },
      };
    }
    return null;
  }

  window.KinetryLMS = function (standard) {
    const lms = make(standard);
    if (!lms || !lms.start()) return null;
    return lms;
  };
})();
