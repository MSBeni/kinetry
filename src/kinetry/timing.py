"""Turn per-beat audio durations into a timeline.

Each beat's narration clip is placed back to back inside its scene; every element listed in
a beat's `show` is revealed the moment that beat starts. Works for v1 and v2 plans (anything
with scenes -> beats -> say/show). Beats can be spoken by different voices (dialogue), and a
silent timeline (estimated durations) powers fast previews and the gallery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .voice import CachedVoice, Clip

LEAD = 0.45  # silence before the first beat of a scene
GAP = 0.22  # breath between beats
TAIL = 0.95  # hold after the last beat before the cut
FIRST_LEAD = 0.8  # a little longer on the opening scene
PACE = {"calm": 1.3, "normal": 1.0, "brisk": 0.75}  # multiplies LEAD/GAP/TAIL


@dataclass
class TimedBeat:
    scene: int
    index: int
    say: str
    audio: Path | None
    start: float  # absolute seconds
    duration: float
    show: list[str]
    voice: str = "narrator"
    caption: str = ""


@dataclass
class TimedScene:
    index: int
    start: float
    duration: float
    beats: list[TimedBeat] = field(default_factory=list)
    reveals: dict[str, float] = field(default_factory=dict)  # element key -> absolute time

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Timeline:
    scenes: list[TimedScene]

    @property
    def duration(self) -> float:
        return round(self.scenes[-1].end, 2) if self.scenes else 0.0


def voice_plan(plan, voice: CachedVoice | dict[str, CachedVoice], audio_dir: Path) -> list[list]:
    """Synthesize every beat; returns clips[scene][beat]. `voice` is one voice or role -> voice."""
    voices = voice if isinstance(voice, dict) else {"narrator": voice}
    clips = []
    for si, scene in enumerate(plan.scenes):
        row = []
        for bi, beat in enumerate(scene.beats):
            role = getattr(beat, "voice", None) or "narrator"
            v = voices.get(role) or voices["narrator"]
            styles = getattr(plan, "voice_styles", None) or {}
            tone = " ".join(x for x in (styles.get(role), getattr(beat, "tone", None)) if x)
            out = audio_dir / f"s{si + 1}-b{bi + 1}.wav"
            row.append(v.synthesize(beat.say, out, tone=tone) if tone else v.synthesize(beat.say, out))
        clips.append(row)
    return clips


def silent_clips(plan, wpm: float = 160.0) -> list[list]:
    """Estimated durations for previews: no audio is generated."""
    return [
        [Clip(None, round(max(1.4, len(b.say.split()) / wpm * 60 + 0.35), 2)) for b in s.beats] for s in plan.scenes
    ]


def build_timeline(plan, clips: list[list], pacing: str = "normal") -> Timeline:
    m = PACE.get(pacing or "normal", 1.0)
    lead, gap, tail, first = LEAD * m, GAP * m, TAIL * m, FIRST_LEAD * m
    t = 0.0
    scenes: list[TimedScene] = []
    for si, scene in enumerate(plan.scenes):
        ts = TimedScene(index=si, start=round(t, 3), duration=0.0)
        cursor = t + (first if si == 0 else lead)
        for bi, (beat, clip) in enumerate(zip(scene.beats, clips[si], strict=True)):
            tb = TimedBeat(
                si,
                bi,
                beat.say,
                clip.path,
                round(cursor, 3),
                round(clip.duration, 3),
                list(beat.show),
                getattr(beat, "voice", None) or "narrator",
                getattr(beat, "caption", None) or beat.say,
            )
            ts.beats.append(tb)
            # several reveals in one beat: spread them across the sentence, in order
            for j, key in enumerate(beat.show):
                ts.reveals[key] = round(cursor + 0.05 + clip.duration * 0.8 * j / len(beat.show), 3)
            cursor += clip.duration + gap
        end = cursor - gap + tail
        ts.duration = round(end - ts.start, 3)
        scenes.append(ts)
        t = end
    return Timeline(scenes)
