"""Documents in, Markdown out: Word, PowerPoint, PDF and web pages.

Every loader returns Markdown with one `## ` heading per section (a Word Heading 1, a slide, a PDF chapter
or page group, a web page's top headings) and an optional `# ` document title, so `--section N` and the
planner treat them like any Markdown source.

Supported: .docx, .pptx, text-based .pdf, public web pages (http/https).
Not supported yet: scanned PDFs (no OCR), legacy .doc/.ppt, course export zips (SCORM, Common Cartridge),
and summarizing long sources; long documents should be planned one section at a time.

The parsers are an optional install: pip install "kinetry[docs]".
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path

DOC_EXTS = {".docx": "Word document", ".pptx": "slide deck", ".pdf": "PDF"}
UNSUPPORTED = {
    ".doc": "legacy Word files aren't supported; save it as .docx",
    ".ppt": "legacy PowerPoint files aren't supported; save it as .pptx",
    ".zip": "course export zips (SCORM, Common Cartridge) aren't supported yet",
    ".imscc": "Common Cartridge packages aren't supported yet",
}
MAX_UNZIPPED = 300_000_000  # Office files are zips: refuse decompression bombs before parsing
MAX_PAGE_BYTES = 5_000_000


class LoaderError(ValueError):
    pass


def _need(module: str, pip_name: str):
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise LoaderError(f"reading this file needs {pip_name}: pip install 'kinetry[docs]'") from e


def _check_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            total = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile as e:
        raise LoaderError(f"{path.name} isn't a valid Office file") from e
    if total > MAX_UNZIPPED:
        raise LoaderError(f"{path.name} expands to {total // 1_000_000} MB; too large to read safely")


def _clean(text: str) -> str:
    text = text.replace("\r", "").replace(" ", " ").replace("\u000b", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- Word
def docx_to_markdown(path: Path) -> tuple[str, str]:
    """-> (markdown, title). Heading 1 = section; Heading 2+ = sub-headings; lists and tables kept as text."""
    _check_zip(path)
    docx = _need("docx", "python-docx")
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    title = (d.core_properties.title or "").strip()
    out: list[str] = []
    for block in d.iter_inner_content():
        if isinstance(block, Paragraph):
            text = _clean(block.text)
            if not text:
                continue
            style = (block.style.name if block.style is not None else "").lower()
            if style == "title":
                title = title or text
                out.append(f"# {text}")
            elif m := re.match(r"heading (\d)", style):
                out.append(("## " if m.group(1) == "1" else "### ") + text)
            elif "list" in style:
                out.append(f"- {text}")
            else:
                out.append(text)
        elif isinstance(block, Table):
            for row in block.rows:
                cells = []
                for c in row.cells:
                    t = _clean(c.text)
                    if t and (not cells or cells[-1] != t):  # merged cells repeat their text
                        cells.append(t)
                if cells:
                    out.append(" | ".join(cells))
    md = "\n\n".join(out)
    if title and not md.startswith("# "):
        md = f"# {title}\n\n{md}"
    return md, title


# ---------------------------------------------------------------- PowerPoint
def pptx_to_markdown(path: Path) -> tuple[str, str]:
    """-> (markdown, title). One section per slide: its title, its text and its speaker notes."""
    _check_zip(path)
    pptx = _need("pptx", "python-pptx")
    prs = pptx.Presentation(str(path))
    title = (prs.core_properties.title or "").strip()
    out: list[str] = []

    def shape_text(shape) -> list[str]:
        lines = []
        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                t = _clean("".join(r.text for r in para.runs))
                if t:
                    lines.append(("  " * para.level) + f"- {t}")
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                cells = [_clean(c.text) for c in row.cells if _clean(c.text)]
                if cells:
                    lines.append(" | ".join(cells))
        for sub in getattr(shape, "shapes", []) or []:  # groups
            lines += shape_text(sub)
        return lines

    for i, slide in enumerate(prs.slides, 1):
        head = ""
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            head = _clean(slide.shapes.title.text_frame.text)
        if i == 1 and head and not title:
            title = head
        body = []
        for shape in slide.shapes:
            if slide.shapes.title is not None and shape.shape_id == slide.shapes.title.shape_id:
                continue
            body += shape_text(shape)
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = _clean(slide.notes_slide.notes_text_frame.text)
        if not (head or body or notes):
            continue
        part = [f"## Slide {i}" + (f": {head}" if head else "")]
        part += body
        if notes:
            part.append(f"Speaker notes: {notes}")
        out.append("\n".join(part))
    md = "\n\n".join(out)
    if title:
        md = f"# {title}\n\n{md}"
    return md, title


# ---------------------------------------------------------------- PDF
def pdf_to_markdown(path: Path, pages_per_section: int = 5) -> tuple[str, str]:
    """-> (markdown, title). Sections follow the PDF's bookmarks when it has them, else groups of pages.
    Lines repeated at the top or bottom of most pages (running headers, footers, page numbers) are dropped."""
    pypdf = _need("pypdf", "pypdf")
    import logging

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding chatter on real-world PDFs
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception as e:  # noqa: BLE001
        raise LoaderError(f"{path.name} isn't a readable PDF: {type(e).__name__}") from e
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:  # noqa: BLE001
            raise LoaderError(f"{path.name} is password-protected") from e
    pages = [(p.extract_text() or "") for p in reader.pages]
    n = len(pages)
    if n == 0 or sum(len(p.strip()) for p in pages) < 40 * n:
        raise LoaderError(
            f"{path.name} has almost no text layer; it looks scanned, and reading scanned PDFs (OCR) isn't supported yet"
        )

    # running headers and footers: the same short first/last line on more than half the pages (numbers ignored, so
    # "Guide, page 2" and "Guide, page 3" match), plus bare page numbers ("12", "Page 3 of 10").
    page_no = re.compile(r"(?i)^\W*(page|p\.)?\s*\d+(\s*(of|/)\s*\d+)?\W*$")
    edges = Counter()
    split = [[ln.strip() for ln in p.splitlines() if ln.strip()] for p in pages]
    for lines in split:
        for ln in {lines[0], lines[-1]} if lines else set():
            if len(ln) <= 80:
                edges[re.sub(r"\d+", "#", ln)] += 1
    repeated = {k for k, c in edges.items() if n >= 3 and c > n / 2}

    def page_text(i: int) -> str:
        lines = split[i]
        keep = [
            ln
            for j, ln in enumerate(lines)
            if not ((j == 0 or j == len(lines) - 1) and (re.sub(r"\d+", "#", ln) in repeated or page_no.match(ln)))
        ]
        return _clean(_unwrap("\n".join(keep)))

    meta = reader.metadata or {}
    title = _clean(str(meta.get("/Title") or "")) if meta else ""

    # top-level bookmarks -> (title, first page)
    marks: list[tuple[str, int]] = []
    try:
        for item in reader.outline:
            if isinstance(item, list):
                continue
            pg = reader.get_destination_page_number(item)
            if pg is not None and item.title:
                marks.append((_clean(item.title), pg))
    except Exception:  # noqa: BLE001  (broken outlines are common; fall back to page groups)
        marks = []
    marks = sorted({pg: t for t, pg in marks}.items())
    out: list[str] = []
    if len(marks) >= 2:
        starts = [pg for pg, _ in marks]
        if starts[0] > 0:
            out.append("## Introduction\n\n" + "\n\n".join(page_text(i) for i in range(starts[0])))
        for k, (pg, t) in enumerate(marks):
            end = starts[k + 1] if k + 1 < len(starts) else n
            out.append(f"## {t}\n\n" + "\n\n".join(page_text(i) for i in range(pg, end)))
    else:
        for s in range(0, n, pages_per_section):
            e = min(n, s + pages_per_section)
            label = f"Page {s + 1}" if e - s == 1 else f"Pages {s + 1}-{e}"
            out.append(f"## {label}\n\n" + "\n\n".join(page_text(i) for i in range(s, e)))
    md = "\n\n".join(x for x in out if x.strip())
    if title:
        md = f"# {title}\n\n{md}"
    return md, title


def _unwrap(text: str) -> str:
    """PDF text comes as visual lines: join lines inside a paragraph, keep blank lines and list items."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # hyphenated line breaks
    lines = text.split("\n")
    out: list[str] = []
    for ln in lines:
        if (
            out
            and out[-1]
            and ln
            and not re.match(r"^\s*([-•*▪●]|\d+[.)])\s", ln)
            and not out[-1].endswith((".", ":", "?", "!"))
        ):
            out[-1] += " " + ln.strip()
        else:
            out.append(ln.strip())
    return "\n".join(out)


