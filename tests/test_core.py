import io
import json
import wave
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from kinetry.brand import BrandKit, contrast, enforce, extract_signals, heuristic_kit
from kinetry.config import Settings
from kinetry.fitcheck import find_problems, get_path, plan_repairs, set_path
from kinetry.schema import VideoPlan
from kinetry.sources import load_source, split_sections
from kinetry.timing import FIRST_LEAD, GAP, LEAD, TAIL, build_timeline
from kinetry.voice import Clip, VoiceStudioError, VoiceStudioProvider

FIX = Path(__file__).parent / "fixtures"


def wav_bytes(seconds=0.5, rate=24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def minimal_plan(**over) -> dict:
    p = {
        "title": "T",
        "chrome_left": "L",
        "scenes": [
            {
                "kind": "title",
                "nav": "Welcome",
                "headline": "Hello",
                "beats": [{"say": "Welcome in.", "show": ["headline"]}],
            },
            {
                "kind": "split_list",
                "nav": "Share",
                "headline": "Share",
                "panel_label": "Do",
                "items": ["a", "b"],
                "beats": [{"say": "First.", "show": ["items.0"]}, {"say": "Second.", "show": ["items.1"]}],
            },
            {"kind": "closer", "nav": "Go", "headline": "Go", "beats": [{"say": "Go now.", "show": []}]},
        ],
    }
    p.update(over)
    return p


# ---------------------------------------------------------------- schema
def test_plan_validates():
    plan = VideoPlan.model_validate(minimal_plan())
    assert plan.word_count() == 6


def test_unknown_show_key_rejected():
    bad = minimal_plan()
    bad["scenes"][1]["beats"][0]["show"] = ["items.9"]
    with pytest.raises(ValidationError, match="unknown element key"):
        VideoPlan.model_validate(bad)


def test_duplicate_reveal_rejected():
    bad = minimal_plan()
    bad["scenes"][1]["beats"][1]["show"] = ["items.0"]
    with pytest.raises(ValidationError, match="more than one beat"):
        VideoPlan.model_validate(bad)


def test_must_start_with_title_and_end_with_closer():
    bad = minimal_plan()
    bad["scenes"] = bad["scenes"][1:] + bad["scenes"][:1]
    with pytest.raises(ValidationError):
        VideoPlan.model_validate(bad)


def test_char_limits_enforced():
    bad = minimal_plan()
    bad["scenes"][0]["headline"] = "x" * 61
    with pytest.raises(ValidationError):
        VideoPlan.model_validate(bad)


# ---------------------------------------------------------------- timing
def test_timeline_from_durations(tmp_path):
    plan = VideoPlan.model_validate(minimal_plan())
    clips = [
        [Clip(tmp_path / "a.wav", 2.0)],
        [Clip(tmp_path / "b.wav", 1.0), Clip(tmp_path / "c.wav", 1.5)],
        [Clip(tmp_path / "d.wav", 1.0)],
    ]
    tl = build_timeline(plan, clips)
    s0, s1 = tl.scenes[0], tl.scenes[1]
    assert s0.beats[0].start == FIRST_LEAD
    assert s0.duration == pytest.approx(FIRST_LEAD + 2.0 + TAIL)
    assert s1.start == pytest.approx(s0.end)
    assert s1.beats[1].start == pytest.approx(s1.start + LEAD + 1.0 + GAP)
    assert s1.reveals["items.1"] == pytest.approx(s1.beats[1].start + 0.05)
    assert tl.duration == pytest.approx(sum(s.duration for s in tl.scenes), abs=0.01)


# ---------------------------------------------------------------- brand
def test_enforce_fixes_low_contrast():
    kit = BrandKit(
        name="x",
        background="#ffffff",
        surface="#ffffff",
        ink="#777777",
        muted="#cccccc",
        line="#eeeeee",
        accent="#ffd400",
        accent2="#00e0ff",
        display_font="Inter",
        body_font="Inter",
    )
    fixed, log = enforce(kit)
    assert contrast(fixed.ink, fixed.background) >= 9
    assert contrast(fixed.muted, fixed.background) >= 4.8
    assert contrast(fixed.accent, fixed.background) >= 4.6
    assert log


def test_dark_background_replaced():
    kit = BrandKit(
        name="x",
        background="#101010",
        surface="#202020",
        ink="#ffffff",
        muted="#aaaaaa",
        line="#333333",
        accent="#7c3aed",
        accent2="#22c55e",
        display_font="Inter",
        body_font="Inter",
    )
    fixed, _ = enforce(kit)
    assert contrast(fixed.ink, fixed.background) >= 9


def test_extract_signals_from_html():
    html = (FIX / "fernhill.html").read_text()
    sig = extract_signals(html)
    assert sig["site_name"] == "Fernhill Academy"
    assert sig["css_variables"]["--brand"] == "#0f766e"
    colors = [c for c, _ in sig["brand_colors"]]
    assert "#0f766e" in colors and "#f97316" in colors
    assert "DM Sans" in [f for f, _ in sig["fonts"]] or "DM Sans" in sig["google_fonts"]
    kit = heuristic_kit(sig)
    assert kit.accent in ("#0f766e", "#f97316")


# ---------------------------------------------------------------- fit
def test_find_and_plan_repairs():
    report = {
        "fields": [
            {
                "field": "scenes.1.headline",
                "lines": 4,
                "maxLines": 3,
                "widow": False,
                "overflowX": 0,
                "fontSize": 100,
                "text": "h",
            },
            {
                "field": "scenes.1.items.0",
                "lines": 2,
                "maxLines": 1,
                "widow": True,
                "overflowX": 0,
                "fontSize": 36,
                "text": "i",
            },
            {
                "field": "scenes.2.headline",
                "lines": 2,
                "maxLines": 2,
                "widow": True,
                "overflowX": 0,
                "fontSize": 92,
                "text": "w",
            },
        ],
        "stages": [{"scene": 1, "overflowY": 40}],
    }
    probs = find_problems(report)
    assert {p.field for p in probs} == {"scenes.1.headline", "scenes.1.items.0", "scenes.2.headline"}
    assert next(p for p in probs if p.field == "scenes.1.headline").issue == "stage_overflow"
    fit, rewrite = plan_repairs(probs, {"scenes.2.headline": 2})
    # an overflowing scene shrinks as a whole; field problems shrink the field
    assert fit["scenes.1"] == 1 and fit["scenes.1.items.0"] == 1
    fit2, rewrite2 = plan_repairs(probs[:1], {"scenes.1": 4})
    assert [p.field for p in rewrite2] == ["scenes.1.headline"]  # past the smallest step: rewrite the biggest text
    assert [p.field for p in rewrite] == ["scenes.2.headline"]  # widow already at shrink floor -> rewrite


def test_set_path_on_plan():
    plan = VideoPlan.model_validate(minimal_plan())
    set_path(plan, "scenes.1.items.1", "changed")
    assert get_path(plan, "scenes.1.items.1") == "changed"


# ---------------------------------------------------------------- sources
def test_load_source_sections():
    src = load_source(FIX / "source.md", section=2, context={"audience": "testers"})
    assert src.title == "Part two" and src.text.startswith("Second part")
    assert src.context["all_sections"] == ["Part one", "Part two"]
    assert src.context["document_title"] == "Sample course"
    assert src.context["audience"] == "testers"
    with pytest.raises(ValueError):
        load_source(FIX / "source.md", section=9)


def test_split_sections_and_html(tmp_path):
    assert split_sections("# A\nalpha text\n# B\nbeta text") == [("A", "alpha text"), ("B", "beta text")]
    assert split_sections("# Doc\nintro\n## B\nbeta\n## C\ngamma") == [("B", "beta"), ("C", "gamma")]
    p = tmp_path / "page.html"
    p.write_text("<html><nav>menu</nav><h2>Title</h2><p>Body text that is long enough to count.</p></html>")
    src = load_source(p)
    assert "menu" not in src.text and "Body text" in src.text


# ---------------------------------------------------------------- VoiceStudio (mocked HTTP contract)
class FakeVoiceStudio:
    def __init__(self):
        self.calls = []
        self.profiles = {}

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path))
        if req.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if req.url.path == "/v1/audio/speech":
            body = json.loads(req.content)
            assert body["response_format"] == "wav" and body["input"]
            if body["voice"] == "missing":
                return httpx.Response(404, json={"error": {"message": "voice not found"}})
            return httpx.Response(200, content=wav_bytes(0.75), headers={"content-type": "audio/wav"})
        if req.url.path == "/design/describe":
            return httpx.Response(
                200,
                json={
                    "attrs": {"Gender": "female", "Age": "middle-aged"},
                    "instruct": "female, middle-aged",
                    "matched": [],
                    "unmatched": ["cozy"],
                },
            )
        if req.url.path == "/profiles" and req.method == "POST":
            pid = f"p{len(self.profiles) + 1}"
            self.profiles[pid] = req.content
            return httpx.Response(200, json={"id": pid, "name": "x"})
        if req.url.path.endswith("/consent"):
            return (
                httpx.Response(422, json={"detail": "consent recording is too short"})
                if b"short" in req.content
                else httpx.Response(200, json={"ok": True})
            )
        if req.method == "DELETE":
            self.profiles.pop(req.url.path.split("/")[-1], None)
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture
def vs():
    fake = FakeVoiceStudio()
    client = httpx.Client(base_url="http://vs", transport=httpx.MockTransport(fake.handler))
    return fake, VoiceStudioProvider("p-voice", settings=Settings(), client=client)


