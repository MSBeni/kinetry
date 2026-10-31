"""Speech to text: recordings in, text out.

Two uses in Kinetry:
- Source content from audio or video (a recorded session, a webinar, a voice memo): transcribe it, then plan.
- Voice check: transcribe each narrated beat and compare it with the script, to catch dropped or garbled words.

Transcribers are addressed like voices, "<provider>:<model>". Today: "inworld:inworld-stt-1" (Inworld's
`inworld/inworld-stt-1`). Any object with `transcribe(path) -> Transcript` works too.
"""

from __future__ import annotations

import base64
import difflib
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".webm", ".mp4", ".mov", ".mkv", ".m4v"}
STT_MODELS = {"inworld-stt-1": "inworld/inworld-stt-1"}
STT_PREFIXES = ("inworld:",)


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Transcript:
    text: str
    words: list[Word] = field(default_factory=list)
    language: str | None = None
    duration: float | None = None


class Transcriber(Protocol):
    name: str

    def transcribe(self, path: Path) -> Transcript: ...


def _seconds(v) -> float:
    """Durations arrive as numbers, '1.25s' strings or {'seconds', 'nanos'} objects."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return float(v.rstrip("s") or 0)
    if isinstance(v, dict):
        return float(v.get("seconds", 0)) + float(v.get("nanos", 0)) / 1e9
    return 0.0


def media_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


class InworldSTT:
    """Inworld speech to text (`inworld-stt-1`), synchronous endpoint.

    Audio is converted to 16 kHz mono MP3 (what the model is tuned for, and small enough for the ~16 MB request
    limit); recordings longer than `segment_s` are sent in pieces and stitched back together with their timing.
    """

    name = "inworld-stt"
    SEGMENT_S = 600

    def __init__(
        self,
        model: str = "inworld-stt-1",
        *,
        language: str | None = "en",
        api_key: str | None = None,
        client: httpx.Client | None = None,
        segment_s: int = SEGMENT_S,
    ):
        if model not in STT_MODELS:
            raise ValueError(f"unknown Inworld STT model '{model}'; use one of {', '.join(STT_MODELS)}")
        self.model, self.language, self.segment_s = model, language, segment_s
        key = api_key or os.environ.get("INWORLD_API_KEY")
        if not key and client is None:
            raise ValueError("inworld speech-to-text needs an API key (api_key= or INWORLD_API_KEY)")
        self.http = client or httpx.Client(
            base_url="https://api.inworld.ai", headers={"Authorization": f"Basic {key}"}, timeout=600
        )

    def _request(self, mp3: bytes) -> dict:
        cfg = {
            "modelId": STT_MODELS[self.model],
            "audioEncoding": "MP3",
            "sampleRateHertz": 16000,
            "numberOfChannels": 1,
            "includeWordTimestamps": True,  # off by default on Inworld
        }
        if self.language:
            cfg["language"] = self.language
        body = {"transcribeConfig": cfg, "audioData": {"content": base64.b64encode(mp3).decode()}}
        r = self.http.post("/stt/v1/transcribe", json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Inworld STT {r.status_code}: {r.text[:300]}")
        return r.json()

    def transcribe(self, path: Path) -> Transcript:
        path = Path(path)
        total = media_duration(path) if shutil.which("ffprobe") else 0.0
        texts: list[str] = []
        words: list[Word] = []
        with tempfile.TemporaryDirectory(prefix="kinetry-stt-") as tmp:
            for offset, mp3 in _segments(path, Path(tmp), self.segment_s, total):
                res = self._request(mp3).get("transcription", {})
                texts.append((res.get("transcript") or "").strip())
                for w in res.get("wordTimestamps") or []:
                    word = w.get("word") or w.get("text") or ""
                    if "startTimeMs" in w:  # Inworld: integer milliseconds
                        start = float(w["startTimeMs"]) / 1000
                        end = float(w.get("endTimeMs", w["startTimeMs"])) / 1000
                    else:
                        start = _seconds(w.get("startTime", w.get("start", 0)))
                        end = _seconds(w.get("endTime", w.get("end", start)))
                    words.append(Word(word, round(offset + start, 3), round(offset + end, 3)))
        return Transcript(" ".join(t for t in texts if t), words, self.language, total or None)


def _segments(path: Path, tmp: Path, segment_s: int, total: float):
    """(offset seconds, 16 kHz mono MP3 bytes) per piece of the recording."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to transcribe audio or video")
    n = max(1, int(-(-total // segment_s))) if total else 1
    for i in range(n):
        out = tmp / f"part{i}.mp3"
        cmd = ["ffmpeg", "-v", "error", "-y"]
        if n > 1:
            cmd += ["-ss", str(i * segment_s), "-t", str(segment_s)]
        cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if res.returncode != 0 or not out.exists():
            raise RuntimeError(f"couldn't read audio from {path.name}: {res.stderr[-300:]}")
        yield i * segment_s, out.read_bytes()


def make_transcriber(spec: str | Transcriber | None, *, api_key: str | None = None, language: str | None = "en"):
    """'inworld:inworld-stt-1' (or just 'inworld-stt-1'), or an object with transcribe(path) -> Transcript.
    None picks Inworld when INWORLD_API_KEY (or api_key) is available."""
    if spec is not None and not isinstance(spec, str):
        if not callable(getattr(spec, "transcribe", None)):
            raise TypeError("transcriber must be a spec string or an object with transcribe(path) -> Transcript")
        return spec
    spec = spec or "inworld:inworld-stt-1"
    provider, _, model = spec.partition(":") if ":" in spec else ("inworld", "", spec)
    if provider != "inworld":
        raise ValueError(f"unknown speech-to-text provider '{provider}' (use inworld:inworld-stt-1)")
    return InworldSTT(model or "inworld-stt-1", api_key=api_key, language=language)


# ---------------------------------------------------------------- voice check
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]")


def _norm(text: str) -> list[str]:
    """Comparable units in any script: words, with punctuation dropped, and single characters for Chinese,
    Japanese and Korean (written without spaces between words). Letters with accents or vowel signs stay whole."""
    t = unicodedata.normalize("NFC", text.lower())
    t = "".join(" " if unicodedata.category(c)[0] in "PSZC" else c for c in t)
    out: list[str] = []
    for w in t.split():
        buf = ""
        for c in w:
            if _CJK.match(c):
                if buf:
                    out.append(buf)
                    buf = ""
                out.append(c)
            else:
                buf += c
        if buf:
            out.append(buf)
    return out


def similarity(expected: str, heard: str) -> float:
    """Word-level match between the script and what was heard (1.0 = identical)."""
    a, b = _norm(expected), _norm(heard)
    if not a and not b:
        return 1.0
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)


def check_voice_clips(timeline, transcriber: Transcriber, threshold: float = 0.8) -> list[dict]:
    """Transcribe every narrated beat and score it against its script; low scores mean the voice dropped,
    garbled or invented words (or a number/acronym it reads differently, worth a listen)."""
    rows = []
    for ts in timeline.scenes:
        for b in ts.beats:
            if b.audio is None:
                continue
            heard = transcriber.transcribe(Path(b.audio)).text
            score = similarity(b.say, heard)
            rows.append(
                {
                    "beat": f"s{ts.index + 1}-b{b.index + 1}",
                    "score": score,
                    "ok": score >= threshold,
                    "said": b.say,
                    "heard": heard,
                }
            )
    return rows
