"""Music bed under the narration: bring your own track (a brand's licensed music or any royalty-free file).

The track loops to the video's length, fades in and out, and ducks under the voice with a sidechain
compressor, so speech stays clear without hand-drawn volume curves. Runs after rendering, with FFmpeg.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return float(out.stdout.strip() or 0)


def mix_music(video: Path, music: Path, out: Path | None = None, volume: float = 0.16, duck: bool = True) -> Path:
    """Mix `music` under `video`'s audio; writes `out` (default: replaces `video`)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to mix music")
    if not music.exists():
        raise FileNotFoundError(music)
    total = duration(video)
    fade_out = max(0.0, total - 2.0)
    dest = out or video.with_name(video.stem + ".music" + video.suffix)
    bed = f"[1:a]volume={volume:.3f},afade=t=in:d=1.5,afade=t=out:st={fade_out:.2f}:d=2[bed]"
    if duck:
        graph = (
            f"{bed};[0:a]asplit=2[vo][sc];[bed][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
            "[vo][duck]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        graph = f"{bed};[0:a][bed]amix=inputs=2:duration=first:normalize=0[a]"
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(video),
        "-stream_loop",
        "-1",
        "-i",
        str(music),
        "-filter_complex",
        graph,
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(dest),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if res.returncode != 0 or not dest.exists():
        raise RuntimeError(f"music mix failed: {res.stderr[-500:]}")
    if out is None:
        dest.replace(video)
        return video
    return dest
