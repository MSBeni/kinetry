"""Word, PowerPoint, PDF and web page loaders, on documents generated here (no customer files)."""

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("docx")
pytest.importorskip("pptx")
pytest.importorskip("pypdf")

from kinetry.loaders import (
    LoaderError,
    docx_to_markdown,
    load_document,
    pdf_to_markdown,
    pptx_to_markdown,
    web_to_markdown,
)  # noqa: E402
from kinetry.sources import MAX_SOURCE_WORDS, Source, load_source, split_sections  # noqa: E402

LOREM = "Managers who give feedback within two days see faster change in their teams. "


def make_docx(path: Path) -> Path:
    import docx

    d = docx.Document()
    d.core_properties.title = "Feedback guide"
    d.add_heading("Why timing matters", level=1)
    d.add_paragraph(LOREM * 3)
    d.add_paragraph("Name the behavior", style="List Bullet")
    d.add_paragraph("Say what it caused", style="List Bullet")
    d.add_heading("A worked example", level=1)
    d.add_heading("The situation", level=2)
    d.add_paragraph(LOREM * 2)
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Instead of", "Try"
    t.cell(1, 0).text, t.cell(1, 1).text = "You're careless", "You skipped the pricing slide"
    d.save(path)
    return path


def make_pptx(path: Path) -> Path:
    import pptx
    from pptx.util import Inches

    prs = pptx.Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Spot the phish"
    s.placeholders[1].text = "Three checks before you click"
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Check the sender"
    body = s.placeholders[1].text_frame
    body.text = "Look at the full address"
    p = body.add_paragraph()
    p.text, p.level = "Not just the display name", 1
    s.notes_slide.notes_text_frame.text = "Say: attackers copy names, not domains."
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Report it"
    box = s.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    box.text_frame.text = "Use the report button"
    prs.save(path)
    return path