def test_voicestudio_speech(vs, tmp_path):
    _, p = vs
    clip = p.synthesize("Hello there.", tmp_path / "o.wav")
    assert clip.duration == pytest.approx(0.75, abs=0.01)


def test_voicestudio_error_surfaces(vs, tmp_path):
    _, p = vs
    p.voice = "missing"
    with pytest.raises(VoiceStudioError, match="404"):
        p.synthesize("x y z", tmp_path / "o.wav")


def test_voicestudio_design(vs):
    fake, p = vs
    out = p.design_voice("Coach", "warm cozy female, middle-aged")
    assert out["profile"]["id"] == "p1"
    assert out["unmatched"] == ["cozy"]
    assert b'name="kind"\r\n\r\ndesign' in fake.profiles["p1"]


def test_voicestudio_clone_requires_and_records_consent(vs, tmp_path):
    fake, p = vs
    ref = tmp_path / "ref.wav"
    ref.write_bytes(wav_bytes(3))
    consent = tmp_path / "consent.wav"
    consent.write_bytes(wav_bytes(2))
    with pytest.raises(ValueError):
        p.clone_voice("Dana", ref, consent_audio=consent, consent_text="  ")
    prof = p.clone_voice(
        "Dana", ref, consent_audio=consent, consent_text="I agree to my voice being cloned for training videos."
    )
    assert prof["id"] in fake.profiles
    assert ("POST", f"/profiles/{prof['id']}/consent") in fake.calls


