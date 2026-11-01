"""Generated media: spending cap, cache, the Google provider (with a fake client), character packs and the
scenes that use them. No network and no spending."""

import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("PIL")
pytest.importorskip("google.genai")
from PIL import Image, ImageDraw  # noqa: E402

from kinetry import load_plan  # noqa: E402
from kinetry.branding import DEFAULT_KIT  # noqa: E402
from kinetry.design.catalog import load_catalog  # noqa: E402
from kinetry.design.icons import Icons  # noqa: E402
from kinetry.design.layout import pick_layouts  # noqa: E402
from kinetry.design.render import RenderInput, write_project  # noqa: E402
from kinetry.images import ImageResolver  # noqa: E402
from kinetry.media import Budget, BudgetExceeded, MediaCache, estimate_image, estimate_video  # noqa: E402
from kinetry.media.base import MediaError  # noqa: E402
from kinetry.media.cast import build_cast, change_box, register  # noqa: E402
from kinetry.media.google import GoogleMedia  # noqa: E402
from kinetry.timing import build_timeline, silent_clips  # noqa: E402

CAT = load_catalog()


def face(mouth: str = "flat", dx: int = 0, dy: int = 0, eyes: bool = True) -> bytes:
    """A stand-in 'cartoon': a face on a plain background; mouth and eyes vary, the whole may be shifted."""
    im = Image.new("RGB", (300, 400), (239, 236, 230))
    d = ImageDraw.Draw(im)
    ox, oy = 150 + dx, 170 + dy
    d.rectangle([ox - 110, oy + 120, ox + 110, 400], fill=(75, 90, 68))  # shoulders
    d.ellipse([ox - 70, oy - 90, ox + 70, oy + 90], fill=(235, 194, 159))
    d.rectangle([ox - 75, oy - 100, ox + 75, oy - 55], fill=(59, 53, 54))  # hair
    if eyes:
        d.ellipse([ox - 35, oy - 15, ox - 20, oy + 5], fill=(20, 20, 30))
        d.ellipse([ox + 20, oy - 15, ox + 35, oy + 5], fill=(20, 20, 30))
    else:
        d.line([ox - 35, oy - 5, ox - 20, oy - 5], fill=(20, 20, 30), width=4)
        d.line([ox + 20, oy - 5, ox + 35, oy - 5], fill=(20, 20, 30), width=4)
    if mouth == "flat":
        d.line([ox - 18, oy + 45, ox + 18, oy + 45], fill=(40, 20, 20), width=5)
    else:
        d.ellipse([ox - 16, oy + 32, ox + 16, oy + 60], fill=(60, 20, 30))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class FakeModels:
    def __init__(self, images, video=b"\x00\x00\x00\x18ftypmp42fake"):
        self.images, self.video, self.calls = list(images), video, []

    def generate_content(self, *, model, contents, config):
        self.calls.append(("image", model))
        data = self.images.pop(0) if self.images else face()
        return NS(candidates=[NS(content=NS(parts=[NS(inline_data=NS(data=data))]))])

    def generate_videos(self, *, model, prompt, image, config):
        self.calls.append(("video", model, config.duration_seconds))
        return NS(done=False, name="op/1", error=None, response=None)


class FakeClient:
    def __init__(self, images=()):
        self.models = FakeModels(images)
        self.polls = 0
        self.operations = NS(get=self._get)

    def _get(self, op):
        self.polls += 1
        if self.polls < 2:
            return op
        vid = NS(video=NS(video_bytes=self.models.video, uri=None))
        return NS(done=True, name=op.name, error=None, response=NS(generated_videos=[vid]))


def test_prices_and_cap():
    assert estimate_image("gemini-2.5-flash-image") == 0.039
    assert estimate_video("veo-3.1-fast-generate-001", 8) == 0.64
    assert estimate_video("veo-3.1-generate-001", 8, "1080p", audio=True) == 3.2
    assert estimate_image("someone-elses-model") is None
    b = Budget(1.0)
    b.charge("a", 0.6)
    with pytest.raises(BudgetExceeded):
        b.charge("b", 0.6)
    with pytest.raises(BudgetExceeded, match="no price known"):
        b.charge("c", None)
    Budget(None).charge("free run", None)  # no cap: unknown prices are allowed


