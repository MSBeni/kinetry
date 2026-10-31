"""The brief agent: a request in plain words -> a structured video request.

    "60-second vertical video for new nurses on hand hygiene, in Spanish, from this: <text>"
    -> Brief(kind="how_to", audience="new nurses", length="60s", lang="es", format="9:16", source_text=...)

With a model, the model reads the message (in any language) and the code checks every field. Without one, or
when the model fails, a keyword reader does what it can. Either way the brief says what's still missing in
`questions` (most often: the content to make the video from), and `to_request()` gives the body for
POST /v1/plans or /v1/videos. The brief never invents content: the source text is only ever text the user gave.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from .kinds import KINDS, get_kind

log = logging.getLogger(__name__)

FORMATS = ("16:9", "9:16", "1:1")
LANGS = {
    "english": "en", "spanish": "es", "español": "es", "french": "fr", "français": "fr", "german": "de",
    "deutsch": "de", "italian": "it", "portuguese": "pt", "brazilian portuguese": "pt-BR", "dutch": "nl",
    "polish": "pl", "turkish": "tr", "russian": "ru", "ukrainian": "uk", "greek": "el", "swedish": "sv",
    "farsi": "fa", "persian": "fa", "arabic": "ar", "hebrew": "he", "urdu": "ur", "hindi": "hi", "bengali": "bn",
    "japanese": "ja", "chinese": "zh", "mandarin": "zh", "korean": "ko", "vietnamese": "vi", "thai": "th",
    "indonesian": "id", "malay": "ms", "filipino": "fil", "tagalog": "fil", "swahili": "sw",
}  # fmt: skip
KIND_WORDS = [
    ("session_recap", r"\b(?:recap|debrief|session summary|meeting summary|what we covered)\b"),
    ("course_summary", r"\b(?:course (?:summary|overview|trailer|preview)|program overview|syllabus)\b"),
    ("announcement", r"\b(?:announc\w*|launch(?:ing|es)?|news|heads[- ]up|we're changing|policy change)\b"),
    ("onboarding", r"\b(?:onboard\w*|welcome (?:video|to)|new (?:hires?|starters?|joiners?)|first (?:day|week))\b"),
    ("how_to", r"\b(?:how[- ]to|how do (?:i|you)|step[- ]by[- ]step|walk ?through|tutorial)\b"),
    ("explainer", r"\b(?:explain\w*|what is|what are|introduction to|intro to)\b"),
    ("lesson", r"\b(?:lesson|module|lecture|class|chapter)\b"),
]
STYLES = ("editorial", "technical", "warm", "bold", "minimal", "corporate", "classic")


class Brief(BaseModel):
    kind: str | None = Field(None, description=f"one of: {', '.join(KINDS)}; null if unclear")
    title: str = Field("", max_length=120, description="a short working title")
    topic: str = Field("", max_length=300, description="what the video is about, in one line")
    audience: str = Field("", max_length=160)
    length: str | None = Field(None, description="e.g. '60s' or '2 min', only if the user said")
    lang: str | None = Field(None, description="language code of the video, e.g. 'en', 'es', 'fa', only if said")
    format: str | None = Field(None, description="16:9, 9:16 (vertical/phone) or 1:1 (square), only if said")
    style: str | None = Field(None, description=f"one of {', '.join(STYLES)}, only if the user named a look")
    captions: bool | None = None
    tone: str = Field("", max_length=80)
    source_text: str = Field("", description="content the user pasted to make the video from, verbatim; else empty")
    source_url: str | None = Field(None, description="a link the user gave to read the content from")
    notes: str = Field("", max_length=600, description="other instructions (must-include points, things to avoid)")
    questions: list[str] = Field(default_factory=list, description="what's missing before a video can be made")

    def to_request(self) -> dict:
        """Body for POST /v1/plans or /v1/videos (add brand_id, voices, ...). Without source text, read
        `source_url` first (POST /v1/sources/url) or ask the user for the content."""
        ctx = {
            k: v
            for k, v in {
                "audience": self.audience,
                "length": self.length,
                "tone": self.tone,
                "topic": self.topic,
                "notes": self.notes,
            }.items()
            if v
        }
        design = {
            k: v
            for k, v in {
                "format": self.format,
                "style": self.style,
                "lang": self.lang,
                "captions": self.captions,
            }.items()
            if v is not None
        }
        out: dict = {"design": design}
        if self.source_text.strip():
            out["source"] = {"text": self.source_text, "title": self.title, "kind": self.kind, "context": ctx}
        else:
            out["source"] = None
            out["pending_source"] = {"url": self.source_url, "title": self.title, "kind": self.kind, "context": ctx}
        return out


BRIEF_SYSTEM = """You turn a request for a short narrated video into a structured brief. Read the message
(it may be in any language) and fill only what it says or clearly implies; leave the rest empty or null.

Video kinds:
{kinds}

Rules:
- kind: the closest kind, or null if none fits.
- source_text: copy the content the user pasted for the video word for word. Never write content yourself:
  if there's no pasted content, leave it empty.
- source_url: a link the user gave as the content.
- format: 9:16 for vertical, phone, reels or stories; 1:1 for square; 16:9 for widescreen. Null if not said.
- lang: the language the video should be in, as a code (en, es, fr, fa, ar, ja, ...). Null if not said.
- questions: short questions for what's missing before a video can be made (always ask for the content when
  there's no source_text and no source_url). Ask at most three.
