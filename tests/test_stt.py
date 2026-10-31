"""Inworld speech to text (inworld-stt-1): request shape, long recordings, recordings as sources and the
voice check. No network: Inworld is a mock transport; ffmpeg converts real (silent) audio."""

import base64
import io
import json
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import kinetry.graph as g
from kinetry import Kinetry
from kinetry.jobs import JobManager
from kinetry.sources import load_source
from kinetry.stt import InworldSTT, Transcript, check_voice_clips, make_transcriber, similarity
from kinetry.voice import Clip

EX = Path(__file__).parent.parent / "examples"
FEEDBACK = json.loads((EX / "plans" / "feedback-that-lands.json").read_text())
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def _wav(path: Path, seconds: float, rate: int = 24000) -> Path:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    path.write_bytes(buf.getvalue())
    return path


def _client(seen: list, words=("hello", "there")) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append({"url": str(req.url), "auth": req.headers.get("authorization"), **body})
        stamps = [
            {"word": w, "confidence": 0.9, "startTimeMs": 100 + i * 300, "endTimeMs": 300 + i * 300}
            for i, w in enumerate(words)
        ]
        return httpx.Response(
            200,
            json={"transcription": {"transcript": " ".join(words), "isFinal": True, "wordTimestamps": stamps}},
        )

    return httpx.Client(
        base_url="https://api.inworld.ai",
        headers={"Authorization": "Basic test-key"},
        transport=httpx.MockTransport(handler),
    )


@needs_ffmpeg
def test_request_shape(tmp_path):
    seen = []
    t = InworldSTT(client=_client(seen)).transcribe(_wav(tmp_path / "a.wav", 1.0))
    assert t.text == "hello there" and [w.text for w in t.words] == ["hello", "there"]
    assert t.words[0].start == pytest.approx(0.1) and t.words[1].end == pytest.approx(0.6)
    (req,) = seen
    assert req["url"] == "https://api.inworld.ai/stt/v1/transcribe" and req["auth"] == "Basic test-key"
    cfg = req["transcribeConfig"]
    assert cfg["modelId"] == "inworld/inworld-stt-1" and cfg["audioEncoding"] == "MP3"
    assert cfg["sampleRateHertz"] == 16000 and cfg["numberOfChannels"] == 1 and cfg["language"] == "en"
    assert cfg["includeWordTimestamps"] is True
    audio = base64.b64decode(req["audioData"]["content"])
    assert audio[:3] == b"ID3" or audio[0] == 0xFF  # an MP3 stream


@needs_ffmpeg
def test_long_recording_is_sent_in_pieces_with_offsets(tmp_path):
    seen = []
    t = InworldSTT(client=_client(seen, ("hi",)), segment_s=1).transcribe(_wav(tmp_path / "long.wav", 2.5))
    assert len(seen) == 3 and t.text == "hi hi hi"
    assert [w.start for w in t.words] == pytest.approx([0.1, 1.1, 2.1])
    assert t.duration == pytest.approx(2.5, abs=0.05)


def test_errors_and_specs(monkeypatch):
    monkeypatch.delenv("INWORLD_API_KEY", raising=False)
    with pytest.raises(ValueError, match="unknown Inworld STT model"):
        InworldSTT("inworld-stt-9", api_key="k")
    with pytest.raises(ValueError, match="API key"):
        InworldSTT()
    with pytest.raises(ValueError, match="provider"):
        make_transcriber("whisper:large")
    assert make_transcriber("inworld:inworld-stt-1", api_key="k").model == "inworld-stt-1"
    assert make_transcriber("inworld-stt-1", api_key="k", language="es").language == "es"

    class Mine:
        name = "mine"

        def transcribe(self, path):
            return Transcript("x")

    m = Mine()
    assert make_transcriber(m) is m
    with pytest.raises(TypeError):
        make_transcriber(object())


def test_similarity():
    assert similarity("Ask what they need.", "ask what they need") == 1.0
    assert similarity("Don't click the link", "don’t click the link") == 1.0
    assert similarity("Report it in one click", "report it in one") > 0.8
    assert similarity("Report it in one click", "the weather is lovely") < 0.3
    assert similarity("", "") == 1.0


class Echo:
    """Hears back each clip's script, except for clips named in `garble`."""

    name = "echo"

    def __init__(self, scripts: dict, garble=()):
        self.scripts, self.garble = scripts, set(garble)

    def transcribe(self, path):
        p = Path(path).name
        return Transcript("mumble mumble" if p in self.garble else self.scripts[p])


