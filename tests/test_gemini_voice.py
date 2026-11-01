"""Gemini speech: direction goes where each model listens for it, never into the spoken text."""

import base64
import io
import wave
from types import SimpleNamespace

import pytest

from kinetry.voice import CachedVoice, GeminiTTSProvider, build_voice, parse_gemini


def _wav(seconds: float = 0.5, header: bool = True) -> bytes:
    pcm = b"\x00\x01" * int(24000 * seconds)
    if not header:
        return pcm
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    return buf.getvalue()


class FakeInteractions:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(output_audio=SimpleNamespace(data=base64.b64encode(_wav()).decode(), mime_type="audio/wav"))


class FakeModels:
    def __init__(self, fail: int = 0):
        self.calls, self.fail = [], fail

    def generate_content(self, **kw):
        self.calls.append(kw)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("503 overloaded")
        part = SimpleNamespace(inline_data=SimpleNamespace(data=_wav(header=False)))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


def _client(fail: int = 0):
    return SimpleNamespace(interactions=FakeInteractions(), models=FakeModels(fail))


def test_parse_and_build():
    assert parse_gemini("Charon") == ("gemini-3.8-flash-tts", "Charon")
    assert parse_gemini("gemini-2.5-pro-preview-tts:Kore") == ("gemini-2.5-pro-preview-tts", "Kore")
    with pytest.raises(ValueError):
        build_voice("gemini:not-a-model:Kore", settings=None, api_key="k")


def test_38_puts_style_in_metadata_not_text(tmp_path):
    cl = _client()
    p = GeminiTTSProvider("Charon", style="firm psychologist", client=cl)
    clip = p.synthesize("It isn't. It's rumination.", tmp_path / "a.wav", tone="slower")
    call = cl.interactions.calls[0]
    item = call["input"][0]
    assert item["text"] == "It isn't. It's rumination."
    assert item["annotations"][0]["style"] == "firm psychologist; slower"
    assert call["generation_config"] == {"speech_config": [{"voice": "Charon"}]}
    assert abs(clip.duration - 0.5) < 0.01
    assert not cl.models.calls


def test_25_prompt_and_retry(tmp_path):
    cl = _client(fail=1)
    p = GeminiTTSProvider("Kore", model="gemini-2.5-pro-preview-tts", style="calm", client=cl, sleep=lambda s: None)
    clip = p.synthesize("Hello.", tmp_path / "b.wav")
    assert len(cl.models.calls) == 2
    assert "Transcript: Hello." in cl.models.calls[-1]["contents"]
    assert abs(clip.duration - 0.5) < 0.01


def test_cache_keys_direction(tmp_path):
    cl = _client()
    v = CachedVoice(GeminiTTSProvider("Charon", client=cl), tmp_path / "cache")
    v.synthesize("Same words.", tmp_path / "1.wav", tone="quiet")
    v.synthesize("Same words.", tmp_path / "2.wav", tone="quiet")
    v.synthesize("Same words.", tmp_path / "3.wav", tone="firm")
    assert len(cl.interactions.calls) == 2  # a new delivery note is a new take; a repeat is cached


def test_voice_plan_passes_role_style_and_beat_tone(tmp_path):
    from kinetry.design.plan import VideoPlan2
    from kinetry.timing import voice_plan

    plan = VideoPlan2.model_validate(
        {
            "title": "t",
            "voice_styles": {"narrator": "serious"},
            "scenes": [
                {"type": "statement", "data": {}, "beats": [{"say": "One.", "tone": "slow"}, {"say": "Two."}]},
                {"type": "statement", "data": {}, "beats": [{"say": "Three."}]},
            ],
        }
    )
    cl = _client()
    v = CachedVoice(GeminiTTSProvider("Charon", client=cl), tmp_path / "cache")
    voice_plan(plan, {"narrator": v}, tmp_path / "audio")
    styles = [c["input"][0].get("annotations", [{}])[0].get("style") for c in cl.interactions.calls]
    assert styles == ["serious slow", "serious", "serious"]


def test_tighten_trims_edges_and_long_pauses():
    import numpy as np

    from kinetry.voice import tighten_pcm16

    rate = 24000
    tone = (np.sin(np.arange(rate // 2) / 5) * 12000).astype("<i2")
    silence = np.zeros(rate * 2, dtype="<i2")  # 2 s
    pcm = np.concatenate([silence, tone, silence, tone, silence]).tobytes()
    out = np.frombuffer(tighten_pcm16(pcm, rate, max_pause=0.7), dtype="<i2")
    secs = len(out) / rate
    assert 1.0 + 0.7 - 0.05 < secs < 1.0 + 0.7 + 0.2  # two tones, one capped pause, small pads
    short = np.concatenate([tone, np.zeros(rate // 4, dtype="<i2"), tone]).tobytes()
    assert abs(len(tighten_pcm16(short, rate)) / 2 / rate - 1.25) < 0.02  # short pauses stay