# ---------------------------------------------------------------- web pages
def web_to_markdown(url: str, *, public_only: bool = False, fetch=None) -> tuple[str, str]:
    """-> (markdown, title). The page's main content (menus, footers and ads removed). Pages that build their
    content with JavaScript come back nearly empty; save those from a browser as .html instead."""
    from .netguard import check_public_url, text_of
    from .netguard import client as make_client

    check_public_url(url, allow_private=not public_only, what="page URL")
    if fetch is None:
        client = make_client(
            public_only,
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (kinetry source loader)"},
        )

        def fetch(u: str) -> str:
            with client.stream("GET", u) as r:  # check the type before reading, and read no more than we keep
                r.raise_for_status()
                ctype = r.headers.get("content-type", "")
                if "html" not in ctype and "xml" not in ctype and "text" not in ctype:
                    raise LoaderError(f"{u} isn't a web page ({ctype or 'unknown type'})")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) >= MAX_PAGE_BYTES:
                        del buf[MAX_PAGE_BYTES:]
                        break
                return text_of(bytes(buf), r)

    html = fetch(url)
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    title = _clean(re.sub(r"<[^>]+>", "", m.group(1))) if m else ""
    md = ""
    try:
        import trafilatura

        md = (
            trafilatura.extract(
                html, output_format="markdown", include_tables=True, include_links=False, favor_recall=True
            )
            or ""
        )
    except ImportError:
        pass
    if len(md) < 200:  # no extractor, or it found little: fall back to the plain tag stripper
        from .sources import html_to_text

        md = html_to_text(html)
    md = _clean(re.sub(r"(?m)^#{1}\s", "## ", md))  # page headings become sections
    if len(md) < 200:
        raise LoaderError(
            f"{url} has almost no readable text; it may build its content with JavaScript. "
            "Save the page from a browser as .html and use that file."
        )
    if title:
        md = f"# {title}\n\n{md}"
    return md, title


def load_document(path_or_url: str | Path, *, public_only: bool = False) -> tuple[str, str, str]:
    """-> (markdown, title, kind) for a .docx, .pptx, .pdf or http(s) URL."""
    s = str(path_or_url)
    if re.match(r"(?i)^https?://", s):
        md, title = web_to_markdown(s, public_only=public_only)
        return md, title, "web page"
    p = Path(path_or_url)
    ext = p.suffix.lower()
    if ext in UNSUPPORTED:
        raise LoaderError(UNSUPPORTED[ext])
    if ext not in DOC_EXTS:
        raise LoaderError(f"{p.name}: unsupported file type")
    md, title = {".docx": docx_to_markdown, ".pptx": pptx_to_markdown, ".pdf": pdf_to_markdown}[ext](p)
    if len(md.strip()) < 20:
        raise LoaderError(f"{p.name} has no readable text")
    return md, title, DOC_EXTS[ext]