def test_voicestudio_clone_rolls_back_without_consent(vs, tmp_path):
    fake, p = vs
    ref = tmp_path / "ref.wav"
    ref.write_bytes(wav_bytes(3))
    consent = tmp_path / "consent.wav"
    consent.write_bytes(wav_bytes(1) + b"short")
    with pytest.raises(VoiceStudioError):
        p.clone_voice("Dana", ref, consent_audio=consent, consent_text="I agree.")
    assert fake.profiles == {}  # unconsented clone deleted


def test_probe_signals_and_vivid_fill():
    from kinetry.brand import signals_from_probe

    probe = json.loads((FIX / "fernhill-probe.json").read_text())
    sig = signals_from_probe(probe)
    top = [c for c, _ in sig["brand_colors"][:4]]
    assert "#0f766e" in top and "#f97316" in top and "#0b1f1d" not in top  # dark ink is not an accent
    assert not any(k.startswith("--wp--") for k in sig["css_variables"])
    kit = BrandKit(
        name="n",
        background="#f7f8fb",
        surface="#ffffff",
        ink="#0b1f1d",
        muted="#4a5568",
        line="#e2e5ea",
        accent="#e4572e",
        accent2="#0f766e",
        display_font="Gilroy",
        body_font="Gilroy",
    )
    fixed, _ = enforce(kit)
    assert fixed.accent_fill == "#e4572e"  # shapes keep the vivid brand color
    assert contrast(fixed.accent, fixed.background) >= 4.6  # text uses an accessible shade
    assert contrast(fixed.accent_ink, fixed.accent_fill) >= 4.5


def test_logo_from_probe_prefers_svg():
    from kinetry.probe import logo_from_probe

    name, data = logo_from_probe({"logos": [{"svg": "<svg viewBox='0 0 1 1'></svg>"}]})
    assert name == "logo.svg" and b"xmlns" in data
