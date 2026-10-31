"""Motion layers (camera, kinetic type, ambient light): opt-in, gated, and invisible when off."""

import json
import re
from pathlib import Path

import pytest

from kinetry import BrandProfile, Design
from kinetry.branding import DEFAULT_KIT
from kinetry.design.catalog import load_catalog
from kinetry.design.director import constrain, heuristic
from kinetry.design.gallery import example_scenes
from kinetry.design.icons import Icons
from kinetry.design.layout import pick_layouts
from kinetry.design.plan import Effects, VideoPlan2, load_plan
from kinetry.design.render import RenderInput, write_project
from kinetry.jobs import check_design
from kinetry.timing import build_timeline, silent_clips

ROOT = Path(__file__).parent.parent
CAT = load_catalog()
PHISH = json.loads((ROOT / "examples" / "plans" / "spot-the-phish.json").read_text())


def _html(tmp_path, plan) -> str:
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("")
    tl = build_timeline(plan, silent_clips(plan))
    out = write_project(
        RenderInput(plan=plan, brand=DEFAULT_KIT, fonts={}, timeline=tl, catalog=CAT, icons=Icons(None)),
        tmp_path / "p",
        gsap,
    )
    return (out if out.is_file() else out / "index.html").read_text()


def test_effects_resolve_per_layer():
    e = Effects(level="subtle", ambient="rich", camera="off")
    assert (
        e.resolved()
        == {
            "camera": "off",
            "kinetic": "subtle",
            "ambient": "rich",
            "illustration": "off",  # the heavier layers are only ever on by name
            "depth": "off",
        }
        and e.any()
    )
    assert not Effects().any() and not Effects(level="off").any()
    assert Effects(depth="subtle").any() and Effects(illustration="rich").resolved()["camera"] == "off"


def test_off_leaves_the_page_untouched(tmp_path):
    html = _html(tmp_path, pick_layouts(load_plan(PHISH), CAT))
    for marker in ("fx-cam", 'class="amb', 'class="cam"', "TF.fxAfter = ", '"fx":', '"focus":'):
        assert marker not in html, marker


@pytest.mark.parametrize("level", ["subtle", "rich"])
def test_layers_render(tmp_path, level):
    plan = load_plan({**PHISH, "design": {**PHISH["design"], "effects": {"level": level}}})
    html = _html(tmp_path, pick_layouts(plan, CAT))
    assert f"fx-cam-{level} fx-kin-{level} fx-amb-{level}" in html
    assert html.count('class="cam"') == len(plan.scenes) and html.count('class="amb amb-grid"') == len(plan.scenes)
    assert ('class="pt pt0"' in html) is (level == "rich")
    assert "TF.fxAfter = " in html and '"focus": {"key": "headline"' in html.replace("\\u003c", "<")


def test_layers_can_be_mixed(tmp_path):
    plan = load_plan({**PHISH, "design": {"style": "warm", "effects": {"ambient": "subtle"}}})
    html = _html(tmp_path, pick_layouts(plan, CAT))
    assert "fx-cam-off fx-kin-off fx-amb-subtle" in html and 'class="cam"' not in html and "amb-blobs" in html


def test_statement_scene_gets_beat_windows(tmp_path):
    st = next(s for s in example_scenes(CAT, "16:9") if s.type == "statement")
    title = next(s for s in example_scenes(CAT, "16:9") if s.type == "title")
    plan = VideoPlan2(title="t", design=Design(style="bold", effects={"kinetic": "rich"}), scenes=[title, st])
    html = _html(tmp_path, plan)
    spec = json.loads(html.split("TF.run(")[1].split(");\n</script>")[0])
    w = spec["scenes"][1]["W"]["text"]
    assert w[1] > w[0] and 'class="w hlw"' in html


def test_kinetic_scene_types_are_gated(monkeypatch):
    from kinetry.agents import Recorder  # noqa: F401  (import side effects)
    from kinetry.config import Settings
    from kinetry.design import planner

    seen = {}

    class Model:
        def invoke(self, messages):
            seen["system"] = messages[0]["content"]
            raise RuntimeError("stop")

    monkeypatch.setattr("kinetry.agents.get_llm", lambda *a, **k: Model())
    monkeypatch.setattr("kinetry.llm.invoke_structured", lambda m, schema, msgs, **k: m.invoke(msgs))
    for kinetic, offered in (("off", False), ("subtle", True)):
        with pytest.raises(RuntimeError):
            planner.run_planner_v2(
                "x", {}, Design(effects={"kinetic": kinetic}), Settings(), None, llm=object(), catalog=CAT
            )
        assert ("- statement:" in seen["system"]) is offered


def test_effects_come_from_request_or_profile_never_the_director():
    choice = heuristic("A big product launch announcement for the sales team.", {}, None)
    assert not constrain(choice, None, None, CAT).effects.any()
    prof = BrandProfile(effects=Effects(level="subtle"))
    assert constrain(choice, prof, None, CAT).effects.level == "subtle"
    req = Design(effects=Effects(level="rich", ambient="off"))
    assert constrain(choice, prof, req, CAT).effects.resolved()["ambient"] == "off"