def test_voice_check_flags_garbled_beats():
    beats = [
        SimpleNamespace(index=i, say=s, audio=Path(f"s1-b{i + 1}.wav"))
        for i, s in enumerate(["One two three.", "Four five six."])
    ]
    beats.append(SimpleNamespace(index=2, say="silent", audio=None))  # previews have no audio: skipped
    tl = SimpleNamespace(scenes=[SimpleNamespace(index=0, beats=beats)])
    rows = check_voice_clips(tl, Echo({"s1-b1.wav": "one two three", "s1-b2.wav": ""}, garble={"s1-b2.wav"}))
    assert [(r["beat"], r["ok"]) for r in rows] == [("s1-b1", True), ("s1-b2", False)]
    assert rows[1]["heard"] == "mumble mumble" and rows[1]["said"] == "Four five six."


def test_recording_as_source(tmp_path):
    rec = tmp_path / "town-hall.mp3"
    rec.write_bytes(b"not really audio")

    class Fake:
        name = "fake"

        def transcribe(self, path):
            assert Path(path) == rec
            return Transcript("Welcome everyone. Today we cover the new expense policy.", duration=754.0)

    src = load_source(rec, context={"audience": "managers"}, transcriber=Fake())
    assert src.text.startswith("Welcome everyone") and src.title == "town-hall"
    assert src.context == {
        "audience": "managers",
        "source_kind": "transcript of a recording",
        "recording_minutes": 12.6,
    }
    with pytest.raises(ValueError, match="section"):
        load_source(rec, section=1, transcriber=Fake())

    class Silent(Fake):
        def transcribe(self, path):
            return Transcript("  ")

    with pytest.raises(ValueError, match="no speech"):
        load_source(rec, transcriber=Silent())


def test_pipeline_voice_check_reports_scores(tmp_path, monkeypatch):
    """voice_check=<transcriber> runs after the voice step; results land in Result and report.json."""
    scripts = {}

    def voice_plan(plan, voices, audio_dir):
        rows = []
        for si, s in enumerate(plan.scenes):
            row = []
            for bi, b in enumerate(s.beats):
                name = f"s{si + 1}-b{bi + 1}.wav"
                scripts[name] = b.say
                row.append(Clip(audio_dir / name, 2.0))
            rows.append(row)
        return rows

    class HF:
        check = staticmethod(lambda *a: {"ok": True, "errors": []})
        snapshot = staticmethod(lambda *a: [])

        @staticmethod
        def render(project, out, settings, quality=None):
            Path(out).write_bytes(b"mp4")
            return Path(out)

    monkeypatch.setattr(g, "make_voice", lambda spec, *a, **k: SimpleNamespace(name="fake", spec=spec))
    monkeypatch.setattr(g, "voice_plan", voice_plan)
    monkeypatch.setattr(g, "compose_project", lambda *a, **k: None)
    monkeypatch.setattr(g, "measure", lambda *a, **k: {"fields": [], "stages": []})
    monkeypatch.setattr(g, "hf", HF)
    res = Kinetry(workdir=tmp_path).render(
        FEEDBACK, out=tmp_path / "v.mp4", voice_check=Echo(scripts, garble={"s2-b1.wav"})
    )
    assert res.status == "done", res.error  # a flagged line is reported, not fatal
    assert [r["beat"] for r in res.voice_check if not r["ok"]] == ["s2-b1"]
    assert len(res.voice_check) == len(scripts)
    report = json.loads((res.run_dir / "report.json").read_text())
    assert report["voice_check"] == res.voice_check
    step = next(e for e in report["log"] if e["step"] == "voice_check")
    assert step["flagged"] == ["s2-b1"]


def test_service_voice_check_needs_callers_inworld_key(tmp_path):
    jm = JobManager(data_dir=tmp_path)
    with pytest.raises(ValueError, match="stt_api_key"):
        jm.start(plan=FEEDBACK, voice_check=True)
    with pytest.raises(ValueError, match="stt_api_key"):  # an OpenAI voice key is never sent to Inworld
        jm.start(plan=FEEDBACK, voice="openai:coral", voice_api_key="sk-x", voice_check=True)


