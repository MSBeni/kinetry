"""Image scenes: where images may come from, the checks on their bytes, the upload endpoint and the planner rules.
No network: fetches are stubbed."""

import io
import json
from pathlib import Path

import pytest

from kinetry.design.catalog import load_catalog
from kinetry.design.plan import load_plan
from kinetry.images import ImageError, ImageResolver, check_image, save_upload, sniff

CAT = load_catalog()
PLAN = json.loads((Path(__file__).parent.parent / "examples" / "plans" / "feedback-that-lands.json").read_text())


def png(color=(200, 80, 40), size=(32, 20)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_type_comes_from_the_bytes_not_the_name():
    assert sniff(png()) == "png"
    assert sniff(b"\xff\xd8\xff\xe0rest") == "jpg"
    assert sniff(b"RIFF\0\0\0\0WEBPVP8 ") == "webp"
    assert sniff(b"GIF89a....") == "gif"
    for bad in (b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', b"%PDF-1.7", b"MZ\x90\0"):
        with pytest.raises(ImageError, match="isn't a PNG"):
            check_image(bad)
    with pytest.raises(ImageError, match="15 MB"):
        check_image(b"\x89PNG\r\n\x1a\n" + b"\0" * (15 * 1024 * 1024))


def test_references_resolve_into_the_project(tmp_path):
    uploads = tmp_path / "uploads"
    ref = save_upload(png(), uploads)
    assert ref.startswith("upload:") and save_upload(png(), uploads) == ref  # content-addressed
    local = tmp_path / "pic.png"
    local.write_bytes(png((10, 10, 10)))
    fetched = []

    def fetch(url):
        fetched.append(url)
        return png((0, 0, 255))

    r = ImageResolver(
        uploads_dir=uploads, brand_images=["https://brand.example/og.png"], base_dir=tmp_path, fetch=fetch
    ).bind(tmp_path / "proj" / "assets")
    srcs = [r.src(x) for x in (ref, "brand:1", "pic.png", "catalog:image_caption/example.jpg", ref)]
    assert all(s.startswith("assets/img-") for s in srcs) and srcs[0] == srcs[-1]
    assert fetched == ["https://brand.example/og.png"]
    assert len(list((tmp_path / "proj" / "assets").iterdir())) == 4
    for bad, msg in [
        ("brand:3", "1 site images"),
        ("upload:nothere0000000000", "unknown upload"),
        ("upload:../../etc/passwd", "unknown upload"),
        ("catalog:../../secrets.png", "bundled sample"),
        ("missing.png", "not found"),
    ]:
        with pytest.raises(ImageError, match=msg):
            r.src(bad)


def test_service_mode_refuses_local_files_and_private_hosts(tmp_path):
    local = tmp_path / "pic.png"
    local.write_bytes(png())
    r = ImageResolver(public_only=True, fetch=lambda u: png()).bind(tmp_path / "a")
    for ref in (str(local), "/etc/passwd", "file:///etc/passwd"):
        with pytest.raises(ImageError, match="https URL or an upload"):
            r.src(ref)
    for ref in ("http://127.0.0.1/x.png", "http://169.254.169.254/latest", "http://10.0.0.5/a.png"):
        with pytest.raises(ValueError):
            r.src(ref)
    assert r.src("catalog:image_caption/example.jpg").startswith("assets/")


def test_image_scene_renders_with_a_copied_image(tmp_path):
    from kinetry.branding import DEFAULT_KIT
    from kinetry.design.gallery import example_scenes
    from kinetry.design.icons import Icons
    from kinetry.design.plan import Design, VideoPlan2
    from kinetry.design.render import RenderInput, write_project
    from kinetry.timing import build_timeline, silent_clips

    ex = {}
    for s in example_scenes(CAT, "9:16"):
        ex.setdefault(s.type, s)
    scenes = [ex["title"], ex["image_caption"], ex["closer"]]
    for lang in ("en", "fa"):
        plan = VideoPlan2(title="t", design=Design(style="bold", format="9:16", lang=lang), scenes=scenes)
        gsap = tmp_path / "gsap.min.js"
        gsap.write_text("")
        tl = build_timeline(plan, silent_clips(plan), None)
        ri = RenderInput(plan=plan, brand=DEFAULT_KIT, fonts={}, timeline=tl, catalog=CAT, icons=Icons(None))
        out = write_project(ri, tmp_path / lang, gsap)
        html = (out / "index.html").read_text() if out.is_dir() else out.read_text()
        assert '<img class="kb"' in html and 'src="assets/img-' in html
        assert list((tmp_path / lang / "assets").glob("img-*.jpg"))


def test_upload_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from kinetry import service
    from kinetry.jobs import JobManager

    service.set_job_manager(JobManager(data_dir=tmp_path / "data"))
    monkeypatch.setenv("KINETRY_API_KEY", "k")
    c = TestClient(service.app)
    h = {"Authorization": "Bearer k"}
    assert c.post("/v1/images", files={"file": ("a.png", png())}).status_code == 401
    r = c.post("/v1/images", files={"file": ("a.png", png(), "image/png")}, headers=h)
    assert r.status_code == 200 and r.json()["ref"].startswith("upload:")
    uid = r.json()["ref"].split(":")[1]
    assert (tmp_path / "data" / "images" / f"{uid}.png").exists()
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
    assert c.post("/v1/images", files={"file": ("x.png", svg)}, headers=h).status_code == 415


# ---------------------------------------------------------------- planner rules
class ScriptedLLM:
    """Answers each call with the next canned plan and keeps the prompts it was given."""

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def invoke(self, messages):  # the planner's JSON path appends the schema as the last message
        self.prompts.append(messages)
        return json.dumps(self.answers.pop(0))


def with_image(ref):
    p = json.loads(json.dumps(PLAN))
    p["scenes"].insert(
        2,
        {
            "type": "image_caption",
            "nav": "Studio",
            "data": {"image": ref, "caption": "The studio is open from eight to six."},
            "beats": [{"say": "Here is the studio, open from eight to six.", "show": ["image", "caption"]}],
        },
    )
    p.pop("design", None)
    return p


def run(context, llm):
    from kinetry.config import Settings
    from kinetry.design.planner import run_planner_v2

    design = load_plan(PLAN).design
    return run_planner_v2("Some source text about feedback. " * 5, context, design, Settings(), None, llm=llm)


def test_planner_offers_image_scenes_only_with_images():
    llm = ScriptedLLM(with_image("https://x.example/a.png"), {k: v for k, v in PLAN.items() if k != "design"})
    plan = run({"length": "40s"}, llm)
    sys0 = llm.prompts[0][0]["content"]
    assert "No images were provided" in sys0 and "image_caption" not in sys0
    assert "image_caption" in llm.prompts[1][-2]["content"]  # the retry was told the type isn't allowed
    assert "image_caption" not in [s.type for s in plan.scenes]


def test_planner_only_accepts_listed_refs():
    ctx = {"length": "40s", "images": [{"ref": "upload:" + "a" * 32, "about": "the third-floor studio"}]}
    llm = ScriptedLLM(with_image("https://made-up.example/studio.jpg"), with_image("upload:" + "a" * 32))
    plan = run(ctx, llm)
    assert "context.images" in llm.prompts[0][0]["content"] and "image_caption" in llm.prompts[0][0]["content"]
    assert "isn't in context.images" in llm.prompts[1][-2]["content"]
    assert [s.data.get("image") for s in plan.scenes if s.type == "image_caption"] == ["upload:" + "a" * 32]


def test_service_jobs_check_image_refs_at_submit(tmp_path):
    from kinetry.jobs import JobManager
    from kinetry.sources import Source

    jm = JobManager(data_dir=tmp_path / "data")
    for ref, msg in [("/etc/passwd", "must be an https URL"), ("http://127.0.0.1/a.png", "non-public")]:
        src = Source(text="Some source text about the studio. " * 3, context={"images": [ref]})
        with pytest.raises(ValueError, match=msg):
            jm.start(source=src)
