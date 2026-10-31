"""Turn a finished video into a lesson an LMS can import.

    kinetry package RUN_DIR --out lesson.zip                  # SCORM 1.2, with a knowledge check
    kinetry package RUN_DIR --standard scorm2004 --quiz off
    kinetry run lesson.md --brand brands/acme --out lesson.mp4 --package scorm12

A package holds the video, captions (WebVTT, with speaker names in dialogues), chapters, a transcript, an
optional knowledge check written from the same source, and a small player page that reports progress to
the LMS: watched (90% of the video, skipping doesn't count), then the quiz score. `web` is the same
player as a plain zip for any website, with no LMS reporting.

Quiz questions must quote the source they're drawn from: a question whose quote can't be found word for
word in the source (or, with no source, in the narration) is dropped, never shown.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from html import escape
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, Field

from .transcript import narration_text

STANDARDS = ("scorm12", "scorm2004", "web")
WATCHED = 0.9  # share of the video that must be seen (skipped parts don't count)
ASSETS = resources.files(__package__) / "package_assets"


# ------------------------------------------------------------------ knowledge check
class QuizQuestion(BaseModel):
    question: str = Field(..., max_length=220, description="One clear question about a key idea of the source")
    options: list[str] = Field(..., min_length=3, max_length=4, description="3-4 short answers, exactly one correct")
    answer: int = Field(..., ge=0, le=3, description="Index of the correct option")
    why: str = Field(..., max_length=240, description="One sentence: why the correct answer is right")
    quote: str = Field(..., max_length=400, description="An exact phrase copied from the source that supports it")


class Quiz(BaseModel):
    questions: list[QuizQuestion] = Field(..., min_length=1, max_length=6)


QUIZ_SYSTEM = """You write a short knowledge check for a training video. The learner has just watched it.

Rules:
- Every question must be answerable from the SOURCE alone. Test the ideas that matter, not trivia, names or numbers
  nobody needs to remember.
- 3 or 4 options per question, exactly one correct. Wrong options are plausible mistakes from the same topic,
  never jokes, never "all of the above" or "none of the above".
- answer is the index of the correct option.
- why: one sentence a learner can learn from.
- quote: copy, word for word, a phrase of 6-25 words from the SOURCE that supports the correct answer. Do not
  paraphrase it; it is checked against the source and the question is dropped if it doesn't match.
- Keep questions under 140 characters and options under 90.
- Write the questions, options and explanation in the language given; the quote stays in the source's words.
"""


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[^\w\s']+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def grounded(quiz: Quiz, text: str) -> tuple[Quiz | None, list[str]]:
    """Keep only questions whose quote is really in the text and whose answer index is valid; rotate options
    so the right answer isn't always in the same place. Returns (quiz or None, notes)."""
    hay = _norm(text)
    kept, notes = [], []
    for q in quiz.questions:
        quote = _norm(q.quote)
        opts = [o.strip() for o in q.options if o.strip()]
        if len(quote.split()) < 4 or quote not in hay:
            notes.append(f"dropped (quote not found in the source): {q.question[:80]}")
            continue
        if not 0 <= q.answer < len(opts) or len({_norm(o) for o in opts}) != len(opts):
            notes.append(f"dropped (answer or options invalid): {q.question[:80]}")
            continue
        shift = int(hashlib.sha1(q.question.encode()).hexdigest(), 16) % len(opts)
        right = opts[q.answer]
        opts = opts[shift:] + opts[:shift]
        kept.append(q.model_copy(update={"options": opts, "answer": opts.index(right)}))
    return (Quiz(questions=kept) if kept else None), notes


def make_quiz(
    text: str, *, n: int = 3, lang: str = "en", settings=None, llm=None, rec=None
) -> tuple[Quiz | None, list[str]]:
    """Ask a model for n questions grounded in `text`, then keep the ones that check out."""
    from .agents import Recorder, get_llm
    from .config import Settings
    from .llm import invoke_structured

    s = settings or Settings()
    words = text.split()
    src = " ".join(words[:12000])

    def _run() -> Quiz:
        model = get_llm(s, llm, 0.2)
        user = f"Language: {lang}\nNumber of questions: {n}\n\nSOURCE:\n{src}"
        return invoke_structured(
            model, Quiz, [{"role": "system", "content": QUIZ_SYSTEM}, {"role": "user", "content": user}]
        )

    rec = rec or Recorder(Path(tempfile.mkdtemp(prefix="kinetry-quiz-")), s)
    quiz = rec.call("quiz", Quiz, _run)
    quiz = Quiz(questions=quiz.questions[:n]) if quiz else quiz
    return grounded(quiz, text)