@needs_ffmpeg
def test_live_check_round_trip_with_mock_inworld(tmp_path):
    """`kinetry check-inworld` logic against a fake Inworld: auth, cast, 3 TTS models, STT round trip."""
    from kinetry.livecheck import SENTENCE, check_inworld

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if req.url.path == "/tts/v1/voices":
            return httpx.Response(200, json={"voices": [{"voiceId": "Ashley", "languages": ["en"]}]})
        if req.url.path == "/tts/v1/voice":
            pcm = b"\x00\x00" * 24000 * 2
            return httpx.Response(200, json={"audioContent": base64.b64encode(pcm).decode()})
        words = SENTENCE.split()
        return httpx.Response(
            200, json={"transcription": {"transcript": SENTENCE, "wordTimestamps": [{"word": w} for w in words]}}
        )

    client = httpx.Client(base_url="https://api.inworld.ai", transport=httpx.MockTransport(handler))
    cast = tmp_path / "cast.json"
    cast.write_text(
        json.dumps({"characters": [{"id": "a", "voice": "inworld:Ashley"}, {"id": "b", "voice": "inworld:Reed"}]})
    )
    rows = check_inworld(tmp_path / "out", cast_file=cast, client=client)
    assert [r["step"] for r in rows] == [
        "auth",
        "cast",
        "tts:inworld-tts-2",
        "stt:inworld-tts-2",
        "tts:inworld-tts-2-flash",
        "stt:inworld-tts-2-flash",
        "tts:inworld-tts-1",
        "stt:inworld-tts-1",
    ]
    assert [r["ok"] for r in rows] == [True, False] + [True] * 6
    assert "missing: b" in rows[1]["detail"]
    assert seen.count("/stt/v1/transcribe") == 3


def test_live_check_stops_when_auth_fails(tmp_path):
    from kinetry.livecheck import check_inworld

    client = httpx.Client(
        base_url="https://api.inworld.ai", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key"))
    )
    rows = check_inworld(tmp_path, client=client)
    assert len(rows) == 1 and not rows[0]["ok"] and "401" in rows[0]["detail"]


@pytest.mark.parametrize(
    "said,same,different",
    [
        ("まず、送信者のアドレスをよく見てください。", "まず送信者のアドレスをよく見てください", "ぜんぜん違う話です"),
        ("先确认发件人，再点击链接。", "先确认发件人 再点击链接", "今天天气很好"),
        ("हर लॉन्च को चार भूमिकाओं की ज़रूरत होती है।", "हर लॉन्च को चार भूमिकाओं की ज़रूरत होती है", "कुछ और बात"),
        ("قبل از کلیک کردن مکث کنید.", "قبل از کلیک کردن مکث کنید", "هوا امروز خوب است"),
        ("Este vídeo se generó dentro del contenedor.", "este vídeo se generó dentro del contenedor", "otra cosa"),
    ],
)
def test_similarity_works_in_every_script(said, same, different):
    assert similarity(said, same) == 1.0
    assert similarity(said, different) < 0.5


def test_voice_check_listens_in_the_script_language(tmp_path, monkeypatch):
    class Lang(Echo):
        language = "en"

        def transcribe(self, path):
            seen.append(self.language)
            return super().transcribe(path)

    seen = []
    scripts = {}

    def voice_plan(plan, voices, audio_dir):
        out = []
        for si, s in enumerate(plan.scenes):
            row = []
            for bi, b in enumerate(s.beats):
                scripts[f"s{si + 1}-b{bi + 1}.wav"] = b.say
                row.append(Clip(audio_dir / f"s{si + 1}-b{bi + 1}.wav", 2.0))
            out.append(row)
        return out

    class HF:
        check = staticmethod(lambda *a: {"ok": True, "errors": []})
        snapshot = staticmethod(lambda *a: [])

        @staticmethod
        def render(project, out, settings, quality=None):
            Path(out).write_bytes(b"mp4")
            return Path(out)

    monkeypatch.setattr(g, "make_voice", lambda spec, *a, **k: SimpleNamespace(name="fake", spec=spec))
    monkeypatch.setattr(g, "voice_plan", voice_plan)
    monkeypatch.setattr(g, "compose_project", lambda *a, **k: None)
    monkeypatch.setattr(g, "measure", lambda *a, **k: {"fields": [], "stages": []})
    monkeypatch.setattr(g, "hf", HF)
    res = Kinetry(workdir=tmp_path).render(
        FEEDBACK, out=tmp_path / "v.mp4", voice="openai:coral", design={"lang": "es-MX"}, voice_check=Lang(scripts)
    )
    assert res.status == "done" and set(seen) == {"es"}
