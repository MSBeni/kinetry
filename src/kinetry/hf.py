"""Thin wrappers over the HyperFrames CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import Settings


def _run(settings: Settings, args: list[str], cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        settings.hf_bin() + args, cwd=cwd, env=settings.hf_env(), capture_output=True, text=True, timeout=timeout
    )


def check(project: Path, settings: Settings) -> dict:
    """Run `hyperframes check --json`; returns {'ok': bool, 'errors': [...], 'raw': ...}."""
    res = _run(settings, ["check", "--json"], cwd=project, timeout=600)
    text = res.stdout.strip()
    start = text.find("{")
    try:
        data = json.loads(text[start:]) if start >= 0 else {}
    except json.JSONDecodeError:
        data = {}
    errors = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("severity") == "error" or o.get("level") == "error":
                errors.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    ok = res.returncode == 0 and not errors
    return {"ok": ok, "errors": errors, "returncode": res.returncode, "raw": data or text[-2000:]}


# Output quality presets, as `hyperframes render` flags. HyperFrames' own default ("high" here) encodes at
# CRF 16 without B-frames: near-lossless and about 5 Mbps for flat motion graphics. "standard" trades an
# invisible amount of fidelity for files several times smaller (measured in docs/QUALITY.md).
STANDARD_CRF = 22
QUALITY = {
    "draft": ["--quality", "draft"],  # ultrafast x264, CRF 28: quick previews
    "standard": ["--crf", str(STANDARD_CRF)],
    "high": [],  # HyperFrames' default (CRF 16)
}


def quality_args(quality: str | int | None) -> list[str]:
    """'draft' | 'standard' | 'high' | a CRF number 0-51 (lower is better and bigger)."""
    q = "standard" if quality in (None, "") else quality
    if isinstance(q, str) and q.strip().lower() in QUALITY:
        return list(QUALITY[q.strip().lower()])
    try:
        crf = int(str(q).strip())
    except ValueError:
        raise ValueError(f"quality must be one of {', '.join(QUALITY)} or a CRF number 0-51, not {q!r}") from None
    if not 0 <= crf <= 51:
        raise ValueError("CRF must be between 0 and 51")
    return ["--crf", str(crf)]


def render(project: Path, out_file: Path, settings: Settings, quality: str | int | None = None) -> Path:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    args = quality_args(quality if quality is not None else settings.quality)
    res = _run(
        settings,
        ["render", "--fps", str(settings.fps), *args, "--output", str(out_file.resolve()), "--quiet"],
        cwd=project,
        timeout=3600,
    )
    if res.returncode != 0 or not out_file.exists():
        raise RuntimeError(f"render failed: {(res.stderr or res.stdout)[-800:]}")
    return out_file


def snapshot(project: Path, times: list[float], out_dir: Path, settings: Settings) -> list[Path]:
    at = ",".join(f"{t:.2f}" for t in times)
    _run(settings, ["snapshot", "--at", at, "--no-end", "-o", str(out_dir.resolve())], cwd=project, timeout=600)
    return sorted(out_dir.glob("frame-*.png"))