# ------------------------------------------------------------------ captions, chapters, transcript
def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def _clock(t: float) -> str:
    m, s = divmod(int(round(t)), 60)
    return f"{m}:{s:02d}"


def captions_vtt(timing: dict) -> str:
    names = {}
    for sc in timing["scenes"]:
        for bi, b in enumerate(sc["beats"]):
            if b.get("speaker"):
                names[(sc["index"], bi)] = b["speaker"]
    out = ["WEBVTT", ""]
    for c in timing["cues"]:
        who = names.get((c["scene"], c["beat"]))
        text = c["text"].replace("-->", "->")
        out += [f"{_ts(c['start'])} --> {_ts(c['end'])}", f"<v {who}>{text}" if who else text, ""]
    return "\n".join(out)


def chapters_vtt(timing: dict) -> str:
    out = ["WEBVTT", ""]
    for sc in timing["scenes"]:
        out += [f"{_ts(sc['start'])} --> {_ts(sc['end'])}", sc["label"].replace("-->", "->"), ""]
    return "\n".join(out)


def transcript_text(timing: dict) -> str:
    lines = [timing.get("title") or "Transcript", ""]
    for sc in timing["scenes"]:
        lines.append(f"[{_clock(sc['start'])}] {sc['label']}")
        for b in sc["beats"]:
            lines.append(f"{b['speaker']}: {b['say']}" if b.get("speaker") else b["say"])
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ player strings
UI = {
    "en": {
        "chapters": "Chapters",
        "captions": "Captions",
        "transcript": "Transcript",
        "check": "Check your understanding",
        "locked": "Watch the video to unlock the questions.",
        "submit": "Check my answers",
        "retry": "Try again",
        "right": "Correct.",
        "wrong": "Not quite.",
        "score": "You got {n} of {m} right.",
        "passed": "Well done: you passed.",
        "failed": "Review the video and try again.",
        "done": "You've finished this lesson.",
        "progress": "Watched",
        "download": "Download the transcript",
        "pick": "Choose an answer for every question.",
    },
    "es": {
        "chapters": "Capítulos",
        "captions": "Subtítulos",
        "transcript": "Transcripción",
        "check": "Comprueba lo que aprendiste",
        "locked": "Mira el video para desbloquear las preguntas.",
        "submit": "Comprobar respuestas",
        "retry": "Intentar de nuevo",
        "right": "Correcto.",
        "wrong": "No exactamente.",
        "score": "Acertaste {n} de {m}.",
        "passed": "¡Bien hecho! Aprobaste.",
        "failed": "Repasa el video e inténtalo de nuevo.",
        "done": "Terminaste esta lección.",
        "progress": "Visto",
        "download": "Descargar la transcripción",
        "pick": "Elige una respuesta para cada pregunta.",
    },
    "fr": {
        "chapters": "Chapitres",
        "captions": "Sous-titres",
        "transcript": "Transcription",
        "check": "Vérifiez vos connaissances",
        "locked": "Regardez la vidéo pour débloquer les questions.",
        "submit": "Vérifier mes réponses",
        "retry": "Réessayer",
        "right": "Exact.",
        "wrong": "Pas tout à fait.",
        "score": "Vous avez {n} bonnes réponses sur {m}.",
        "passed": "Bravo : c'est réussi.",
        "failed": "Revoyez la vidéo et réessayez.",
        "done": "Vous avez terminé cette leçon.",
        "progress": "Vu",
        "download": "Télécharger la transcription",
        "pick": "Choisissez une réponse pour chaque question.",
    },
    "de": {
        "chapters": "Kapitel",
        "captions": "Untertitel",
        "transcript": "Transkript",
        "check": "Prüfen Sie Ihr Wissen",
        "locked": "Sehen Sie sich das Video an, um die Fragen freizuschalten.",
        "submit": "Antworten prüfen",
        "retry": "Noch einmal",
        "right": "Richtig.",
        "wrong": "Nicht ganz.",
        "score": "{n} von {m} richtig.",
        "passed": "Gut gemacht: bestanden.",
        "failed": "Sehen Sie sich das Video noch einmal an und versuchen Sie es erneut.",
        "done": "Sie haben diese Lektion abgeschlossen.",
        "progress": "Gesehen",
        "download": "Transkript herunterladen",
        "pick": "Wählen Sie für jede Frage eine Antwort.",
    },
    "pt": {
        "chapters": "Capítulos",
        "captions": "Legendas",
        "transcript": "Transcrição",
        "check": "Verifique o que aprendeu",
        "locked": "Assista ao vídeo para liberar as perguntas.",
        "submit": "Verificar respostas",
        "retry": "Tentar de novo",
        "right": "Correto.",
        "wrong": "Não exatamente.",
        "score": "Você acertou {n} de {m}.",
        "passed": "Muito bem: aprovado.",
        "failed": "Reveja o vídeo e tente de novo.",
        "done": "Você concluiu esta lição.",
        "progress": "Assistido",
        "download": "Baixar a transcrição",
        "pick": "Escolha uma resposta para cada pergunta.",
    },
    "zh": {
        "chapters": "章节",
        "captions": "字幕",
        "transcript": "文字稿",
        "check": "检验一下",
        "locked": "看完视频即可解锁题目。",
        "submit": "检查答案",
        "retry": "再试一次",
        "right": "正确。",
        "wrong": "不太对。",
        "score": "答对 {n} / {m} 题。",
        "passed": "做得好，通过了。",
        "failed": "再看一遍视频，然后重试。",
        "done": "本课已完成。",
        "progress": "已观看",
        "download": "下载文字稿",
        "pick": "请为每道题选择一个答案。",
    },
    "ar": {
        "chapters": "الفصول",
        "captions": "الترجمة النصية",
        "transcript": "النص",
        "check": "اختبر فهمك",
        "locked": "شاهد الفيديو لفتح الأسئلة.",
        "submit": "تحقق من إجاباتي",
        "retry": "حاول مرة أخرى",
        "right": "صحيح.",
        "wrong": "ليس تمامًا.",
        "score": "أجبت إجابة صحيحة عن {n} من {m}.",
        "passed": "أحسنت: لقد نجحت.",
        "failed": "راجع الفيديو وحاول مرة أخرى.",
        "done": "لقد أنهيت هذا الدرس.",
        "progress": "تمت المشاهدة",
        "download": "تنزيل النص",
        "pick": "اختر إجابة لكل سؤال.",
    },
}
RTL = {"ar", "fa", "he", "ur"}


