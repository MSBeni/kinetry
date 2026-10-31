"""The creative director: one decision per video about how it should look.

Given the content, the audience, the brand and the brand's profile, it picks a style pack,
format, transition, pacing and captions, and which scene types to favor or avoid. One LLM
call when a model is available; a transparent keyword heuristic otherwise (and in replay
runs without a recording). Explicit choices from the request always win, then the profile.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from ..brand import BrandKit
from .catalog import Catalog, load_catalog
from .plan import Design
from .profile import BrandProfile

log = logging.getLogger("kinetry")


class DesignChoice(BaseModel):
    style: str = Field(..., description="Style pack id")
    format: Literal["16:9", "9:16", "1:1"] = "16:9"
    transition: str | None = Field(None, description="Transition id, or empty for the style's own")
    pacing: Literal["calm", "normal", "brisk"] = "normal"
    captions: bool | None = None
    prefer_components: list[str] = Field(default_factory=list, description="Scene types that suit this content")
    avoid_components: list[str] = Field(default_factory=list, description="Scene types that don't")
    rationale: str = Field("", max_length=500, description="2-3 sentences: why this look for this content and audience")


DIRECTOR_SYSTEM = """You are the creative director for short narrated videos made from learning and business content.
Pick ONE look that fits the content, the audience and the brand. Return a DesignChoice.

Styles:
{styles}

Transitions: {transitions}
Formats: 16:9 (default, desktops and LMS players), 9:16 (phones, frontline staff, social), 1:1 (feeds, small embeds).

Guidance:
- Match the style to the subject and audience first, the brand's tone second.
- Choose 9:16 only when the audience watches on phones (frontline, retail, field, social) or the request says so.
- Captions: on for 9:16 and 1:1 (sound-off viewing); optional for 16:9.
- pacing: calm for reflective or sensitive topics, brisk for short punchy clips, otherwise normal.
- prefer_components: scene types whose shape fits this content (e.g. dialogue for mentoring or role-play,
  annotated_mock for spot-the-problem, big_stat/bar_chart only if the source has numbers).
