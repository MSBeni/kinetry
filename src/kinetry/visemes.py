"""Mouth shapes (visemes) for animated characters, timed from each voiced line's own audio.

Classic 2D lip-sync uses a small set of mouth drawings; this module picks one for every moment of a line:

    X  rest (mouth closed, relaxed)       A  closed, lips pressed (m, b, p)
    B  slightly open, teeth (most consonants: t, d, s, n, k, l, r...)
    C  open (e, i, the 'uh' of 'about')   D  wide open (a, ah, ow)
    E  rounded (o, er, aw)                F  puckered (oo, u, w)
    G  upper teeth on the lip (f, v)

Timing comes from the audio: the line's loudness, in 10 ms frames, marks where the voice is actually sounding,
and the line's phonemes are spread over those voiced stretches in order (vowels get more time than
consonants). Quiet frames inside a word close the mouth down a step. The phonemes come from espeak-ng through
`phonemizer` (installed with the local Kokoro voice); without it, shapes follow loudness alone. No speech
recognition and no network: same audio and text in, same cues out.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

FRAME = 0.01  # seconds per analysis frame
MIN_HOLD = 0.05  # shortest time a mouth shape is held (shorter flickers read as noise)

_V = {
    "A": "pbm",
    "G": "fv",
    "F": "uʊw",
    "E": "oɔɒɜɝɚ",
    "D": "ɑaæʌ",
    "C": "eɛiɪəɐ",
}
_VOWELS = set("aeiouɑæʌɔɒɜɝɚəɐɛɪʊ")
_DROP = re.compile(r"[ˈˌːˑ.\-‿͡]")


def _viseme(ph: str) -> str:
    for shape, chars in _V.items():
        if ph[0] in chars:
            return shape
    return "B"


@lru_cache(maxsize=1)
def _phonemizer():
    try:
        import espeakng_loader
        from phonemizer.backend import EspeakBackend
        from phonemizer.backend.espeak.wrapper import EspeakWrapper

        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
        return EspeakBackend("en-us", preserve_punctuation=False, with_stress=False)
    except Exception:  # noqa: BLE001  (optional: shapes then follow loudness alone)
        return None


def phonemes(text: str) -> list[str] | None:
    """IPA phonemes of an English line, one entry per sound (diphthongs kept together), or None."""
    be = _phonemizer()
    if be is None:
        return None
    try:
        ipa = be.phonemize([text], strip=True)[0]
    except Exception:  # noqa: BLE001
        return None
    out: list[str] = []
    for ch in _DROP.sub("", ipa).replace(" ", ""):
        if out and ch in _VOWELS and out[-1][-1] in _VOWELS and len(out[-1]) == 1:
            out[-1] += ch  # a diphthong (aɪ, oʊ, eɪ...) is one mouth movement
        else:
            out.append(ch)
    return out


def _loudness(path: Path) -> list[float]:
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(path), always_2d=True)
    mono = data.mean(axis=1)
    n = max(1, int(sr * FRAME))
    frames = len(mono) // n
    if frames == 0:
        return []
    rms = np.sqrt((mono[: frames * n].reshape(frames, n) ** 2).mean(axis=1))
    peak = float(np.percentile(rms, 98)) or 1.0
    smooth = np.convolve(rms / peak, np.ones(3) / 3, mode="same")
    return [float(min(1.0, v)) for v in smooth]


def mouth_cues(audio: Path, text: str) -> list[tuple[float, str]]:
    """[(seconds from the start of the line, shape)], starting and ending on 'X'."""
    loud = _loudness(audio)
    if not loud:
        return [(0.0, "X")]
    voiced = [v > 0.12 for v in loud]
    seq = phonemes(text)
    shapes: list[str] = []
    if seq:
        weights = [1.7 if p[0] in _VOWELS else 1.0 for p in seq]
        total_w = sum(weights)
        n_voiced = sum(voiced) or 1
        bounds, acc = [], 0.0
        for w in weights:  # where each phoneme ends, in voiced frames
            acc += w
            bounds.append(acc / total_w * n_voiced)
        k = vi = 0
        for i, on in enumerate(voiced):
            if not on:
                shapes.append("X")
                continue
            while k < len(seq) - 1 and vi >= bounds[k]:
                k += 1
            vi += 1
            s = _viseme(seq[k])
            if s in "CDE" and loud[i] < 0.3:  # a quiet vowel opens less
                s = "B"
            shapes.append(s)
    else:  # loudness alone
        shapes = [
            "X" if not on else "D" if v > 0.65 else "C" if v > 0.35 else "B" for v, on in zip(loud, voiced, strict=True)
        ]
    # collapse into cues, dropping shapes held for less than MIN_HOLD
    cues: list[tuple[float, str]] = []
    run_start, cur = 0, shapes[0]
    for i in range(1, len(shapes) + 1):
        if i == len(shapes) or shapes[i] != cur:
            t = round(run_start * FRAME, 3)
            if (i - run_start) * FRAME >= MIN_HOLD or not cues:
                if not cues or cues[-1][1] != cur:
                    cues.append((t, cur))
            if i < len(shapes):
                run_start, cur = i, shapes[i]
    if cues[-1][1] != "X":
        cues.append((round(len(shapes) * FRAME, 3), "X"))
    return cues
