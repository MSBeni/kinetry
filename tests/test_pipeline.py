"""The whole LangGraph pipeline with the expensive edges stubbed (voice, Chrome, render), plus the
service's security rules. No Chrome, keys or model calls."""

import json
from pathlib import Path

import pytest

import kinetry.graph as g
from kinetry import BrandPack, BrandProfile, Kinetry, Source
from kinetry.jobs import JobManager, check_llm, check_profile, check_voice
from kinetry.netguard import is_public_ip
from kinetry.voice import Clip

EX = Path(__file__).parent.parent / "examples"
FEEDBACK = json.loads((EX / "plans" / "feedback-that-lands.json").read_text())
KEY = "sk-caller-0123456789"


@pytest.fixture
def stub(monkeypatch):
    seen = {"voices": {}, "keys": set(), "music": []}

    class V:
        name = "fake"

        def __init__(self, spec):
            self.spec = spec

    def make_voice(spec, *a, api_key=None, **k):
        seen["keys"].add(api_key)
        return V(spec)

    def voice_plan(plan, voices, audio_dir):
        seen["voices"] = {r: v.spec for r, v in voices.items()}
        return [[Clip(None, 2.0) for _ in s.beats] for s in plan.scenes]

    class HF:
        @staticmethod
        def check(*a):
            return {"ok": True, "errors": []}

        @staticmethod
        def render(project, out, settings, quality=None):
            Path(out).write_bytes(b"mp4")
            return Path(out)

        @staticmethod
        def snapshot(*a):
            return []

    monkeypatch.setattr(g, "make_voice", make_voice)
    monkeypatch.setattr(g, "voice_plan", voice_plan)
    monkeypatch.setattr(g, "compose_project", lambda *a, **k: None)
    monkeypatch.setattr(g, "measure", lambda *a, **k: {"fields": [], "stages": []})
    monkeypatch.setattr(g, "mix_music", lambda video, music, volume=0.16: seen["music"].append((music.name, volume)))
    monkeypatch.setattr(g, "hf", HF)
    return seen


def test_provided_plan_runs_end_to_end(tmp_path, stub):
    tf = Kinetry(workdir=tmp_path)
    res = tf.render(FEEDBACK, out=tmp_path / "f.mp4", design={"format": "9:16"})
    assert res.status == "done", res.error
    d = res.plan.design
    assert d.style == "editorial" and d.resolved_format() == "9:16" and d.resolved_captions()
    assert all(s.layout in tf.catalog().components[s.type].layouts_for("9:16") for s in res.plan.scenes)
    # dialogue speakers get their own voices, distinct from the narrator
    assert stub["voices"]["narrator"] == "kokoro:af_heart"
    assert stub["voices"]["a"] != stub["voices"]["b"] and "narrator" != stub["voices"]["a"]
    assert stub["music"] == []


def test_voice_precedence_request_plan_profile(tmp_path, stub):
    pack = BrandPack.default()
    pack.profile = BrandProfile(
        voices={"narrator": "kokoro:am_adam", "a": "kokoro:bm_george"}, music=str(tmp_path / "m.mp3")
    )
    tf = Kinetry(workdir=tmp_path)
    tf.render(FEEDBACK, brand=pack, out=tmp_path / "1.mp4")
    assert stub["voices"]["narrator"] == "kokoro:am_adam" and stub["voices"]["a"] == "kokoro:bm_george"
    assert stub["music"] == [("m.mp3", 0.16)]
    tf.render(FEEDBACK, brand=pack, out=tmp_path / "2.mp4", voice="kokoro:bf_emma", voices={"a": "kokoro:am_echo"})
    assert stub["voices"]["narrator"] == "kokoro:bf_emma" and stub["voices"]["a"] == "kokoro:am_echo"


def test_caller_voice_key_reaches_every_voice_and_nothing_else(tmp_path, stub):
    tf = Kinetry(workdir=tmp_path)
    res = tf.render(FEEDBACK, out=tmp_path / "k.mp4", voice="openai:coral", voice_api_key=KEY)
    assert res.status == "done" and stub["keys"] == {KEY}
    assert stub["voices"]["a"] == "openai:onyx"
    assert KEY not in (res.run_dir / "report.json").read_text()


def test_generate_from_replay_with_profile(tmp_path, stub):
    tf = Kinetry(workdir=tmp_path, replay_dir=EX / "replay" / "run-the-room-fernhill")
    src = Source(text="Open the meeting by saying why you called it. " * 4, title="Run the room")
    res = tf.generate(src, out=tmp_path / "r.mp4", design={"format": "1:1"})
    assert res.status == "done", res.error
    assert res.plan.design.style == "classic" and res.plan.design.resolved_format() == "1:1"
    assert res.plan.design.resolved_captions()  # a recorded v1 plan cut for a square feed still gets captions


