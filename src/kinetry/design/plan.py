"""Video plan v2: generic scenes drawn from the component catalog.

A scene names a component (`type`), optionally one of its layouts, and carries that
component's `data` (validated against its manifest, see catalog.py) plus narration
`beats`. The `design` block records the look: style pack, format, motion, transition,
captions and pacing. Any field left empty is decided by the creative director and the
layout picker, and every decision is written back into the plan so a person can review
or override it.

v1 plans (fixed archetypes, schema.py) are upgraded with `upgrade_v1`, so recorded
plans and stored reviews keep working.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator

from ..textwidth import text_width


def _width(limit: int):
    """Length limit by visual width (CJK characters count 2, combining marks 0), not code points."""

    def check(v: str) -> str:
        if text_width(v) > limit:
            raise ValueError(f"is {text_width(v)} wide; at most {limit} (Chinese/Japanese/Korean characters count 2)")
        return v

    return AfterValidator(check)


def Width(limit: int):  # noqa: N802  (reads like a type)
    return Annotated[str, _width(limit)]


FORMATS = ("16:9", "9:16", "1:1")
Format = Literal["16:9", "9:16", "1:1"]
SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


class Beat(BaseModel):
    say: Width(400) = Field(
        ...,
        min_length=2,
        json_schema_extra={"maxLength": 400},
        description="Narration for this beat: 1-2 plain sentences.",
    )
    show: list[str] = Field(
        default_factory=list,
        description="Element keys revealed when this beat starts, e.g. 'headline', 'items.0'. See each component.",
    )
    voice: str | None = Field(
        None,
        description="Speaker role for this beat ('narrator' if empty). Dialogue lines use the speaker id, e.g. 'a'.",
    )
    caption: str | None = Field(None, description="On-screen caption if it should differ from the narration")


class Scene(BaseModel):
    type: str = Field(..., description="Component id from the catalog")
    layout: str | None = Field(None, description="One of the component's layouts; empty = picked automatically")
    nav: Width(20) = Field("", json_schema_extra={"maxLength": 20}, description="1-3 word label for progress chrome")
    data: dict[str, Any] = Field(default_factory=dict, description="The component's fields")
    beats: list[Beat] = Field(..., min_length=1, max_length=10)


Level = Literal["off", "subtle", "rich"]


class Effects(BaseModel):
    """Optional motion layers on top of a style. All off by default, so plain videos are unchanged.

    `level` sets the first three at once; `camera`, `kinetic` and `ambient` override it one by one.
    - camera:  slow push-ins and parallax depth; rich adds a punch-in on each scene's key moment
    - kinetic: headlines animate word by word; enables the kinetic `statement` scene type
    - ambient: drifting brand-colored light (or a grid, by style) behind every scene
    The next two are heavier and only ever on when asked for by name (`level` doesn't touch them):
    - illustration: enables the `illustration` scene type (animated illustrations, or the caller's Lottie files);
      rich keeps their parts moving gently
    - depth: a 3D stage behind the scenes (Three.js): a camera that travels from scene to scene past the brand's
      own 3D models (where it has shared some), its logo mark and brand-colored shapes; rich adds more movement
    - characters: enables the `character` scene type: animated people who blink, breathe, change expression and
      move their mouths while their own lines are voiced (subtle and rich behave the same for now)
    - clips: enables the `clip` scene type: a generated or supplied video clip (see kinetry.media)
    """

    level: Level = "off"
    camera: Level | None = None
    kinetic: Level | None = None
    ambient: Level | None = None
    illustration: Level = "off"
    depth: Level = "off"
    characters: Level = "off"
    clips: Level = "off"
    # the brand's own 3D models on the stage (see kinetry.brand3d): "auto" lets the asset agent pick per scene,
    # "off" shows none, or {scene number (1 = first): model id} places them by hand
    depth_models: Literal["auto", "off"] | dict[str, str] = "auto"

    def resolved(self) -> dict[str, str]:
        out = {k: getattr(self, k) or self.level for k in ("camera", "kinetic", "ambient")}
        return {
            **out,
            "illustration": self.illustration,
            "depth": self.depth,
            "characters": self.characters,
            "clips": self.clips,
        }

    def any(self) -> bool:
        return any(v != "off" for v in self.resolved().values())


class Design(BaseModel):
    style: str | None = Field(None, description="Style pack id; empty = chosen by the creative director")
    format: Format | None = Field(None, description="16:9 (default), 9:16 for phones, 1:1 for feeds")
    motion: str | None = Field(None, description="Motion pack override; empty = the style's own")
    transition: str | None = Field(None, description="Transition override; empty = the style's own")
    captions: bool | None = Field(None, description="Burn in captions; empty = on for 9:16 and 1:1")
    pacing: Literal["calm", "normal", "brisk"] | None = None
    seed: int = Field(0, description="Changes automatic layout choices without changing content")
    lang: str = Field("en", max_length=12, description="Language of the narration and on-screen text")
    rationale: str = Field("", max_length=600, description="Why this look (written by the director)")
    effects: Effects = Field(default_factory=Effects, description="Optional motion layers (off by default)")

    def resolved_format(self) -> str:
        return self.format or "16:9"

    def resolved_captions(self) -> bool:
        return self.captions if self.captions is not None else self.resolved_format() != "16:9"


class VideoPlan2(BaseModel):
    version: Literal[2] = 2
    title: Width(90) = Field(..., json_schema_extra={"maxLength": 90})
    chrome_left: Width(40) = Field(
        "", json_schema_extra={"maxLength": 40}, description="Small top label, e.g. 'Onboarding · Week 2'"
    )
    chrome_right: Width(30) = Field(
        "", json_schema_extra={"maxLength": 30}, description="Small top-right label, e.g. 'New managers'"
    )
    design: Design = Field(default_factory=Design)
    voices: dict[str, str] = Field(
        default_factory=dict, description="Speaker role -> voice spec, e.g. {'a': 'kokoro:am_michael'}"
    )
    scenes: list[Scene] = Field(..., min_length=2, max_length=14)

    @field_validator("voices")
    @classmethod
    def _voice_roles(cls, v: dict[str, str]) -> dict[str, str]:
        for role in v:
            if not role.replace("_", "").isalnum():
                raise ValueError(f"bad voice role '{role}'")
        return v

    def word_count(self) -> int:
        return sum(len(b.say.split()) for s in self.scenes for b in s.beats)

    def roles(self) -> set[str]:
        return {b.voice or "narrator" for s in self.scenes for b in s.beats}


# ---------------------------------------------------------------- v1 -> v2
def upgrade_v1(plan) -> VideoPlan2:
    """A v1 VideoPlan (fixed archetypes) -> v2. The six archetypes are catalog components
    with the same field names and reveal keys, so this is a lossless re-shape."""
    scenes = []
    for sc in plan.scenes:
        raw = sc.model_dump()
        kind = raw.pop("kind")
        nav = raw.pop("nav", "")
        beats = raw.pop("beats")
        raw = {k: v for k, v in raw.items() if v not in ("", None, [], {})}  # v1 defaults for unused fields
        if kind == "card_grid":
            raw["cards"] = [dict(c) for c in raw["cards"]]
        scenes.append(Scene(type=kind, nav=nav, data=raw, beats=[Beat(**b) for b in beats]))
    return VideoPlan2(
        title=plan.title,
        chrome_left=plan.chrome_left,
        chrome_right=plan.chrome_right,
        # the classic look; format and captions stay open so a v1 plan can still be cut for phones
        design=Design(style="classic", transition="exit"),
        scenes=scenes,
    )


def load_plan(obj: dict | BaseModel) -> VideoPlan2:
    """Accept a v2 plan, a v1 plan, or their JSON dicts."""
    if isinstance(obj, VideoPlan2):
        return obj
    if isinstance(obj, BaseModel):  # a v1 VideoPlan instance
        return upgrade_v1(obj)
    if obj.get("version") == 2 or (obj.get("scenes") and "type" in obj["scenes"][0]):
        return VideoPlan2.model_validate(obj)
    from ..schema import VideoPlan

    return upgrade_v1(VideoPlan.model_validate(obj))
