"""The design engine without Chrome or a model: catalog, tokens, rendering to HTML, director, layouts."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from kinetry import BrandPack, BrandProfile, Design, load_plan
from kinetry.brand import BrandKit, contrast, enforce
from kinetry.branding import DEFAULT_KIT
from kinetry.design.catalog import load_catalog
from kinetry.design.director import choose_design, constrain, heuristic
from kinetry.design.gallery import example_scenes
from kinetry.design.icons import Icons
from kinetry.design.layout import pick_layouts
from kinetry.design.plan import FORMATS, VideoPlan2
from kinetry.design.render import RenderInput, write_project
from kinetry.design.tokens import build_tokens
from kinetry.timing import build_timeline, silent_clips

ROOT = Path(__file__).parent.parent
PLANS = sorted((ROOT / "examples" / "plans").glob("*.json"))
CAT = load_catalog()

KITS = {
    "default": DEFAULT_KIT,
    "neon": BrandKit(
        name="Neon",
        background="#fffbe6",
        surface="#ffffff",
        ink="#222222",
        muted="#777777",
        line="#eeeeee",
        accent="#ffe600",
        accent2="#00e5ff",
        display_font="Inter",
        body_font="Inter",
    ),
    "dark": BrandKit(
        name="Night",
        background="#0b0b12",
        surface="#15151f",
        ink="#f5f5f5",
        muted="#9a9aa8",
        line="#2a2a36",
        accent="#7c5cff",
        accent2="#ff5c8a",
        display_font="Inter",
        body_font="Inter",
    ),
}


# ---------------------------------------------------------------- catalog
def test_catalog_counts_and_examples_validate():
    n = CAT.combinations()
    assert n["components"] >= 22 and n["styles"] >= 7 and n["transitions"] >= 9 and n["scene_renderings"] >= 800
    for fmt in FORMATS:
        for sc in example_scenes(CAT, fmt):
            assert sc.layout in CAT.components[sc.type].layouts_for(fmt)
            assert CAT.validate_scene(sc, "s") == [], (fmt, sc.type, sc.layout)


def test_catalog_rejects_bad_scenes():
    plan = load_plan(json.loads(PLANS[0].read_text()))
    sc = plan.scenes[0]
    sc.beats[0].show.append("nope")
    assert "nope" in " ".join(CAT.validate_scene(sc, "s0"))
    sc.data["nonsense"] = "x"
    sc.data["headline"] = "word " * 40
    errs = " ".join(CAT.validate_scene(sc, "s0"))
    assert "unknown field" in errs and "headline is 200 wide" in errs


def test_dialogue_needs_speaker_voices():
    sc = next(s for s in example_scenes(CAT, "16:9") if s.type == "dialogue")
    assert CAT.validate_scene(sc, "s0") == []
    sc.beats[0].voice = "b" if sc.beats[0].voice == "a" else "a"
    assert any("that line's speaker" in e for e in CAT.validate_scene(sc, "s0"))


def test_catalog_doc_is_current():
    doc = ROOT / "docs" / "CATALOG.md"
    assert doc.read_text() == CAT.to_markdown() + "\n", "run: kinetry catalog --markdown > docs/CATALOG.md"


@pytest.mark.parametrize("path", PLANS, ids=lambda p: p.stem)
def test_example_plans_validate(path):
    plan = pick_layouts(load_plan(json.loads(path.read_text())), CAT)
    assert CAT.validate_plan(plan) == []
    fmt = plan.design.resolved_format()
    assert all(s.layout in CAT.components[s.type].layouts_for(fmt) for s in plan.scenes)


def test_v1_plans_upgrade():
    for p in (ROOT / "examples" / "replay").glob("*/plan.json"):
        plan = load_plan(json.loads(p.read_text()))
        assert plan.design.style == "classic" and CAT.validate_plan(pick_layouts(plan, CAT)) == []


# ---------------------------------------------------------------- tokens: legible in every style, on every brand
@pytest.mark.parametrize("kit", list(KITS), ids=str)
@pytest.mark.parametrize("style", list(CAT.styles))
def test_tokens_contrast(kit, style):
    k, _ = enforce(KITS[kit])
    tok = build_tokens(k, CAT.styles[style].tokens, "16:9", False)
    for name in ("palette", "inverse_palette"):
        p = tok[name]
        assert contrast(p.ink, p.bg) >= 4.5, (name, p)
        assert contrast(p.muted, p.bg) >= 3, (name, p)
        assert contrast(p.accent, p.bg) >= 3, (name, p)
        assert contrast(p.on_fill, p.fill) >= 3, (name, p)


def test_format_tokens():
    for fmt, (w, h) in {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}.items():
        tok = build_tokens(DEFAULT_KIT, CAT.styles["editorial"].tokens, fmt, True)
        assert tok["size"] == (w, h) and tok["root"]["--W"] == f"{w}px"


# ---------------------------------------------------------------- rendering (HTML only)
def _project(tmp_path, plan, kit=DEFAULT_KIT):
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("/* gsap */")
    tl = build_timeline(plan, silent_clips(plan), plan.design.pacing)
    ri = RenderInput(plan=plan, brand=kit, fonts={}, timeline=tl, catalog=CAT, icons=Icons(None))
    out = write_project(ri, tmp_path / "p", gsap)
    return (out / "index.html").read_text() if out.is_dir() else out.read_text()


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("style", list(CAT.styles))
def test_every_component_renders(tmp_path, style, fmt):
    scenes = example_scenes(CAT, fmt)
    assert {s.type for s in scenes} >= {c for c, comp in CAT.components.items() if not comp.requires}
    for k in range(0, len(scenes), 14):  # every scene type and layout, in projects of up to 14 scenes
        chunk = scenes[k : k + 14] if len(scenes) - k > 1 else scenes[k - 1 :]  # a plan needs 2+ scenes
        plan = VideoPlan2(title="t", design=Design(style=style, format=fmt), scenes=chunk)
        (tmp_path / str(k)).mkdir()
        html = _project(tmp_path / str(k), plan)
        for i, sc in enumerate(plan.scenes):
            assert f'class="clip scene c-{sc.type} l-{sc.layout}' in html
            assert f'data-field="scenes.{i}.' in html, sc.type
        assert f"st-{style}" in html and f"fmt-{fmt.replace(':', 'x')}" in html
        assert "{{" not in html and "None" not in re.sub(r"<script.*?</script>", "", html, flags=re.S)
        assert "TF.run(" in html


def test_character_scene_validates_and_renders(tmp_path):
    shower = {
        "type": "character",
        "layout": "stage",
        "data": {
            "setting": "shower",
            "speakers": {
                "a": {"name": "You", "skin": "tan", "hair": "short", "mood": "annoyed"},
                "b": {"name": "Alex", "role": "In your head", "hair": "bun", "glasses": True, "imagined": True},
            },
            "lines": [
                {"who": "a", "text": "That deadline was never realistic.", "mood": "annoyed"},
                {"who": "b", "text": "Then why didn't you say so?", "mood": "thinking"},
            ],
            "thoughts": [{"who": "a", "text": "Why didn't I?", "mood": "worried"}],
        },
        "beats": [
            {"say": "That deadline was never realistic.", "show": ["cast", "lines.0"], "voice": "a"},
            {"say": "Then why didn't you say so?", "show": ["lines.1"], "voice": "b"},
            {"say": "And you can't stop asking yourself why.", "show": ["thoughts.0"]},
        ],
    }
    raw = {
        "version": 2,
        "title": "t",
        "design": {"format": "9:16", "effects": {"characters": "subtle"}},
        "scenes": [
            {"type": "title", "data": {"headline": "Replaying"}, "beats": [{"say": "Hi.", "show": ["headline"]}]},
            shower,
        ],
    }
    plan = load_plan(raw)
    assert CAT.validate_plan(plan) == []
    # a spoken line must be voiced by its own speaker; thoughts go with the narrator
    bad = json.loads(json.dumps(raw))
    bad["scenes"][1]["beats"][1]["voice"] = "a"
    assert any("lines.1" in e for e in CAT.validate_plan(load_plan(bad)))
    html = _project(tmp_path, pick_layouts(plan, CAT))
    assert "c-character" in html and "who-b imagined" in html and "fx-chr-subtle" in html
    assert 'class="bub box say from-b ln-1"' in html and 'class="bub box think from-a th-0"' in html
    assert '"speak": [["a"' in html  # the speaker windows that drive the mouths


def test_adapted_scene_types_are_credited():
    third = (ROOT / "THIRD_PARTY.md").read_text()
    adapted = {c: comp.adapted_from for c, comp in CAT.components.items() if comp.adapted_from}
    assert {"code_snippet", "chat_thread", "line_chart", "decision"} <= set(adapted)
    for c in adapted:
        assert f"`{c}`" in third, f"{c} is adapted from the HyperFrames registry; credit it in THIRD_PARTY.md"


def test_dialogue_and_captions_render(tmp_path):
    plan = load_plan(json.loads((ROOT / "examples" / "plans" / "feedback-that-lands.json").read_text()))
    plan.design.captions = True
    html = _project(tmp_path, pick_layouts(plan, CAT))
    assert "Priya" in html and 'class="clip caps"' in html.replace("caps ", "caps")


def test_inverse_and_scribble(tmp_path):
    plan = VideoPlan2(
        title="t",
        design=Design(style="warm", format="16:9", transition="scribble"),
        scenes=[s for s in example_scenes(CAT, "16:9") if s.type in ("title", "pull_quote", "closer")],
    )
    plan.scenes[1].layout = "panel"
    html = _project(tmp_path, plan)
    subs = sorted((tmp_path / "p" / "compositions").glob("tf-scribble-*.html"))
    assert " inv" in html and len(subs) == len(plan.scenes) - 1
    a, b = (x.read_text() for x in subs[:2])
    assert '"tf-scribble-0"' in a and 'id="hw-st1-root"' in b and "../" not in a + b


# ---------------------------------------------------------------- director and layouts
def test_heuristic_reads_the_content():
    sec = heuristic("How to spot a phishing email and report it to security.", {}, None)
    assert sec.style == "technical" and "annotated_mock" in sec.prefer_components
    cafe = heuristic("Your first shift as a barista: greet every guest.", {}, None)
    assert cafe.style == "warm" and cafe.format == "9:16" and cafe.captions
    mentor = heuristic("A mentoring session: how to give feedback to your mentee.", {}, None)
    assert mentor.prefer_components[0] == "dialogue" and "big_stat" in mentor.avoid_components


def test_profile_and_overrides_constrain_the_director():
    choice = heuristic("Phishing and password security for every employee.", {}, None)
    prof = BrandProfile(styles=["editorial", "minimal"], format="1:1", avoid_components=["sticky_tip"])
    d = constrain(choice, prof, None, CAT)
    assert d.style in ("editorial", "minimal") and d.format == "1:1"
    d = constrain(choice, prof, Design(style="bold", format="9:16"), CAT)
    assert d.style == "bold" and d.format == "9:16" and d.resolved_captions()  # captions follow the final format


def test_choose_design_without_a_model():
    d, prefer, avoid = choose_design(
        "Open enrollment: compare the two health plans.",
        {},
        kit=DEFAULT_KIT,
        profile=BrandProfile(avoid_components=["dialogue"]),
        use_model=False,
    )
    assert d.style in CAT.styles and "dialogue" in avoid and "dialogue" not in prefer


def test_layout_picker_is_seeded_and_format_aware():
    base = json.loads((ROOT / "examples" / "plans" / "launch-roles.json").read_text())
    a = [s.layout for s in pick_layouts(load_plan(base), CAT).scenes]
    b = [s.layout for s in pick_layouts(load_plan(base), CAT).scenes]
    assert a == b
    seeds = {
        tuple(s.layout for s in pick_layouts(load_plan({**base, "design": {**base["design"], "seed": k}}), CAT).scenes)
        for k in range(12)
    }
    assert len(seeds) > 1
    vertical = load_plan({**base, "design": {"style": "bold", "format": "9:16"}})
    for s in pick_layouts(vertical, CAT).scenes:
        assert s.layout in CAT.components[s.type].layouts_for("9:16")


# ---------------------------------------------------------------- brand profile persistence and jobs
def test_profile_saved_with_brand_pack(tmp_path):
    pack = BrandPack.default()
    pack.profile = BrandProfile(styles=["warm"], voices={"narrator": "kokoro:bf_emma"})
    pack.save(tmp_path / "b")
    assert BrandPack.load(tmp_path / "b").profile == pack.profile


def test_jobs_check_design_and_profile(tmp_path):
    from kinetry.jobs import JobManager, check_design

    assert check_design({"style": "warm", "format": "9:16"}) == {"style": "warm", "format": "9:16"}
    with pytest.raises(ValueError, match="style"):
        check_design({"style": "comic-sans"})
    jm = JobManager(None, data_dir=tmp_path / "data")
    bid = "b1"
    BrandPack.default().save(tmp_path / "data" / "brands" / bid)
    info = jm.set_profile(bid, {"styles": ["minimal"], "avoid_components": ["sticky_tip"]})
    assert info["profile"]["styles"] == ["minimal"]
    for bad in ({"music": "/etc/passwd"}, {"styles": ["nope"]}, {"voices": {"narrator": "file:/x"}}):
        with pytest.raises(ValueError):
            jm.set_profile(bid, bad)


# ---------------------------------------------------------------- music
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_music_mix(tmp_path):
    from kinetry.design.music import duration, mix_music

    def ff(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    video = tmp_path / "v.mp4"
    ff("-f", "lavfi", "-i", "color=c=white:s=320x180:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4",
       "-shortest", "-c:v", "libx264", "-c:a", "aac", str(video))  # fmt: skip
    bed = tmp_path / "bed.wav"
    ff("-f", "lavfi", "-i", "sine=f=110:d=1.5", str(bed))
    out = mix_music(video, bed, tmp_path / "mixed.mp4")
    assert out.exists() and abs(duration(out) - 4) < 0.3


def test_caption_chunks():
    from kinetry.design.render import caption_chunks

    text = "First, greet every guest within five seconds, even when the line is long. Then smile."
    chunks = caption_chunks(text, 8)
    assert " ".join(chunks) == text and all(len(c.split()) <= 10 for c in chunks)
    assert chunks[0].endswith("seconds,") or len(chunks[0].split()) <= 8
    assert caption_chunks("Short line.", 8) == ["Short line."]
    assert all(len(c.split()) >= 3 for c in caption_chunks("one two three four five six seven eight nine", 8))


def test_plan_text_cannot_break_out_of_the_page(tmp_path):
    plan = load_plan(json.loads((ROOT / "examples" / "plans" / "launch-roles.json").read_text()))
    plan.scenes[0].data["headline"] = "</script><script>alert(1)</script>"
    plan.scenes[0].beats[0].show.append("</script><b>")
    html = _project(tmp_path, plan)
    assert "<script>alert" not in html and "</script><b>" not in html


def test_brand_colors_and_fonts_are_sanitized():
    bad = {**DEFAULT_KIT.model_dump(), "background": "#fff</style><script>"}
    with pytest.raises(ValueError):
        BrandKit(**bad)
    with pytest.raises(ValueError):
        BrandKit(**{**DEFAULT_KIT.model_dump(), "display_font": "Inter;}</style>"})
    assert BrandKit(**{**DEFAULT_KIT.model_dump(), "accent": "rgb(10,20,30)"}).accent == "#0a141e"


def test_cross_field_checks():
    sc = next(s for s in example_scenes(CAT, "16:9") if s.type == "bar_chart")
    sc.data["highlight"] = len(sc.data["bars"])
    assert any("highlight" in e for e in CAT.validate_scene(sc, "s"))
    cg = next(s for s in example_scenes(CAT, "16:9") if s.type == "card_grid")
    cg.data.pop("strip_label", None)
    assert any("strip_label" in e for e in CAT.validate_scene(cg, "s"))


def test_highlight_survives_case_changes():
    from kinetry.design.render import _marked

    assert _marked("İstanbul is great", "GREAT") == 'İstanbul is <span class="hl">great</span>'
    assert _marked("no match here", "absent") == "no match here"