def test_fit_loop_shrinks_then_rewrites_then_gives_up(tmp_path, stub, monkeypatch):
    from kinetry.fitcheck import Problem

    field = "scenes.0.data.headline"
    monkeypatch.setattr(g, "find_problems", lambda r: [Problem(field, "too_many_lines", "3 > 2", "x")])
    asked = []

    def repair(problems, *a, **k):
        asked.append([p.field for p in problems])
        return type("R", (), {"items": [type("I", (), {"field": "design.format", "text": "4:3"})()]})()

    monkeypatch.setattr(g, "run_repair", repair)
    res = Kinetry(workdir=tmp_path).render(FEEDBACK, out=tmp_path / "x.mp4")
    assert res.status == "needs_review"
    assert asked and asked[0] == [field]  # a rewrite was attempted after the shrink steps ran out
    assert res.plan.design.format != "4:3"  # fields we didn't ask about are never touched


# ---------------------------------------------------------------- service rules
def test_plan_voices_follow_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("KINETRY_VOICE_PROVIDERS", "kokoro")
    jm = JobManager(Kinetry(workdir=tmp_path), data_dir=tmp_path / "d")
    for voices in ({"a": "elevenlabs:x"}, {"a": "kokoro:../../etc"}, {"../x": "kokoro:af_heart"}):
        with pytest.raises(ValueError):
            jm.start(plan={**FEEDBACK, "voices": voices})
    with pytest.raises(ValueError, match="valid video plan"):
        jm.start(plan={"scenes": [None]})


def test_voice_ids_and_keys():
    with pytest.raises(ValueError):
        check_voice("elevenlabs:../../v1/user?x", "k")
    assert check_voice("elevenlabs:21m00Tcm4TlvDq8ikWAM", "k")
    assert check_voice("voicestudio:design=female, calm, british accent")
    with pytest.raises(ValueError, match="voice_api_key"):
        check_voice("openai:onyx", None, mode="byok")


def test_custom_endpoints_need_the_callers_key():
    with pytest.raises(ValueError, match="own api_key"):
        check_llm({"provider": "openai_compatible", "model": "m", "base_url": "https://example.com/v1"}, mode="any")
    with pytest.raises(ValueError, match="base_url"):
        check_llm({"provider": "anthropic", "model": "m", "api_key": KEY, "base_url": "https://x.example.com"})


def test_profile_rules():
    for bad in (
        {"transition": "nope"},
        {"format": "4:3"},
        {"pacing": "fast"},
        {"motion": "x"},
        {"music": "/etc/passwd"},
        {"voices": {"a": "file:/x"}},
    ):
        with pytest.raises(ValueError):
            check_profile(bad)
    assert check_profile({"styles": ["warm"], "transition": "fade", "format": "9:16"}).format == "9:16"


@pytest.mark.parametrize(
    "ip,ok",
    [
        ("8.8.8.8", True),
        ("2606:4700::1", True),
        ("10.0.0.1", False),
        ("100.100.100.200", False),
        ("169.254.169.254", False),
        ("::ffff:127.0.0.1", False),
        ("64:ff9b::7f00:1", False),
        ("2002:7f00:1::", False),
        ("fd00::1", False),
    ],
)
def test_public_ip(ip, ok):
    assert is_public_ip(ip) is ok


def test_redirects_are_rechecked():
    import httpx

    from kinetry.netguard import guard_hook

    with pytest.raises(ValueError, match="non-public"):
        guard_hook(httpx.Request("GET", "http://127.0.0.1/admin"))


def test_public_record_hides_url_credentials():
    from kinetry.llm import LLMConfig

    pub = LLMConfig("openai_compatible", "m", base_url="https://user:pw@api.example.com/v1?api-key=zz").public()
    assert pub["base_url"] == "https://api.example.com/v1"


def test_no_model_for_copy_rewrite_ends_as_needs_review(tmp_path, stub, monkeypatch):
    from kinetry.fitcheck import Problem

    monkeypatch.setattr(
        g, "find_problems", lambda r: [Problem("scenes.0.data.headline", "too_many_lines", "3 > 2", "x")]
    )

    def no_model(*a, **k):
        raise ConnectionError("no model reachable")

    monkeypatch.setattr(g, "run_repair", no_model)
    res = Kinetry(workdir=tmp_path).render(FEEDBACK, out=tmp_path / "x.mp4")
    assert res.status == "needs_review" and res.error is None
