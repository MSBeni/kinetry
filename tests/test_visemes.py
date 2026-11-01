import numpy as np
import soundfile as sf

from kinetry.visemes import mouth_cues


def _line(path, pattern):
    """A fake voice: tone bursts (on) and silence (off), 10 ms per entry."""
    sr = 16000
    t = np.arange(int(sr * 0.01)) / sr
    chunk = 0.5 * np.sin(2 * np.pi * 220 * t)
    sf.write(str(path), np.concatenate([chunk if on else np.zeros_like(chunk) for on in pattern]), sr)
    return path


def test_mouth_rests_in_silence_and_moves_while_voiced(tmp_path):
    wav = _line(tmp_path / "l.wav", [0] * 20 + [1] * 60 + [0] * 30 + [1] * 60 + [0] * 20)
    cues = mouth_cues(wav, "Mama, why?")
    assert cues[0] == (0.0, "X") and cues[-1][1] == "X"
    assert all(b[0] > a[0] for a, b in zip(cues, cues[1:], strict=False))  # strictly in time order
    shapes = {s for _, s in cues}
    assert shapes - {"X"}, "the mouth must move while the voice sounds"
    assert any(s == "X" and 0.75 <= t <= 1.15 for t, s in cues), "closed in the pause between words"
    assert cues == mouth_cues(wav, "Mama, why?")  # deterministic


def test_loudness_alone_without_text(tmp_path):
    wav = _line(tmp_path / "l.wav", [0] * 10 + [1] * 50 + [0] * 10)
    cues = mouth_cues(wav, "")
    assert cues[0][1] == "X" and any(s in "BCD" for _, s in cues)