def ui_strings(lang: str) -> dict:
    code = (lang or "en").split("-")[0].lower()
    return {**UI["en"], **UI.get(code, {})}


# ------------------------------------------------------------------ manifests
def _manifest_scorm12(ident: str, title: str, files: list[str], mastery: int | None) -> str:
    t = escape(title)
    ms = f"<adlcp:masteryscore>{mastery}</adlcp:masteryscore>" if mastery is not None else ""
    fl = "".join(f'<file href="{escape(f)}"/>' for f in files)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{ident}" version="1.0"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
  <metadata><schema>ADL SCORM</schema><schemaversion>1.2</schemaversion></metadata>
  <organizations default="org-1">
    <organization identifier="org-1"><title>{t}</title>
      <item identifier="item-1" identifierref="res-1" isvisible="true"><title>{t}</title>{ms}</item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-1" type="webcontent" adlcp:scormtype="sco" href="index.html">{fl}</resource>
  </resources>
</manifest>
"""


def _manifest_scorm2004(ident: str, title: str, files: list[str], mastery: int | None) -> str:
    t = escape(title)
    fl = "".join(f'<file href="{escape(f)}"/>' for f in files)
    seq = ""
    if mastery is not None:
        seq = (
            "<imsss:sequencing><imsss:objectives>"
            '<imsss:primaryObjective objectiveID="primary" satisfiedByMeasure="true">'
            f"<imsss:minNormalizedMeasure>{mastery / 100:.2f}</imsss:minNormalizedMeasure>"
            "</imsss:primaryObjective></imsss:objectives></imsss:sequencing>"
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{ident}" version="1.0"
  xmlns="http://www.imsglobal.org/xsd/imscp_v1p1"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_v1p3"
  xmlns:adlseq="http://www.adlnet.org/xsd/adlseq_v1p3"
  xmlns:adlnav="http://www.adlnet.org/xsd/adlnav_v1p3"
  xmlns:imsss="http://www.imsglobal.org/xsd/imsss"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsglobal.org/xsd/imscp_v1p1 imscp_v1p1.xsd http://www.adlnet.org/xsd/adlcp_v1p3 adlcp_v1p3.xsd http://www.adlnet.org/xsd/adlseq_v1p3 adlseq_v1p3.xsd http://www.adlnet.org/xsd/adlnav_v1p3 adlnav_v1p3.xsd http://www.imsglobal.org/xsd/imsss imsss_v1p0.xsd">
  <metadata><schema>ADL SCORM</schema><schemaversion>2004 4th Edition</schemaversion></metadata>
  <organizations default="org-1">
    <organization identifier="org-1"><title>{t}</title>
      <item identifier="item-1" identifierref="res-1" isvisible="true"><title>{t}</title>{seq}</item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-1" type="webcontent" adlcp:scormType="sco" href="index.html">{fl}</resource>
  </resources>
</manifest>
"""