def test_google_image_is_cached_and_capped(tmp_path):
    client = FakeClient([face()])
    g = GoogleMedia(cache=MediaCache(tmp_path), budget=Budget(0.05), client=client, project="p")
    r1 = g.image("a cartoon")
    assert not r1.cached and r1.cost == 0.039 and r1.path.read_bytes()[:4] == b"\x89PNG"
    r2 = g.image("a cartoon")  # same request: free, no call
    assert r2.cached and r2.cost == 0 and len(client.models.calls) == 1
    with pytest.raises(BudgetExceeded):  # a new request would go over the $0.05 cap
        g.image("another cartoon")
    assert len(client.models.calls) == 1, "a refused call is never made"


def test_google_video_polls_until_done(tmp_path):
    client = FakeClient()
    g = GoogleMedia(cache=MediaCache(tmp_path), budget=Budget(2.0), client=client, project="p", sleep=lambda s: None)
    r = g.video("a quiet bedroom at night", seconds=8)
    assert r.path.suffix == ".mp4" and r.cost == 0.64 and client.polls == 2
    with pytest.raises(MediaError, match="4, 6, 8"):
        g.video("x", seconds=5)


def test_register_and_change_box():
    base = Image.open(io.BytesIO(face()))
    moved = Image.open(io.BytesIO(face("open", dx=6, dy=-4)))
    aligned, shift = register(base, moved)
    assert shift == (-6, 4)
    x0, y0, x1, y1 = change_box(base, [aligned], region=(0.25, 0.42, 0.75, 0.80))
    assert x0 < 150 < x1 and y0 < 230 < y1 and (x1 - x0) < 150, "the box hugs the mouth"


def test_cast_pack_needs_consent_and_renders(tmp_path):
    variants = [face()] + [face(dx=2)] * 5 + [face("open", dx=3, dy=-2)] * 7 + [face(eyes=False, dy=1)]
    g = GoogleMedia(cache=MediaCache(tmp_path / "cache"), budget=Budget(5), client=FakeClient(variants), project="p")
    with pytest.raises(MediaError, match="consent"):
        build_cast(face(), tmp_path / "pack", g, consent=False)
    pack = build_cast(face(), tmp_path / "pack", g, consent=True)
    assert set(pack["mouth"]["shapes"]) == set("ABCDEFG") and "happy" in pack["moods"] and pack["consent"]
    assert json.loads((tmp_path / "pack" / "pack.json").read_text())["usd"] == pytest.approx(14 * 0.039)
    base = Image.open(tmp_path / "pack" / "base.png")
    assert base.mode == "RGBA" and base.getpixel((2, 2))[3] == 0, "the plain background is cut out"

    clip = tmp_path / "night.mp4"
    clip.write_bytes((CAT.root / "components" / "clip" / "example.mp4").read_bytes())
    raw = {
        "version": 2,
        "title": "t",
        "design": {"format": "9:16", "effects": {"characters": "subtle", "clips": "subtle"}},
        "scenes": [
            {
                "type": "clip",
                "data": {"video": str(clip), "headline": "2 a.m."},
                "beats": [{"say": "Late.", "show": ["video", "headline"]}],
            },
            {
                "type": "character",
                "data": {
                    "setting": "office",
                    "speakers": {"a": {"name": "You", "sprite": str(tmp_path / "pack")}},
                    "lines": [{"who": "a", "text": "Friday is tight."}],
                },
                "beats": [{"say": "Friday is tight.", "show": ["cast", "lines.0"], "voice": "a"}],
            },
        ],
    }
    plan = load_plan(raw)
    assert CAT.validate_plan(plan) == []
    plan = pick_layouts(plan, CAT)
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("/* gsap */")
    tl = build_timeline(plan, silent_clips(plan), plan.design.pacing)
    ri = RenderInput(
        plan=plan,
        brand=DEFAULT_KIT,
        fonts={},
        timeline=tl,
        catalog=CAT,
        icons=Icons(None),
        images=ImageResolver(base_dir=tmp_path),
    )
    html = write_project(ri, tmp_path / "p", gsap).read_text()
    out = tmp_path / "p"
    assert '<video id="clip-1" src="assets/vid-' in html and 'data-start="0' in html and "muted" in html
    # the clip is hoisted out of its timed scene to the top level (HyperFrames can't time a nested video)
    assert html.index('class="hoisted c-clip') > html.index('id="s2"') and "<!--hoist-->" not in html
    assert 'class="sp-mood sp-happy"' in html and 'class="v v-D"' in html and "sp-blink" in html
    assert html.count('class="sp-mood ') == 6 and html.count('class="v v-') == 7
    assert list((out / "assets").glob("spr-*.png")), "pack files are copied into the project (deduplicated)"