Return a Brief.
"""


def _clean(b: Brief, message: str) -> Brief:
    """The code's word on every field, whatever produced it."""
    try:
        b.kind = get_kind(b.kind).id if b.kind else None
    except ValueError:
        b.kind = None
    if b.format not in FORMATS:
        b.format = {"vertical": "9:16", "portrait": "9:16", "square": "1:1", "landscape": "16:9"}.get(
            str(b.format or "").lower()
        )
    if b.style and b.style.lower() not in STYLES:
        b.style = None
    if b.lang:
        lang = b.lang.strip()
        b.lang = LANGS.get(lang.lower(), lang if re.fullmatch(r"[a-zA-Z]{2,3}(?:-[A-Za-z0-9]{2,8})?", lang) else None)
    if b.length and not re.match(r"\s*\d+(?:\.\d+)?\s*(s|sec|seconds?|m|min|minutes?)?\s*$", b.length.lower()):
        b.length = None
    # the source text must come from the message, never from the model
    if b.source_text and _norm(b.source_text) not in _norm(message):
        log.info("brief: dropped source text that isn't in the message")
        b.source_text = ""
    if b.source_url and b.source_url not in message:
        b.source_url = None
    if not b.source_text.strip() and not b.source_url and not any("content" in q.lower() for q in b.questions):
        b.questions.insert(
            0, "What should the video be made from? Paste the content, attach a document or give a link."
        )
    b.questions = b.questions[:3]
    return b


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def heuristic_brief(message: str) -> Brief:
    b = Brief()
    m = message.strip()
    # pasted content: what follows a colon or a blank line, when it's long enough to be the content itself;
    # only the request before it is read for kind, length, audience and the rest
    parts = re.split(r":\s*\n|\n\s*\n|:\s+(?=\S[^\n]{200,})", m, maxsplit=1)
    if len(parts) == 2 and len(parts[1].split()) >= 40:
        b.source_text = parts[1].strip()
        m = parts[0].strip()
    low = m.lower()
    for kind, rx in KIND_WORDS:
        if re.search(rx, low):
            b.kind = kind
            break
    d = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?\s*(seconds?|secs?|s|minutes?|mins?|m)\b", low)
    if d:
        unit = "min" if d.group(2).startswith("m") else "s"
        b.length = f"{d.group(1)}{unit}"
    if re.search(r"\b(?:vertical|portrait|phones?|mobile|reels?|stories|tiktok|shorts|9:16)\b", low):
        b.format = "9:16"
    elif re.search(r"\b(?:square|1:1)\b", low):
        b.format = "1:1"
    elif re.search(r"\b(?:widescreen|landscape|16:9)\b", low):
        b.format = "16:9"
    for name in sorted(LANGS, key=len, reverse=True):
        if re.search(rf"\b(?:in|into)\s+{re.escape(name)}\b", low):
            b.lang = LANGS[name]
            break
    if re.search(r"\b(?:captions?|subtitles?|subtitled)\b", low) and not re.search(
        r"\bno (?:captions?|subtitles?)\b", low
    ):
        b.captions = True
    for s in STYLES:
        if re.search(rf"\b{s}\b (?:style|look)", low):
            b.style = s
    a = re.search(
        r"\bfor\s+((?:new|our|all|the|junior|senior)?\s*[a-z][a-z -]{2,40}?)(?=\s+(?:about|on|in|to|from|with|that|who)\b|[,.:;]|$)",
        low,
    )
    if a and not re.fullmatch(r"(?:\d.*|a minute|now|today|me|us)", a.group(1).strip()):
        b.audience = a.group(1).strip()
    t = re.search(r"\b(?:about|on)\s+(.{3,120}?)(?=[,.:;\n]|\s+(?:for|in|from|with)\b|$)", m, re.I)
    if t and not re.match(r"(?i)(?:https?|www)\b", t.group(1)):
        b.topic = t.group(1).strip()
        b.title = b.topic[:1].upper() + b.topic[1:]
    u = re.search(r"https?://[^\s<>\"')\]]+", m)
    if u:
        b.source_url = u.group(0).rstrip(".,;")
    return _clean(b, message)


def make_brief(message: str, *, llm=None, settings=None) -> Brief:
    """A chat request -> Brief. Uses the model when one is given or configured, else the keyword reader."""
    if not message or not message.strip():
        raise ValueError("message is empty")
    if len(message) > 200_000:
        raise ValueError("message is too long; send the content as a source document instead")
    if llm is None and settings is None:
        return heuristic_brief(message)
    try:
        from .agents import get_llm
        from .llm import invoke_structured

        if settings is None:
            from .config import Settings

            settings = Settings()
        model = get_llm(settings, llm, 0.1)
        kinds = "\n".join(f"- {k.id}: {k.purpose}" for k in KINDS.values())
        sys = BRIEF_SYSTEM.format(kinds=kinds)
        b = invoke_structured(
            model, Brief, [{"role": "system", "content": sys}, {"role": "user", "content": message}], json_mode=True
        )
        return _clean(b, message)
    except Exception as e:  # noqa: BLE001  (no model configured, provider error, bad JSON)
        log.info("brief: model unavailable (%s); using the keyword reader", str(e)[:160])
        return heuristic_brief(message)


def brief_json(b: Brief) -> str:
    return json.dumps({"brief": b.model_dump(), "request": b.to_request()}, indent=2, ensure_ascii=False)