# ------------------------------------------------------------------ the package
@dataclass
class Package:
    path: Path
    standard: str
    questions: int
    notes: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def poster_time(timing: dict) -> float:
    """A frame for the still before play: a few seconds in, and, when captions are drawn into the video,
    in a pause between lines so the poster isn't half a sentence (and before the next scene moves in)."""
    at = min(4.0, max(0.5, timing["duration"] / 4))
    if not timing.get("burned_captions"):
        return at
    cues = sorted(timing.get("cues", []), key=lambda c: c["start"])
    gaps = [(0.0, cues[0]["start"])] if cues else []
    gaps += [(a["end"], b["start"]) for a, b in zip(cues, cues[1:], strict=False)]
    for a, b in gaps:
        if b - a >= 0.4 and b > 1.0:
            return round(min(a + 0.3, b - 0.1), 2)  # just after a line ends: the scene is still settled
    return at


def _poster(video: Path, at: float, dest: Path) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{at:.2f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(dest),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return dest.exists()
    except (OSError, subprocess.SubprocessError):
        return False


def load_run(run_dir: str | Path) -> tuple[dict, dict]:
    """(report, timing) of a finished run."""
    rd = Path(run_dir)
    rep, tim = rd / "report.json", rd / "timing.json"
    if not tim.exists():
        raise FileNotFoundError(f"{rd} has no timing.json: package a run made with Kinetry 0.3 or later")
    report = json.loads(rep.read_text(encoding="utf-8")) if rep.exists() else {}
    return report, json.loads(tim.read_text(encoding="utf-8"))


def build_package(
    run_dir: str | Path,
    out: str | Path,
    *,
    standard: str = "scorm12",
    quiz: Quiz | None | bool = True,
    questions: int = 3,
    mastery: int = 80,
    title: str | None = None,
    video: str | Path | None = None,
    settings=None,
    llm=None,
    replay_dir: str | Path | None = None,
) -> Package:
    """Package a finished run. `quiz`: True writes one with a model, False/None leaves it out, a Quiz is used as
    given (still checked against the source). `mastery`: the passing score, in percent."""
    from .agents import Recorder
    from .config import Settings

    if standard not in STANDARDS:
        raise ValueError(f"standard must be one of {', '.join(STANDARDS)}")
    rd = Path(run_dir)
    report, timing = load_run(rd)
    vid = Path(video) if video else Path(report.get("video") or "")
    if not vid.is_file():
        raise FileNotFoundError(f"video not found: {vid} (pass video=...)")
    title = title or timing.get("title") or "Lesson"
    lang = timing.get("lang") or "en"
    src_file = rd / "source.md"
    ground = src_file.read_text(encoding="utf-8") if src_file.exists() else narration_text(timing)

    notes: list[str] = []
    q: Quiz | None = None
    if isinstance(quiz, Quiz):
        q, notes = grounded(quiz, ground)
    elif quiz:
        s = settings or Settings()
        rec = Recorder(rd, s, Path(replay_dir) if replay_dir else None)
        try:
            q, notes = make_quiz(ground, n=questions, lang=lang, settings=s, llm=llm, rec=rec)
        except Exception as e:  # noqa: BLE001  (no model reachable): package without the quiz, and say so
            notes.append(f"no knowledge check: {type(e).__name__}: {e}"[:300])
    if q is not None:
        (rd / "quiz.json").write_text(q.model_dump_json(indent=2), encoding="utf-8")

    brand = report.get("brand") or {}
    with tempfile.TemporaryDirectory(prefix="kinetry-pkg-") as tmp:
        root = Path(tmp)
        (root / "media").mkdir()
        shutil.copy(vid, root / "media" / "video.mp4")
        (root / "media" / "captions.vtt").write_text(captions_vtt(timing), encoding="utf-8")
        (root / "media" / "chapters.vtt").write_text(chapters_vtt(timing), encoding="utf-8")
        (root / "media" / "transcript.txt").write_text(transcript_text(timing), encoding="utf-8")
        has_poster = _poster(vid, poster_time(timing), root / "media" / "poster.jpg")
        for name in ("player.css", "player.js", "lms.js"):
            (root / name).write_text((ASSETS / name).read_text(encoding="utf-8"), encoding="utf-8")
        lesson = {
            "title": title,
            "lang": lang,
            "standard": standard,
            "duration": timing["duration"],
            "watched": WATCHED,
            "mastery": mastery / 100 if q is not None else None,
            "scenes": [{"label": s["label"], "start": s["start"], "end": s["end"]} for s in timing["scenes"]],
            "cues": [
                {"start": c["start"], "end": c["end"], "text": c["text"], "scene": c["scene"]} for c in timing["cues"]
            ],
            "quiz": [qq.model_dump(exclude={"quote"}) for qq in q.questions] if q is not None else [],
            "ui": ui_strings(lang),
        }
        (root / "lesson.js").write_text(
            "window.KINETRY_LESSON = " + json.dumps(lesson, ensure_ascii=False).replace("</", "<\\/") + ";\n",
            encoding="utf-8",
        )
        (root / "index.html").write_text(
            _index_html(title, lang, brand, has_poster, timing.get("burned_captions", False)), encoding="utf-8"
        )

        files = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file())
        ident = (
            "kinetry-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{title}|{timing['duration']}|{vid.stat().st_size}").hex[:16]
        )
        if standard == "scorm12":
            (root / "imsmanifest.xml").write_text(
                _manifest_scorm12(ident, title, files, mastery if q else None), encoding="utf-8"
            )
        elif standard == "scorm2004":
            (root / "imsmanifest.xml").write_text(
                _manifest_scorm2004(ident, title, files, mastery if q else None), encoding="utf-8"
            )

        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    arc = str(p.relative_to(root)).replace("\\", "/")
                    # video is already compressed: store it, so the LMS can stream it straight from the zip
                    z.write(p, arc, compress_type=zipfile.ZIP_STORED if arc.endswith(".mp4") else zipfile.ZIP_DEFLATED)
        allfiles = sorted(files + (["imsmanifest.xml"] if standard != "web" else []))
    return Package(out, standard, len(q.questions) if q else 0, notes, allfiles)


