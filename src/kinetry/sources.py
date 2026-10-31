"""Source content: the text a video is made from.

Kinetry takes plain text or Markdown, and reads Word (.docx), PowerPoint (.pptx), text-based PDF, web
pages and audio/video recordings into it (see loaders.py and stt.py). Callers with their own formats (an
LMS, a course builder, a guide generator) convert to `Source` on their side, which keeps this package free
of any one platform's data model.

Long sources aren't summarized yet: a source is limited to MAX_SOURCE_WORDS, and longer documents are
planned one section at a time (`section=`). Course export zips (SCORM, Common Cartridge) aren't supported.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_SOURCE_WORDS = 12_000  # about 25 pages; longer sources need summarizing, which isn't built yet


class Source(BaseModel):
    text: str = Field(..., min_length=20, description="The content to explain. Plain text or Markdown.")
    title: str = Field("", max_length=200)
    context: dict = Field(
        default_factory=dict,
        description="Facts for the planner that aren't in the text: program name, audience, "
        "session number/count, sibling session titles, language, tone.",
    )

    kind: str | None = Field(
        None,
        description="What the video is for: lesson, course_summary, session_recap, explainer, how_to, "
        "announcement or onboarding. Shapes the plan's structure, default length and scene types.",
    )

    @model_validator(mode="after")
    def _kind(self) -> Source:
        from .kinds import get_kind

        k = get_kind(self.kind or self.context.get("kind"))
        self.kind = k.id if k else None
        if k:
            self.context = {**self.context, "kind": k.id}
        return self

    @field_validator("text")
    @classmethod
    def _not_too_long(cls, v: str) -> str:
        n = len(v.split())
        if n > MAX_SOURCE_WORDS:
            raise ValueError(
                f"source is {n} words; the limit is {MAX_SOURCE_WORDS} because long sources aren't summarized "
                "yet. Make a video per section instead (section= / --section; `kinetry sections FILE` lists them)."
            )
        return v


def html_to_text(html: str) -> str:
    s = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", "", html)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<h[1-6][^>]*>", "\n## ", s)
    s = re.sub(r"(?i)</(p|ul|ol|li|div|h[1-6]|section|br)>|<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def split_sections(markdown: str) -> list[tuple[str, str]]:
    """Split Markdown into [(title, body)]. If the document uses `##` headings, those are the
    sections (a leading `#` heading is the document title); otherwise `#` headings are."""
    level = 2 if re.search(r"(?m)^##\s", markdown) else 1
    head = re.compile(r"^#{" + str(level) + r"}\s+(.*)")
    parts: list[tuple[str, str]] = []
    title, buf = "", []
    for line in markdown.splitlines():
        m = head.match(line)
        if m:
            if title or "".join(buf).strip():
                parts.append((title, "\n".join(buf).strip()))
            title, buf = m.group(1).strip(), []
        elif level == 2 and re.match(r"^#\s", line):
            continue  # document title, handled by doc_title()
        else:
            buf.append(line)
    if title or "".join(buf).strip():
        parts.append((title, "\n".join(buf).strip()))
    return [(t, b) for t, b in parts if t]


def doc_title(markdown: str) -> str:
    m = re.search(r"(?m)^#\s+(.*)", markdown)
    return m.group(1).strip() if m and re.search(r"(?m)^##\s", markdown) else ""


def read_markdown(path: str | Path, *, public_only: bool = False) -> tuple[str, str, str]:
    """Any supported text source as Markdown -> (markdown, title, kind). Recordings aren't included (they need a
    transcriber); .json sources aren't Markdown."""
    from .loaders import DOC_EXTS, UNSUPPORTED, load_document

    s = str(path)
    if public_only and not re.match(r"(?i)^https?://", s):  # a caller's URL never names a file on this machine
        raise ValueError("only http(s) web page URLs can be read")
    if re.match(r"(?i)^https?://", s) or Path(s).suffix.lower() in DOC_EXTS or Path(s).suffix.lower() in UNSUPPORTED:
        return load_document(s, public_only=public_only)
    p = Path(s)
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".html", ".htm"):
        return html_to_text(raw), "", "web page"
    return raw, "", ""


def load_source(
    path: str | Path,
    section: int | None = None,
    context: dict | None = None,
    *,
    transcriber=None,
    public_only: bool = False,
) -> Source:
    """Load .md/.txt/.html/.json, a Word/PowerPoint/PDF file, a web page URL, or an audio/video recording
    (transcribed with `transcriber`, default Inworld inworld-stt-1). With `section` (1-based), pick one section
    (a `##` heading, a Word Heading 1, a slide, a PDF chapter or page group) and pass the other section titles to
    the planner as context."""
    ctx = dict(context or {})
    if re.match(r"(?i)^https?://", str(path)):
        raw, title, kind = read_markdown(str(path), public_only=public_only)
        ctx.setdefault("source_kind", kind)
        ctx.setdefault("source_url", str(path))
        return _pick(raw, title or str(path), section, ctx)
    p = Path(path)
    from .stt import AUDIO_EXTS, make_transcriber

    if p.suffix.lower() in AUDIO_EXTS:
        if section is not None:
            raise ValueError("--section applies to Markdown files, not recordings")
        tr = make_transcriber(transcriber).transcribe(p)
        if not tr.text.strip():
            raise ValueError(f"no speech found in {p.name}")
        ctx.setdefault("source_kind", "transcript of a recording")
        if tr.duration:
            ctx.setdefault("recording_minutes", round(tr.duration / 60, 1))
        return Source(text=tr.text, title=p.stem, context=ctx)
    if p.suffix.lower() == ".json":
        raw = p.read_text(encoding="utf-8")
        return Source.model_validate(
            json.loads(raw) | ({"context": ctx | json.loads(raw).get("context", {})} if ctx else {})
        )
    raw, title, kind = read_markdown(p, public_only=public_only)
    if kind and kind != "web page":
        ctx.setdefault("source_kind", kind)
    return _pick(raw, title or doc_title(raw) or p.stem, section, ctx)


def source_from_markdown(raw: str, title: str, section: int | None = None, context: dict | None = None) -> Source:
    """Markdown (from any loader) -> Source, optionally one section of it with the others as context."""
    return _pick(raw, title, section, dict(context or {}))


def _pick(raw: str, title: str, section: int | None, ctx: dict) -> Source:
    title = title[:200]
    name = title or "the source"
    if section is None:
        return Source(text=raw, title=title, context=ctx)
    sections = split_sections(raw)
    if not 1 <= section <= len(sections):
        raise ValueError(f"{name} has {len(sections)} sections; asked for {section}")
    title, body = sections[section - 1]
    if doc_title(raw):
        ctx.setdefault("document_title", doc_title(raw))
    ctx.setdefault("section_number", section)
    ctx.setdefault("section_count", len(sections))
    ctx.setdefault("all_sections", [t for t, _ in sections])
    return Source(text=body, title=title, context=ctx)