def test_check_design_validates_effects():
    assert check_design({"effects": {"level": "rich"}}) == {"effects": {"level": "rich"}}
    with pytest.raises(ValueError):
        check_design({"effects": {"level": "wild"}})


@pytest.mark.parametrize("level", ["subtle", "rich"])
def test_ambient_light_never_costs_text_its_contrast(level):
    from kinetry.brand import BrandKit, contrast, enforce, mix
    from kinetry.design.render import ambient_light
    from kinetry.design.tokens import build_tokens

    kits = [
        DEFAULT_KIT,
        BrandKit(**{**DEFAULT_KIT.model_dump(), "accent": "#ffe600", "accent2": "#00e5ff", "background": "#fffbe6"}),
        BrandKit(**{**DEFAULT_KIT.model_dump(), "accent": "#7c5cff", "accent2": "#ff5c8a", "background": "#0b0b12"}),
    ]
    for kit in kits:
        k, _ = enforce(kit)
        for style in CAT.styles.values():
            tok = build_tokens(k, style.tokens, "16:9", False)
            for p in (tok["palette"], tok["inverse_palette"]):
                (c1, c2), (a1, a2) = ambient_light(p, level)
                worst = mix(mix(p.bg, c1, a1), c2, a2)
                for t in (p.ink, p.muted, p.accent):
                    base = contrast(t, p.bg)
                    if base >= 4.5:
                        assert contrast(t, worst) >= 4.5, (kit.name, style.id, t)


def _vendor_html(tmp_path, plan, vendor):
    tmp_path.mkdir(parents=True, exist_ok=True)
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("")
    tl = build_timeline(plan, silent_clips(plan), plan.design.pacing)
    ri = RenderInput(plan=plan, brand=DEFAULT_KIT, fonts={}, timeline=tl, catalog=CAT, icons=Icons(None), vendor=vendor)
    out = write_project(ri, tmp_path / "p", gsap)
    return (out if out.is_file() else out / "index.html").read_text()


def _fake_vendor(tmp_path):
    three = tmp_path / "three"
    three.mkdir()
    for f in ("three.module.min.js", "three.core.min.js"):
        (three / f).write_text("// three")
    jsm = tmp_path / "examples" / "jsm"
    for f in ("loaders/SVGLoader.js", "loaders/GLTFLoader.js", "utils/BufferGeometryUtils.js",
              "environments/RoomEnvironment.js"):  # fmt: skip
        (jsm / f).parent.mkdir(parents=True, exist_ok=True)
        (jsm / f).write_text(
            "import { Box2 } from 'three';\nimport { toTrianglesDrawMode } from '../utils/BufferGeometryUtils.js';\n"
        )
    lot = tmp_path / "lottie_light.min.js"
    lot.write_text("// lottie")
    return {"three": three, "lottie": lot}


def test_depth_stage_is_added_only_when_asked(tmp_path):
    plan = pick_layouts(load_plan(PHISH), CAT)
    plan.design.effects = Effects(depth="rich")
    html = _vendor_html(tmp_path, plan, _fake_vendor(tmp_path))
    assert 'id="tf-depth"' in html and "window.TF_DEPTH = " in html and "fx-dep-rich" in html
    assert (tmp_path / "p" / "assets" / "js" / "three.module.min.js").exists()
    assert (tmp_path / "p" / "assets" / "fx" / "depth.mjs").exists()
    spec = json.loads(re.search(r"window.TF_DEPTH = (.*?);</script>", html).group(1))
    assert len(spec["scenes"]) == len(plan.scenes) and spec["level"] == "rich"
    plan.design.effects = Effects(level="rich")  # level alone never turns the 3D stage on
    (tmp_path / "b").mkdir()
    html = _vendor_html(tmp_path / "b", plan, _fake_vendor(tmp_path / "b"))
    assert "tf-depth" not in html and "TF_DEPTH" not in html
    plan.design.effects = Effects(depth="subtle")
    with pytest.raises(RuntimeError, match="kinetry setup"):
        _vendor_html(tmp_path / "c", plan, {})