def _index_html(title: str, lang: str, brand: dict, has_poster: bool, burned: bool = False) -> str:
    code = (lang or "en").split("-")[0].lower()
    d = "rtl" if code in RTL else "ltr"
    css_vars = "".join(
        f"--{k}:{brand[v]};"
        for k, v in (
            ("bg", "background"),
            ("surface", "surface"),
            ("ink", "ink"),
            ("muted", "muted"),
            ("line", "line"),
            ("accent", "accent"),
            ("on-accent", "accent_ink"),
        )
        if isinstance(brand.get(v), str) and re.fullmatch(r"#[0-9a-fA-F]{3,8}", brand[v])
    )
    poster = ' poster="media/poster.jpg"' if has_poster else ""
    ui = ui_strings(lang)
    t = escape(title)
    return f"""<!doctype html>
<html lang="{escape(lang)}" dir="{d}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t}</title>
<link rel="stylesheet" href="player.css">
<style>:root{{{css_vars}}}</style>
</head>
<body>
<main class="lesson">
  <h1>{t}</h1>
  <div class="stage">
    <video id="video" controls playsinline preload="metadata"{poster} src="media/video.mp4">
      <track kind="captions" src="media/captions.vtt" srclang="{escape(code)}" label="{escape(ui["captions"])}"{"" if burned else " default"}>
      <track kind="chapters" src="media/chapters.vtt" srclang="{escape(code)}" label="{escape(ui["chapters"])}">
    </video>
    <div class="meter" aria-hidden="true"><i id="meter"></i></div>
    <p class="status" id="status" aria-live="polite"></p>
  </div>
  <div class="cols">
    <nav class="panel" aria-labelledby="ch-h"><h2 id="ch-h"></h2><ol id="chapters"></ol></nav>
    <section class="panel" aria-labelledby="tr-h"><h2 id="tr-h"></h2><div id="transcript" class="transcript"></div>
      <a id="download" href="media/transcript.txt" download></a></section>
  </div>
  <section class="panel quiz" id="quiz" aria-labelledby="q-h" hidden><h2 id="q-h"></h2><p id="q-lock"></p>
    <form id="q-form"></form><p class="result" id="q-result" aria-live="polite"></p></section>
</main>
<script src="lms.js"></script>
<script src="lesson.js"></script>
<script src="player.js"></script>
</body>
</html>
"""
