"""Voice providers.

Every provider turns one beat of narration into a WAV file and reports its
real duration; the timeline is built from those durations.

- KokoroProvider    : free, local, CPU. Uses `hyperframes tts`.
- VoiceStudioProvider: your self-hosted VoiceStudio backend (OpenAI-compatible
  /v1/audio/speech), plus voice cloning and voice design through its native
  profile API. Clones require a consent recording from the speaker.
- OpenAITTSProvider : OpenAI text-to-speech (gpt-4o-mini-tts etc.), your key.
- ElevenLabsProvider: ElevenLabs voices (including ones you cloned there), your key.
- InworldProvider   : Inworld TTS (inworld-tts-2, inworld-tts-2-flash, inworld-tts-1), built-in
  or cloned voices, your key.

Voices are addressed as "<provider>:<voice>", e.g. "kokoro:af_heart",
"voicestudio:3f9a2c1d" (a VoiceStudio profile id), "openai:coral",
"elevenlabs:<voice_id>", "inworld:Ashley" or "inworld:inworld-tts-2-flash:Ashley" (model first). Platforms with their own TTS pass any object
implementing the VoiceProvider protocol instead.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from .config import Settings

log = logging.getLogger("kinetry")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


@dataclass
class Clip:
    path: Path
    duration: float


class VoiceProvider(Protocol):
    name: str

    def synthesize(self, text: str, out_path: Path) -> Clip: ...


def _cache_key(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


class CachedVoice:
    """Wraps a provider so identical (voice, text) pairs are generated once."""

    def __init__(self, inner: VoiceProvider, cache_dir: Path):
        self.inner = inner
        self.name = inner.name
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def synthesize(self, text: str, out_path: Path) -> Clip:
        inner = self.inner
        key = _cache_key(
            inner.name,
            getattr(inner, "voice", None),
            getattr(inner, "model", None),
            getattr(inner, "speed", None),
            text,
        )
        cached = self.cache_dir / f"{key}.wav"
        if not cached.exists():
            self.inner.synthesize(text, cached)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(cached.read_bytes())
        return Clip(out_path, wav_duration(out_path))


KOKORO_LANGS = {
    "a": "US English",
    "b": "British English",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese (not usable: needs a cloud voice, see KOKORO_CANT_READ)",
    "p": "Brazilian Portuguese",
    "z": "Mandarin Chinese",
}


# Kokoro voice-id prefix -> ISO 639-1 language, and per language: (narrator, dialogue a, dialogue b).
# Some languages have only one or two voices, so speakers may share one.
KOKORO_LANG_OF = {"a": "en", "b": "en", "e": "es", "f": "fr", "h": "hi", "i": "it", "j": "ja", "p": "pt", "z": "zh"}
KOKORO_BY_LANG = {
    "en": ("af_heart", "am_michael", "af_nova"),
    "es": ("ef_dora", "em_alex", "ef_dora"),
    "fr": ("ff_siwis", "ff_siwis", "ff_siwis"),
    "hi": ("hf_alpha", "hm_omega", "hf_beta"),
    "it": ("if_sara", "im_nicola", "if_sara"),
    "pt": ("pf_dora", "pm_alex", "pf_dora"),
    "zh": ("zf_xiaoxiao", "zm_yunxi", "zf_xiaoyi"),
}


# Languages Kokoro has voices for but can't read properly here: its pronunciation step (espeak-ng) reads
# Japanese kanji as the words "Japanese letter" / "Chinese letter". Proper Japanese needs a Japanese reading
# dictionary Kokoro doesn't ship with, so these scripts must use a cloud voice.
KOKORO_CANT_READ = {"ja": "Japanese"}


# Scripts written right to left. Arabic-script languages are also cursive: letter-spacing would break the joins.
RTL_LANGS = {"ar", "fa", "he", "ur", "ps", "sd", "yi", "ug", "ckb", "dv"}
CURSIVE_RTL = {"ar", "fa", "ur", "ps", "sd", "ug", "ckb"}


def is_rtl(lang: str | None) -> bool:
    return lang_code(lang) in RTL_LANGS


def lang_code(lang: str | None) -> str:
    """'pt-BR' -> 'pt', 'zh-Hans' -> 'zh', None -> 'en'."""
    code = (lang or "en").replace("_", "-").split("-")[0].strip().lower()
    return {"cmn": "zh", "jp": "ja"}.get(code, code) or "en"


def kokoro_lang(spec: str) -> str | None:
    """Language of a 'kokoro:<id>' voice, or None for other providers."""
    if not isinstance(spec, str) or not spec.startswith("kokoro:"):
        return None
    vid = spec.split(":", 1)[1]
    return KOKORO_LANG_OF.get(vid[:1])


def kokoro_voices(settings: Settings | None = None) -> list[str]:
    """Voice ids in the installed Kokoro voice pack (a_ = US English, b_ = British, ...; f/m = female/male)."""
    import zipfile

    s = settings or Settings()
    for p in (
        Path.home() / ".cache" / "hyperframes" / "tts" / "voices" / "voices-v1.0.bin",
        s.cache_dir / "voices-v1.0.bin",
    ):
        if p.exists():
            with zipfile.ZipFile(p) as z:
                return sorted(n.removesuffix(".npy") for n in z.namelist())
    return []


class KokoroProvider:
    name = "kokoro"

    def __init__(self, voice: str = "af_heart", speed: float = 0.98, settings: Settings | None = None):
        self.voice, self.speed = voice, speed
        self.settings = settings or Settings()

    def synthesize(self, text: str, out_path: Path) -> Clip:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self.settings.hf_bin() + [
            "tts",
            "-o",
            str(out_path),
            "--voice",
            self.voice,
            "--speed",
            str(self.speed),
            "--json",
            "--",  # the narration is never read as an option, whatever it starts with
            text,
        ]
        cwd = self.settings.tool_dir if self.settings.tool_dir.exists() else None
        res = subprocess.run(cmd, capture_output=True, text=True, env=self.settings.hf_env(), cwd=cwd, timeout=300)
        if res.returncode != 0 or not out_path.exists():
            raise RuntimeError(f"kokoro tts failed: {res.stderr[-400:] or res.stdout[-400:]}")
        return Clip(out_path, wav_duration(out_path))


class VoiceStudioError(RuntimeError):
    pass


class VoiceStudioProvider:
    """Client for a VoiceStudio backend (https://github.com/debpalash/VoiceStudio).

    Contract used (from its backend source, Oct 2026):
      GET  /health
      GET  /v1/audio/voices                      list voices (profiles + aliases)
      POST /v1/audio/speech                      OpenAI-compatible TTS (voice = profile id)
      POST /design/describe                      free text -> design attributes
      POST /profiles  (multipart)                kind=clone (ref_audio) | kind=design (vd_states)
      POST /profiles/{id}/consent (multipart)    consent recording + statement
    Auth: optional `Authorization: Bearer $VOICESTUDIO_API_KEY` (required off-loopback).
    """

    name = "voicestudio"

    def __init__(
        self,
        voice: str = "default",
        *,
        settings: Settings | None = None,
        model: str = "omnivoice",
        speed: float = 1.0,
        instruct: str | None = None,
        seed: int | None = 7,
        client: httpx.Client | None = None,
    ):
        self.settings = settings or Settings()
        self.voice, self.model, self.speed, self.instruct, self.seed = voice, model, speed, instruct, seed
        headers = {"Authorization": f"Bearer {self.settings.voicestudio_key}"} if self.settings.voicestudio_key else {}
        self.http = client or httpx.Client(base_url=self.settings.voicestudio_url, headers=headers, timeout=600)

    # -- helpers ---------------------------------------------------------
    def _ok(self, r: httpx.Response) -> httpx.Response:
        if r.status_code in (401, 403):
            raise VoiceStudioError(f"VoiceStudio auth failed ({r.status_code}); set VOICESTUDIO_API_KEY")
        if r.status_code >= 400:
            raise VoiceStudioError(
                f"VoiceStudio {r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:300]}"
            )
        return r

    def health(self) -> bool:
        try:
            return self.http.get("/health").status_code == 200
        except httpx.HTTPError:
            return False

    def list_voices(self) -> list[dict]:
        data = self._ok(self.http.get("/v1/audio/voices")).json()
        return data.get("voices", data) if isinstance(data, dict) else data

    # -- speech ----------------------------------------------------------
    def synthesize(self, text: str, out_path: Path) -> Clip:
        body = {"model": self.model, "input": text, "voice": self.voice, "response_format": "wav", "speed": self.speed}
        if self.instruct:
            body["instruct"] = self.instruct
        if self.seed is not None:
            body["seed"] = self.seed  # repeatable takes
        r = self._ok(self.http.post("/v1/audio/speech", json=body))
        if not r.content.startswith(b"RIFF"):
            raise VoiceStudioError(f"VoiceStudio returned non-WAV content ({r.headers.get('content-type')})")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(r.content)
        return Clip(out_path, wav_duration(out_path))

    # -- voice design ----------------------------------------------------
    def design_voice(self, name: str, description: str) -> dict:
        """Create a reusable designed voice from a description like
        'warm female, middle-aged, moderate pitch, american accent'."""
        parsed = self._ok(self.http.post("/design/describe", json={"description": description})).json()
        if parsed.get("unmatched"):
            # Not fatal: VoiceStudio only understands a fixed attribute vocabulary.
            parsed.setdefault("warnings", []).append(f"ignored: {parsed['unmatched']}")
        form = {
            "name": name,
            "kind": "design",
            "vd_states": json.dumps(parsed["attrs"]),
            "instruct": parsed.get("instruct", ""),
            "seed": str(self.seed or 42),
        }
        # multipart, like the VoiceStudio UI (the endpoint also accepts optional file parts)
        profile = self._ok(self.http.post("/profiles", files={k: (None, v) for k, v in form.items()})).json()
        return {"profile": profile, "matched": parsed.get("matched", []), "unmatched": parsed.get("unmatched", [])}

    # -- cloning ---------------------------------------------------------
    def clone_voice(
        self,
        name: str,
        reference_audio: Path,
        *,
        consent_audio: Path,
        consent_text: str,
        reference_text: str = "",
        language: str = "Auto",
    ) -> dict:
        """Clone a real person's voice. Requires their recorded consent; the
        consent is stored on the profile in VoiceStudio. If consent upload fails
        the new profile is deleted so no unconsented clone is left behind."""
        if not consent_text.strip():
            raise ValueError("consent_text is required to clone a voice")
        if not consent_audio.exists() or consent_audio.stat().st_size < 2000:
            raise ValueError("consent_audio must be a real recording of the speaker giving consent")
        with reference_audio.open("rb") as ref:
            profile = self._ok(
                self.http.post(
                    "/profiles",
                    data={"name": name, "kind": "clone", "ref_text": reference_text, "language": language},
                    files={"ref_audio": (reference_audio.name, ref, "audio/wav")},
                )
            ).json()
        pid = profile["id"]
        try:
            with consent_audio.open("rb") as c:
                self._ok(
                    self.http.post(
                        f"/profiles/{pid}/consent",
                        data={"consent_text": consent_text},
                        files={"consent_audio": (consent_audio.name, c, "audio/wav")},
                    )
                )
        except Exception:
            self.http.delete(f"/profiles/{pid}")
            raise
        return profile


def _pcm16_to_wav(pcm: bytes, out_path: Path, rate: int) -> None:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    out_path.write_bytes(buf.getvalue())


class OpenAITTSProvider:
    """OpenAI speech (POST /v1/audio/speech). Voices: alloy, ash, ballad, coral, echo, fable, nova,
    onyx, sage, shimmer, verse... `instructions` steers delivery on gpt-4o-mini-tts."""

    name = "openai"

    def __init__(
        self,
        voice: str = "coral",
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini-tts",
        instructions: str | None = "Warm, clear and unhurried, like a good teacher.",
        speed: float = 1.0,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.Client | None = None,
    ):
        self.voice, self.model, self.instructions, self.speed = voice, model, instructions, speed
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key and client is None:
            raise ValueError("openai voice needs an API key (api_key= or OPENAI_API_KEY)")
        self.http = client or httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {key}"}, timeout=300)

    def synthesize(self, text: str, out_path: Path) -> Clip:
        body = {"model": self.model, "voice": self.voice, "input": text, "response_format": "wav", "speed": self.speed}
        if self.instructions and not self.model.startswith("tts-1"):
            body["instructions"] = self.instructions
        r = self.http.post("/audio/speech", json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI TTS {r.status_code}: {r.text[:300]}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if r.content.startswith(b"RIFF"):
            out_path.write_bytes(r.content)
        else:  # some compatible servers stream raw PCM
            _pcm16_to_wav(r.content, out_path, 24000)
        _fix_streamed_wav(out_path)
        return Clip(out_path, wav_duration(out_path))


def _fix_streamed_wav(path: Path) -> None:
    """Streamed WAVs can carry a placeholder data size (0xFFFFFFFF); rewrite the header from the real length."""
    data = path.read_bytes()
    i = data.find(b"data", 12)
    if i == -1:
        return
    declared = int.from_bytes(data[i + 4 : i + 8], "little")
    actual = len(data) - (i + 8)
    if declared != actual:
        fixed = bytearray(data)
        fixed[4:8] = (len(data) - 8).to_bytes(4, "little")
        fixed[i + 4 : i + 8] = actual.to_bytes(4, "little")
        path.write_bytes(bytes(fixed))


class ElevenLabsProvider:
    """ElevenLabs text-to-speech. `voice` is a voice_id from your ElevenLabs library (premade,
    designed, or a voice you cloned there with the speaker's consent)."""

    name = "elevenlabs"
    RATE = 24000

    def __init__(
        self,
        voice: str,
        *,
        api_key: str | None = None,
        model: str = "eleven_multilingual_v2",
        seed: int | None = 7,
        client: httpx.Client | None = None,
    ):
        self.voice, self.model, self.seed = voice, model, seed
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key and client is None:
            raise ValueError("elevenlabs voice needs an API key (api_key= or ELEVENLABS_API_KEY)")
        self.http = client or httpx.Client(
            base_url="https://api.elevenlabs.io", headers={"xi-api-key": key or ""}, timeout=300
        )

    def synthesize(self, text: str, out_path: Path) -> Clip:
        body: dict = {"text": text, "model_id": self.model}
        if self.seed is not None:
            body["seed"] = self.seed
        r = self.http.post(f"/v1/text-to-speech/{self.voice}", params={"output_format": f"pcm_{self.RATE}"}, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"ElevenLabs TTS {r.status_code}: {r.text[:300]}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _pcm16_to_wav(r.content, out_path, self.RATE)
        return Clip(out_path, wav_duration(out_path))


class InworldProvider:
    """Inworld text-to-speech. `voice` is a voice id from Inworld's library or one cloned in your workspace
    (with the speaker's consent); `model` is one of INWORLD_MODELS."""

    name = "inworld"
    RATE = 24000
    MAX_CHARS = 2000  # per request

    def __init__(
        self,
        voice: str,
        *,
        model: str = "inworld-tts-2",
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ):
        if model not in INWORLD_MODELS:
            raise ValueError(f"unknown Inworld model '{model}'; use one of {', '.join(INWORLD_MODELS)}")
        if model in INWORLD_RETIRED:
            log.warning("inworld: %s is retired by Inworld (requests are rerouted to a newer model)", model)
        self.voice, self.model = voice, model
        key = api_key or os.environ.get("INWORLD_API_KEY")
        if not key and client is None:
            raise ValueError("inworld voice needs an API key (api_key= or INWORLD_API_KEY)")
        # Inworld issues keys already base64-encoded for HTTP Basic auth
        self.http = client or httpx.Client(
            base_url="https://api.inworld.ai", headers={"Authorization": f"Basic {key}"}, timeout=300
        )

    def _speak(self, text: str) -> bytes:
        body = {
            "text": text,
            "voiceId": self.voice,
            "modelId": self.model,
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": self.RATE},
        }
        r = self.http.post("/tts/v1/voice", json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Inworld TTS {r.status_code}: {r.text[:300]}")
        audio = base64.b64decode(r.json()["audioContent"])
        if audio.startswith(b"RIFF"):  # LINEAR16 can arrive with a WAV header; keep only the samples
            with wave.open(io.BytesIO(audio), "rb") as w:
                if w.getframerate() != self.RATE or w.getsampwidth() != 2 or w.getnchannels() != 1:
                    raise RuntimeError(f"Inworld returned {w.getframerate()} Hz / {w.getnchannels()} ch audio")
                audio = w.readframes(w.getnframes())
        return audio

    def synthesize(self, text: str, out_path: Path) -> Clip:
        pcm = b"".join(self._speak(part) for part in _chunks(text, self.MAX_CHARS))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _pcm16_to_wav(pcm, out_path, self.RATE)
        return Clip(out_path, wav_duration(out_path))

    def list_voices(self, language: str | None = None) -> list[dict]:
        r = self.http.get("/tts/v1/voices", params={"filter": f"language={language}"} if language else None)
        if r.status_code >= 400:
            raise RuntimeError(f"Inworld voices {r.status_code}: {r.text[:300]}")
        return r.json().get("voices", [])


def _chunks(text: str, limit: int) -> list[str]:
    """Split at sentence ends so each request stays under the provider's limit."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(sent) > limit and cur:  # keep order: flush what we have before splitting a very long sentence
            out.append(cur)
            cur = ""
        while len(sent) > limit:  # one very long sentence: hard split at a space
            cut = sent.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            out.append(sent[:cut])
            sent = sent[cut:].lstrip()
        if cur and len(cur) + 1 + len(sent) > limit:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


INWORLD_MODELS = ("inworld-tts-2", "inworld-tts-2-flash", "inworld-tts-1")
INWORLD_RETIRED = {"inworld-tts-1"}  # discontinued by Inworld on 2026-06-15; still accepted, rerouted by them


def parse_inworld(spec_voice: str) -> tuple[str, str]:
    """'Ashley' -> (inworld-tts-2, Ashley); 'inworld-tts-2-flash:Ashley' -> (inworld-tts-2-flash, Ashley)."""
    model, sep, voice = spec_voice.rpartition(":")
    return (model if sep else "inworld-tts-2"), voice


VOICE_PREFIXES = ("kokoro:", "voicestudio:", "openai:", "elevenlabs:", "inworld:")


def make_voice(
    spec: str | VoiceProvider, settings: Settings, cache_dir: Path, *, api_key: str | None = None
) -> CachedVoice:
    """'kokoro:af_heart' | 'voicestudio:<profile_id>' | 'voicestudio:design=<description>' |
    'openai:<voice>' | 'elevenlabs:<voice_id>', or any object with `name` and
    `synthesize(text, out_path) -> Clip` (bring your own TTS). `api_key` is for the cloud voices
    (default: OPENAI_API_KEY / ELEVENLABS_API_KEY)."""
    if not isinstance(spec, str):
        if not callable(getattr(spec, "synthesize", None)):
            raise TypeError("voice must be a spec string or an object with synthesize(text, out_path) -> Clip")
        return spec if isinstance(spec, CachedVoice) else CachedVoice(spec, cache_dir)
    return CachedVoice(build_voice(spec, settings, api_key=api_key), cache_dir)


def build_voice(spec: str, settings: Settings, *, api_key: str | None = None) -> VoiceProvider:
    """A voice spec -> an (uncached) provider."""
    provider, _, voice = spec.partition(":")
    if provider == "kokoro":
        inner: VoiceProvider = KokoroProvider(voice or "af_heart", settings=settings)
    elif provider == "voicestudio":
        if voice.startswith("design="):
            vs = VoiceStudioProvider(settings=settings)
            created = vs.design_voice(f"kinetry-{_cache_key(voice)[:6]}", voice[len("design=") :])
            vs.voice = created["profile"]["id"]
            inner = vs
        else:
            inner = VoiceStudioProvider(voice or "default", settings=settings)
    elif provider == "openai":
        inner = OpenAITTSProvider(voice or "coral", api_key=api_key)
    elif provider == "elevenlabs":
        if not voice:
            raise ValueError("elevenlabs voice needs a voice id: elevenlabs:<voice_id>")
        inner = ElevenLabsProvider(voice, api_key=api_key)
    elif provider == "inworld":
        model, vid = parse_inworld(voice)
        if not vid:
            raise ValueError("inworld voice needs a voice id: inworld:<voice_id> or inworld:<model>:<voice_id>")
        inner = InworldProvider(vid, model=model, api_key=api_key)
    else:
        raise ValueError(f"unknown voice provider '{provider}' (use one of {', '.join(VOICE_PREFIXES)})")
    return inner