- Respect the brand profile's constraints exactly.
"""

# word-start matches ("secur" -> security, securing); whole words where a prefix would mislead ("api" vs "capital")
KEYWORDS = {
    "technical": r"\b(?:secur|phish|password|cyber|complian|software|apis?\b|data\b|engineer|incident|malware|it support|privacy)",
    "warm": r"\b(?:barista|caf[eé]|coffee|restaurant|retail|guests?\b|hospitality|frontline|crew|kitchen|welcome)",
    "bold": r"\b(?:launch|announc|campaign|sales\b|kick-?off|promo|new product|big news|celebrat)",
    "minimal": r"\b(?:health|patient|clinic|wellbeing|well-being|benefits?\b|care\b|caring|nurs(?:e|es|ing)\b|medical|mindful)",
    "corporate": r"\b(?:financ|quarterly|capital markets|operations|enterprise|clients?\b|procurement|audit|polic(?:y|ies)\b|process|governance)",
    "editorial": r"\b(?:course|program|mentor|leadership|session|module|learning|reflect|coach|career)",
}
TONE = {
    "playful": "warm",
    "warm": "warm",
    "bold": "bold",
    "energetic": "bold",
    "calm": "minimal",
    "corporate": "corporate",
    "confident": "editorial",
    "technical": "technical",
    "friendly": "warm",
}
PREFER = {
    "technical": ["annotated_mock", "numbered_steps", "do_dont", "big_stat"],
    "warm": ["steps_path", "instead_try", "sticky_tip", "icon_grid"],
    "bold": ["big_stat", "chapter", "pull_quote", "icon_grid"],
    "minimal": ["definition", "checklist", "pull_quote", "numbered_steps"],
    "corporate": ["comparison", "agenda_timeline", "icon_grid", "bar_chart"],
    "editorial": ["pull_quote", "agenda_timeline", "dialogue", "checklist"],
}


def heuristic(text: str, context: dict, kit: BrandKit | None) -> DesignChoice:
    blob = (text + " " + json.dumps(context, default=str)).lower()
    scores = {s: len(re.findall(rx, blob)) for s, rx in KEYWORDS.items()}
    tone = TONE.get((kit.tone if kit else "").split(",")[0].strip().lower())
    if tone:
        scores[tone] = scores.get(tone, 0) + 1.5
    style = max(scores, key=lambda s: (scores[s], s == "editorial")) if any(scores.values()) else "editorial"
    # vertical only on clear phone cues; words like "shift" or "social" alone are too ambiguous
    mobile = re.search(
        r"\b(?:phones?|mobile|frontline|vertical|tiktok|reels?|instagram|baristas?|cashiers?|crew|warehouse|"
        r"store (?:staff|associates|team)|field (?:staff|team|workers))\b",
        blob,
    )
    fmt = context.get("format") if context.get("format") in ("16:9", "9:16", "1:1") else ("9:16" if mobile else "16:9")
    prefer = list(PREFER.get(style, []))
    if re.search(r"mentor|mentee|role.?play|conversation|coach|feedback", blob):
        prefer.insert(0, "dialogue")
    avoid = [] if re.search(r"\d", text) else ["big_stat", "bar_chart"]
    return DesignChoice(
        style=style,
        format=fmt,
        pacing="calm" if style == "minimal" else "normal",
        captions=fmt != "16:9",
        prefer_components=prefer,
        avoid_components=avoid,
        rationale=f"Keyword match on the content and brand tone ({style}).",
    )


def constrain(choice: DesignChoice, profile: BrandProfile | None, overrides: Design | None, cat: Catalog) -> Design:
    """Choice -> Design, applying the profile and then explicit overrides; drops anything unknown."""
    p = profile or BrandProfile()
    o = overrides or Design()
    allowed = [s for s in (p.styles or list(cat.styles)) if s in cat.styles] or list(cat.styles)
    style = o.style or p.style or (choice.style if choice.style in allowed else allowed[0])
    transition = o.transition or p.transition or (choice.transition if choice.transition in cat.transitions else None)
    motion = o.motion or p.motion
    fmt = o.format or (p.format if p.format in ("16:9", "9:16", "1:1") else None) or choice.format
    # the director's caption call was made for its own format; for another format, fall back to the default
    cap_choice = choice.captions if fmt == choice.format else None
    d = Design(
        style=style if style in cat.styles else "editorial",
        format=fmt,
        motion=motion if motion in cat.motions else None,
        transition=transition,
        captions=o.captions if o.captions is not None else (p.captions if p.captions is not None else cap_choice),
        pacing=o.pacing or (p.pacing if p.pacing in ("calm", "normal", "brisk") else None) or choice.pacing,
        seed=o.seed,
        lang=o.lang,
        # motion layers are opt-in: the request, else the brand profile; never switched on by the director
        effects=o.effects if o.effects.model_dump(exclude_defaults=True) else (p.effects or o.effects),
        rationale=choice.rationale,
    )
    return d


def choose_design(
    source_text: str,
    context: dict,
    *,
    kit: BrandKit | None = None,
    profile: BrandProfile | None = None,
    overrides: Design | None = None,
    llm=None,
    settings=None,
    rec=None,
    catalog: Catalog | None = None,
    use_model: bool = True,
) -> tuple[Design, list[str], list[str]]:
    """-> (design, prefer_components, avoid_components). Falls back to the heuristic if no model answers."""
    cat = catalog or load_catalog()
    o = overrides or Design()
    fully_set = o.style and o.format
    choice = None
    if not fully_set and use_model and (llm is not None or settings is not None):

        def _run() -> DesignChoice:
            from ..agents import get_llm
            from ..llm import invoke_structured

            model = get_llm(settings, llm, 0.4)

            sys = DIRECTOR_SYSTEM.format(styles=cat.styles_guide(), transitions=", ".join(cat.transitions))
            user = {
                "content": source_text[:6000],
                "context": context,
                "brand": {"name": kit.name, "tone": kit.tone} if kit else None,
                "brand_profile": (profile.model_dump(exclude_defaults=True) if profile else None),
                "already_decided": o.model_dump(exclude_defaults=True),
            }
            return invoke_structured(
                model,
                DesignChoice,
                [{"role": "system", "content": sys}, {"role": "user", "content": json.dumps(user, default=str)}],
            )

        try:
            choice = rec.call("design", DesignChoice, _run) if rec else _run()
        except Exception as e:  # noqa: BLE001  (no model, no recording, provider error): use the heuristic
            log.info("design: director model unavailable (%s); using heuristic", str(e)[:120])
            choice = None
    if choice is None:
        choice = heuristic(source_text, context, kit)
    design = constrain(choice, profile, o, cat)
    from ..kinds import get_kind

    kind = get_kind((context or {}).get("kind"))
    if kind and kind.pacing and not o.pacing and not (profile and getattr(profile, "pacing", None)):
        if design.pacing in (None, "normal"):  # the kind's hint, unless the director heard otherwise
            design.pacing = kind.pacing
    avoid = sorted(set(choice.avoid_components) | set((profile or BrandProfile()).avoid_components))
    prefer = [
        c
        for c in dict.fromkeys(choice.prefer_components + (profile or BrandProfile()).prefer_components)
        if c in cat.components and c not in avoid
    ]
    return design, prefer, [c for c in avoid if c in cat.components]