def make_pdf(path: Path, pages: list[list[str]], outline: list[tuple[str, int]] = ()) -> Path:
    """A real text PDF written by hand (Helvetica text objects), with optional bookmarks added by pypdf."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        ops = (
            "BT /F1 11 Tf 14 TL 72 760 Td "
            + " ".join(
                "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for ln in lines
            )
            + " ET"
        )
        objs.append(f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream")
        content = len(objs)
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        )
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    if outline:
        import pypdf

        w = pypdf.PdfWriter(clone_from=str(path))
        for title, page in outline:
            w.add_outline_item(title, page)
        w.write(str(path))
    return path


def test_word(tmp_path):
    md, title = docx_to_markdown(make_docx(tmp_path / "guide.docx"))
    assert title == "Feedback guide" and md.startswith("# Feedback guide")
    assert [t for t, _ in split_sections(md)] == ["Why timing matters", "A worked example"]
    assert "- Name the behavior" in md and "### The situation" in md
    assert "Instead of | Try" in md and "You're careless | You skipped the pricing slide" in md
    src = load_source(tmp_path / "guide.docx", section=2)
    assert src.title == "A worked example" and src.context["section_count"] == 2
    assert src.context["source_kind"] == "Word document" and src.context["document_title"] == "Feedback guide"


def test_powerpoint_keeps_speaker_notes(tmp_path):
    md, title = pptx_to_markdown(make_pptx(tmp_path / "deck.pptx"))
    assert title == "Spot the phish"
    assert [t for t, _ in split_sections(md)] == [
        "Slide 1: Spot the phish",
        "Slide 2: Check the sender",
        "Slide 3: Report it",
    ]
    assert "- Look at the full address" in md and "  - Not just the display name" in md
    assert "Speaker notes: Say: attackers copy names, not domains." in md and "- Use the report button" in md
    src = load_source(tmp_path / "deck.pptx", section=2)
    assert "attackers copy names" in src.text and src.context["source_kind"] == "slide deck"


def test_pdf_page_groups_drop_running_headers(tmp_path):
    pages = [["Acme Training - Confidential", f"Lesson part {i}.", LOREM, f"Page {i}"] for i in range(1, 8)]
    md, _ = pdf_to_markdown(make_pdf(tmp_path / "doc.pdf", pages))
    assert [t for t, _ in split_sections(md)] == ["Pages 1-5", "Pages 6-7"]
    assert "Confidential" not in md and "Page 3" not in md and "Lesson part 3." in md


def test_pdf_bookmarks_become_sections(tmp_path):
    first = ["Why feedback matters.", "Most people wait.", "Timing changes everything.", "Be specific.", "Then listen."]
    pages = [[first[i - 1], f"Chapter text {i}.", LOREM, "In practice, start small."] for i in range(1, 6)]
    md, _ = pdf_to_markdown(make_pdf(tmp_path / "book.pdf", pages, [("Getting started", 0), ("Going deeper", 2)]))
    secs = split_sections(md)
    assert [t for t, _ in secs] == ["Getting started", "Going deeper"]
    assert "Chapter text 2." in secs[0][1] and "Chapter text 3." in secs[1][1]


def test_scanned_pdf_is_refused_clearly(tmp_path):
    with pytest.raises(LoaderError, match="scanned"):
        pdf_to_markdown(make_pdf(tmp_path / "scan.pdf", [[""], [""]]))


def test_unsupported_formats_say_so(tmp_path):
    for name, msg in (("course.zip", "supported yet"), ("old.doc", "save it as .docx"), ("old.ppt", ".pptx")):
        (tmp_path / name).write_bytes(b"x")
        with pytest.raises(LoaderError, match=msg):
            load_document(tmp_path / name)


def test_decompression_bomb_is_refused(tmp_path, monkeypatch):
    import kinetry.loaders as L

    p = tmp_path / "big.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "0" * 2_000_000)
    monkeypatch.setattr(L, "MAX_UNZIPPED", 1_000_000)
    with pytest.raises(LoaderError, match="too large"):
        docx_to_markdown(p)


PAGE = """<html><head><title>Giving feedback | Example blog</title></head><body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<article><h1>Giving feedback that lands</h1>
<p>Feedback works best within a day or two of what happened, while everyone still remembers it clearly.</p>
<h2>Name the behavior</h2>
<p>Describe what the person did, not who they are. Say what it caused, then ask a question and listen.</p>
<p>Positive feedback follows the same pattern: be specific so the person knows what to repeat next time.</p>
</article><footer>Copyright 2026 Example blog. All rights reserved.</footer></body></html>"""


def test_web_page_main_content(tmp_path):
    md, title = web_to_markdown("https://blog.example/feedback", fetch=lambda u: PAGE)
    assert title == "Giving feedback | Example blog"
    assert "within a day or two" in md and "Name the behavior" in md
    assert "Copyright 2026" not in md and "About" not in md.split("\n", 1)[1]


def test_web_page_needs_public_address_in_service_mode():
    with pytest.raises(ValueError, match="non-public|resolve"):
        web_to_markdown("http://127.0.0.1/admin", public_only=True, fetch=lambda u: PAGE)


def test_javascript_only_page_says_what_to_do():
    with pytest.raises(LoaderError, match="JavaScript"):
        web_to_markdown("https://app.example", fetch=lambda u: "<html><body><div id=root></div></body></html>")


def test_long_sources_are_refused_with_a_way_forward():
    with pytest.raises(ValueError, match="per section"):
        Source(text="word " * (MAX_SOURCE_WORDS + 1))


def test_service_reads_uploads_and_urls(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import kinetry.loaders as L
    from kinetry import service
    from kinetry.jobs import JobManager

    service.set_job_manager(JobManager(data_dir=tmp_path / "data"))
    monkeypatch.setenv("KINETRY_API_KEY", "k")
    c = TestClient(service.app)
    h = {"Authorization": "Bearer k"}
    deck = make_pptx(tmp_path / "deck.pptx")
    r = c.post("/v1/sources", files={"file": ("deck.pptx", deck.read_bytes())}, data={"section": "2"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"]["title"] == "Slide 2: Check the sender" and len(body["sections"]) == 3
    r = c.post("/v1/sources", files={"file": ("course.zip", b"PK")}, headers=h)
    assert r.status_code == 415 and "supported yet" in r.json()["detail"]
    monkeypatch.setattr(
        L, "web_to_markdown", lambda url, public_only=False, fetch=None: ("# T\n\n## A\n\n" + "words " * 50, "T")
    )
    import kinetry.netguard as G

    monkeypatch.setattr(G, "check_public_url", lambda url, allow_private=False, what="URL": url)  # no DNS in tests
    r = c.post("/v1/sources/url", json={"url": "https://blog.example/x"}, headers=h)
    assert r.status_code == 200 and r.json()["source"]["context"]["source_url"] == "https://blog.example/x"
