"""Inworld voices: request shape, models, long text, WAV handling and the service's voice rules. No network."""

import base64
import io
import json
import wave

import httpx
import pytest

from kinetry.config import Settings
from kinetry.design.plan import load_plan
from kinetry.design.profile import BrandProfile
from kinetry.graph import role_voices
from kinetry.jobs import check_voice
from kinetry.voice import INWORLD_MODELS, InworldProvider, _chunks, build_voice, parse_inworld, wav_duration


def _pcm(seconds: float, rate: int = 24000) -> bytes:
    return b"\x00\x01" * int(seconds * rate)


def _wav(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _client(seen: list, *, header: bool = False) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append({"url": str(req.url), "auth": req.headers.get("authorization"), **body})
        audio = _pcm(0.5)
        return httpx.Response(200, json={"audioContent": base64.b64encode(_wav(audio) if header else audio).decode()})

    return httpx.Client(
        base_url="https://api.inworld.ai",
        headers={"Authorization": "Basic KEY"},
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("model", INWORLD_MODELS)
def test_request_shape_per_model(tmp_path, model):
    seen = []
    clip = InworldProvider("Ashley", model=model, client=_client(seen)).synthesize("Hello there.", tmp_path / "a.wav")
    r = seen[0]
    assert r["url"] == "https://api.inworld.ai/tts/v1/voice" and r["auth"] == "Basic KEY"
    assert r["voiceId"] == "Ashley" and r["modelId"] == model and r["text"] == "Hello there."
    assert r["audioConfig"] == {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}
    assert abs(clip.duration - 0.5) < 0.01 and abs(wav_duration(tmp_path / "a.wav") - 0.5) < 0.01


def test_wav_header_is_stripped_and_long_text_is_split(tmp_path):
    seen = []
    text = ("This sentence is about forty characters. " * 120).strip()  # ~4,900 characters
    clip = InworldProvider("Dennis", client=_client(seen, header=True)).synthesize(text, tmp_path / "b.wav")
    assert len(seen) == 3 and all(len(r["text"]) <= 2000 for r in seen)
    assert " ".join(r["text"] for r in seen) == text
    assert abs(clip.duration - 1.5) < 0.01  # three parts, no stray header bytes counted as audio


def test_chunker_never_loses_text():
    long_word = "x" * 4500
    parts = _chunks(f"Start. {long_word} end.", 2000)
    assert all(0 < len(p) <= 2000 for p in parts) and "".join(parts).replace(" ", "") == f"Start.{long_word}end."


def test_specs_and_models(monkeypatch):
    monkeypatch.setenv("INWORLD_API_KEY", "k")
    assert parse_inworld("Ashley") == ("inworld-tts-2", "Ashley")
    assert parse_inworld("inworld-tts-2-flash:Ashley") == ("inworld-tts-2-flash", "Ashley")
    v = build_voice("inworld:inworld-tts-1:Sarah", Settings())
    assert v.model == "inworld-tts-1" and v.voice == "Sarah"
    with pytest.raises(ValueError, match="unknown Inworld model"):
        build_voice("inworld:inworld-tts-9:Sarah", Settings())


def test_service_rules_for_inworld():
    assert check_voice("inworld:Ashley", "key") and check_voice("inworld:inworld-tts-2-flash:Ashley", "key")
    with pytest.raises(ValueError, match="voice_api_key"):
        check_voice("inworld:Ashley", None, mode="byok")
    with pytest.raises(ValueError, match="model"):
        check_voice("inworld:inworld-tts-9:Ashley", "key")
    with pytest.raises(ValueError):
        check_voice("inworld:../../v1/voices", "key")


def test_dialogue_defaults_follow_the_narrators_model():
    from pathlib import Path

    plan = load_plan(json.loads((Path(__file__).parent.parent / "examples/plans/feedback-that-lands.json").read_text()))
    out = role_voices(plan, {"voice": "inworld:inworld-tts-2-flash:Ashley"}, BrandProfile())
    assert out["a"].startswith("inworld:inworld-tts-2-flash:") and out["b"].startswith("inworld:inworld-tts-2-flash:")
    assert len({out["narrator"], out["a"], out["b"]}) == 3
