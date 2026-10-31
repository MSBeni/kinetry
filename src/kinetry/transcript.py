"""What was said, when: the finished video's timing, kept next to it for captions, transcripts and chapters.

Every render writes `<run>/timing.json` (the final plan's scenes and beats with their real times, and the
caption cues) and, when it was made from a source, `<run>/source.md`. Packaging (package.py) reads both.
"""

from __future__ import annotations

import json
from pathlib import Path

TIMING_VERSION = 1

# fields that name a scene well, in order of preference (the progress label `nav` is shortest)
_LABEL_FIELDS = ("nav", "headline", "title", "term", "question", "text")


def scene_label(scene) -> str:
    if getattr(scene, "nav", ""):
        return scene.nav
    for k in _LABEL_FIELDS[1:]:
        v = scene.data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return scene.type.replace("_", " ").capitalize()


def speaker_names(scene) -> dict[str, str]:
    """Dialogue speakers' names by role id ('a' -> 'Mateo'); other scenes have none."""
    sp = scene.data.get("speakers") if isinstance(scene.data, dict) else None
    out = {}
    if isinstance(sp, dict):
        for role, who in sp.items():
            if isinstance(who, dict) and who.get("name"):
                out[role] = who["name"]
    return out


def timing_record(plan, tl) -> dict:
    """The final plan on the real timeline, as plain data."""
    from .design.render import caption_cues

    fmt = plan.design.resolved_format()
    scenes = []
    for sc, ts in zip(plan.scenes, tl.scenes, strict=True):
        names = speaker_names(sc)
        scenes.append(
            {
                "index": ts.index,
                "type": sc.type,
                "label": scene_label(sc),
                "start": round(ts.start, 3),
                "end": round(ts.end, 3),
                "beats": [
                    {
                        "start": round(b.start, 3),
                        "end": round(b.start + b.duration, 3),
                        "say": b.say,
                        "caption": b.caption,
                        "voice": b.voice,
                        "speaker": names.get(b.voice, ""),
                    }
                    for b in ts.beats
                ],
            }
        )
    return {
        "version": TIMING_VERSION,
        "title": plan.title,
        "lang": plan.design.lang or "en",
        "format": fmt,
        "duration": tl.duration,
        "burned_captions": bool(plan.design.resolved_captions()),  # captions are drawn into the video itself
        "scenes": scenes,
        "cues": caption_cues(tl, fmt),
    }


def write_timing(run_dir: Path, plan, tl, source_text: str = "") -> Path:
    run_dir = Path(run_dir)
    p = run_dir / "timing.json"
    p.write_text(json.dumps(timing_record(plan, tl), indent=2, ensure_ascii=False), encoding="utf-8")
    if source_text.strip():
        (run_dir / "source.md").write_text(source_text, encoding="utf-8")
    return p


def narration_text(timing: dict) -> str:
    """Everything the video says, in order: the fallback grounding text when there was no source."""
    return "\n".join(b["say"] for s in timing["scenes"] for b in s["beats"])