def test_illustration_scene_with_art_and_lottie(tmp_path):
    from kinetry.design.plan import Design, Scene, VideoPlan2
    from kinetry.images import ImageResolver

    lottie = {"v": "5.7.4", "fr": 30, "ip": 0, "op": 45, "w": 200, "h": 200, "layers": [], "nm": "</script><b>"}
    (tmp_path / "wave.json").write_text(json.dumps(lottie))
    ex = CAT.components["illustration"].example
    scenes = [
        Scene(type="illustration", layout="hero", data=ex, beats=[{"say": "One.", "show": ["art"]}]),
        Scene(type="illustration", layout="side", data={**ex, "animation": "wave.json"}, beats=[{"say": "Two."}]),
    ]
    plan = VideoPlan2(title="t", design=Design(effects={"illustration": "rich"}), scenes=scenes)
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("")
    tl = build_timeline(plan, silent_clips(plan), None)
    ri = RenderInput(
        plan=plan, brand=DEFAULT_KIT, fonts={}, timeline=tl, catalog=CAT, icons=Icons(None),
        images=ImageResolver(base_dir=tmp_path), vendor=_fake_vendor(tmp_path),
    )  # fmt: skip
    out = write_project(ri, tmp_path / "p", gsap)
    html = (out if out.is_file() else out / "index.html").read_text()
    assert '<svg class="art"' in html and "a-pop" in html and "fx-ill-rich" in html
    assert 'data-lottie="lottie-2-1"' in html and '<script type="application/json" id="lottie-2-1">' in html
    assert "</script><b>" not in html and "\\u003c/script" in html  # the file can't close its script tag
    assert "lottie_light.min.js" in html and "delete window.lottie" in html and "TF.lottie = " in html
    # a resolver in service mode won't read a local Lottie
    ri.images = ImageResolver(public_only=True)
    with pytest.raises(ValueError, match="https URL or an upload"):
        write_project(ri, tmp_path / "q", gsap)


def test_lottie_files_are_checked():
    from kinetry.images import ImageError, check_lottie

    ok = {"v": "5", "fr": 30, "ip": 0, "op": 60, "w": 10, "h": 10, "layers": []}
    assert check_lottie(json.dumps(ok).encode())["op"] == 60
    for bad, msg in [
        (b"not json", "isn't a Lottie JSON"),
        (json.dumps({"layers": []}).encode(), "isn't a Lottie animation"),
        (json.dumps({**ok, "fr": 0}).encode(), "out of range"),
        (json.dumps({**ok, "assets": [{"id": "i", "u": "https://x.example/", "p": "a.png"}]}).encode(), "embedded"),
        (b"{" + b" " * (3 * 1024 * 1024) + b"}", "3 MB"),
    ]:
        with pytest.raises(ImageError, match=msg):
            check_lottie(bad)
    embedded = {**ok, "assets": [{"id": "i", "u": "", "p": "data:image/png;base64,AAAA", "e": 1}]}
    assert check_lottie(json.dumps(embedded).encode())


def test_logo_mark_for_the_3d_stage():
    from kinetry.design.depth import logo_mark

    square = b'<svg viewBox="0 0 100 100"><path d="M0 0h10v10z"/></svg>'
    wide = b'<svg viewBox="0 0 400 100"><path d="M0 0h10v10z"/></svg>'
    assert logo_mark(("mark.svg", square), ("logo.svg", wide)) == square.decode()
    assert logo_mark(None, ("logo.svg", square)) == square.decode()  # a square logo works as its own mark
    assert logo_mark(None, ("logo.svg", wide)) is None  # a wordmark doesn't
    assert logo_mark(None, ("logo.png", b"\x89PNG")) is None


def test_depth_spec_carries_hero_scenes_and_mark(tmp_path):
    plan = pick_layouts(load_plan(PHISH), CAT)
    plan.design.effects = Effects(depth="subtle")
    vendor = _fake_vendor(tmp_path)
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("")
    tl = build_timeline(plan, silent_clips(plan), plan.design.pacing)
    mark = ("mark.svg", b'<svg viewBox="0 0 10 10"><path d="M0 0h10v10z"/></svg>')
    ri = RenderInput(
        plan=plan, brand=DEFAULT_KIT, fonts={}, timeline=tl, catalog=CAT, icons=Icons(None), vendor=vendor, mark=mark
    )
    out = write_project(ri, tmp_path / "p", gsap)
    html = (out if out.is_file() else out / "index.html").read_text()
    spec = json.loads(re.search(r"window.TF_DEPTH = (.*?);</script>", html).group(1))
    assert spec["models"] == {} and "<path" in spec["mark"].replace("\\u003c", "<")
    assert [s["id"] for s in spec["scenes"]] == [f"s{i + 1}" for i in range(len(plan.scenes))]
    heroes = [sc.type for s, sc in zip(spec["scenes"], plan.scenes, strict=True) if s["hero"]]
    assert heroes and set(heroes) <= {"title", "closer"}
    for f in ("SVGLoader.js", "GLTFLoader.js", "BufferGeometryUtils.js", "RoomEnvironment.js"):
        js = (tmp_path / "p" / "assets" / "js" / f).read_text()
        assert "from './three.module.min.js';" in js and "from 'three'" not in js
        assert "'../utils/" not in js


def test_brand_pack_keeps_its_mark(tmp_path):
    from kinetry.branding import BrandPack

    p = BrandPack(DEFAULT_KIT.model_copy(), mark=("mark.svg", b"<svg/>"))
    p.save(tmp_path / "b")
    assert BrandPack.load(tmp_path / "b").mark == ("mark.svg", b"<svg/>")
    assert BrandPack.load(tmp_path / "b").logo is None