def test_local_media_refused_for_public_only(tmp_path):
    clip = tmp_path / "x.mp4"
    clip.write_bytes(b"x")
    raw = {
        "version": 2,
        "title": "t",
        "design": {"effects": {"clips": "subtle"}},
        "scenes": [
            {"type": "clip", "data": {"video": str(clip)}, "beats": [{"say": "Hi.", "show": ["video"]}]},
            {"type": "clip", "data": {"video": str(clip)}, "beats": [{"say": "Hi.", "show": ["video"]}]},
        ],
    }
    plan = pick_layouts(load_plan(raw), CAT)
    tl = build_timeline(plan, silent_clips(plan), plan.design.pacing)
    gsap = tmp_path / "g.js"
    gsap.write_text("")
    ri = RenderInput(
        plan=plan,
        brand=DEFAULT_KIT,
        fonts={},
        timeline=tl,
        catalog=CAT,
        icons=Icons(None),
        images=ImageResolver(public_only=True),
    )
    with pytest.raises(ValueError, match="local media"):
        write_project(ri, tmp_path / "p", gsap)


def test_paths(tmp_path):
    assert Path(CAT.root / "components" / "clip" / "example.mp4").stat().st_size < 50_000


def test_gemini_omni_video_through_interactions(tmp_path):
    import base64

    calls = []

    class FakeInteractions:
        def __init__(self):
            self.n = 0

        def create(self, **kw):
            calls.append(kw)
            return NS(id="it-1", status="in_progress", output_video=None, usage=None, errors=None)

        def get(self, id):
            self.n += 1
            if self.n < 2:
                return NS(id=id, status="in_progress", output_video=None, usage=None, errors=None)
            usage = NS(output_tokens_by_modality=[NS(modality="video", tokens=46336)])
            vid = NS(data=base64.b64encode(b"\x00\x00\x00\x18ftypmp42omni").decode(), mime_type=None)
            return NS(id=id, status="completed", output_video=vid, usage=usage, errors=None)

    client = NS(interactions=FakeInteractions())
    g = GoogleMedia(cache=MediaCache(tmp_path), budget=Budget(2), client=client, api_key="k", sleep=lambda s: None)
    r = g.video("a quiet bedroom", image=face(), seconds=8)
    assert r.path.read_bytes().endswith(b"omni") and r.cost == 0.808 and r.meta["usd_from_usage"] == 0.8109
    kw = calls[0]
    assert kw["model"] == "gemini-omni-1.1-flash" and kw["response_modalities"] == ["video"]
    assert (
        kw["response_format"]["duration"] == "8s"
        and kw["generation_config"]["video_config"]["task"] == "image_to_video"
    )
    with pytest.raises(MediaError, match="3 to 10"):
        g.video("x", seconds=12)


def test_described_cast_and_recut(tmp_path):
    variants = [face()] + [face(dx=1)] * 13
    g = GoogleMedia(cache=MediaCache(tmp_path / "c"), budget=Budget(5), client=FakeClient(variants), project="p")
    with pytest.raises(MediaError, match="description"):
        build_cast(None, tmp_path / "x", g)
    pack = build_cast(None, tmp_path / "jordan", g, description="a team lead", style_ref=face())
    assert pack["source"] == "described" and set(pack["mouth"]["shapes"]) == set("ABCDEFG")
    # re-cutting from the same base costs nothing: every variant comes from the cache
    g2 = GoogleMedia(cache=MediaCache(tmp_path / "c"), budget=Budget(0.01), client=FakeClient(), project="p")
    raw = sorted((tmp_path / "c").glob("*.png"), key=lambda p: p.stat().st_mtime)[0].read_bytes()
    build_cast(None, tmp_path / "again", g2, base=raw)
    assert g2.budget.spent == 0
