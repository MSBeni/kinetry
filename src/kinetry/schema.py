"""Structured video plan the LLM must produce.

A plan is a list of scenes drawn from a small set of fixed archetypes. Every
scene carries *beats*: one narration sentence (or two) plus the on-screen
elements that appear while it is spoken. Timing is derived from the real audio
duration of each beat, so visuals and narration stay in sync without anyone
hand-tuning reveal times.

Character limits are soft guidance for the model; the rendered-layout fit
check (fitcheck.py) is the real gate.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


def S(max_len: int, desc: str = "") -> object:
    return Field(..., max_length=max_len, description=desc)


class Beat(BaseModel):
    say: str = Field(
        ..., min_length=3, max_length=320, description="Narration spoken during this beat. Plain sentences."
    )
    show: list[str] = Field(
        default_factory=list,
        description="Element keys revealed when this beat starts, e.g. 'headline', 'items.0', 'cards.2'.",
    )


class _SceneBase(BaseModel):
    nav: str = Field(..., max_length=16, description="Short label for the bottom progress bar.")
    eyebrow: str = Field("", max_length=40, description="Small uppercase label above the headline.")
    beats: list[Beat] = Field(..., min_length=1, max_length=8)

    # keys an archetype exposes for reveal; subclasses override
    def reveal_keys(self) -> list[str]:  # pragma: no cover - overridden
        return []

    @model_validator(mode="after")
    def _check_show_keys(self):
        valid = set(self.reveal_keys())
        seen: set[str] = set()
        for b in self.beats:
            for k in b.show:
                if k not in valid:
                    raise ValueError(f"{self.kind}: unknown element key '{k}'. Valid keys: {sorted(valid)}")
                if k in seen:
                    raise ValueError(f"{self.kind}: element '{k}' is revealed by more than one beat")
                seen.add(k)
        return self


class TitleScene(_SceneBase):
    kind: Literal["title"] = "title"
    kicker: str = Field("", max_length=60)
    headline: str = S(60, "Main title, 2-3 lines at most")
    chips: list[str] = Field(
        default_factory=list, max_length=3, description="Up to 3 short numbered aims, <=32 chars each"
    )

    def reveal_keys(self):
        return ["headline", "kicker"] + [f"chips.{i}" for i in range(len(self.chips))]


class SplitListScene(_SceneBase):
    kind: Literal["split_list"] = "split_list"
    headline: str = S(48)
    aside: str = Field("", max_length=40, description="Italic one-liner under the headline")
    tags: list[str] = Field(default_factory=list, max_length=2)
    panel_label: str = S(32, "Label for the right-hand panel, e.g. 'Ask each person'")
    items: list[str] = Field(..., min_length=2, max_length=4, description="Numbered items, <=40 chars each")

    def reveal_keys(self):
        return (
            ["headline", "aside", "panel"]
            + [f"tags.{i}" for i in range(len(self.tags))]
            + [f"items.{i}" for i in range(len(self.items))]
        )


class Card(BaseModel):
    label: str = Field(..., max_length=20)
    text: str = Field(..., max_length=28)


class CardGridScene(_SceneBase):
    kind: Literal["card_grid"] = "card_grid"
    headline: str = S(48)
    sub: str = Field("", max_length=80)
    cards: list[Card] = Field(..., min_length=2, max_length=4)
    strip_label: str = Field("", max_length=24)
    strip_items: list[str] = Field(default_factory=list, max_length=2)

    def reveal_keys(self):
        keys = ["headline", "sub"] + [f"cards.{i}" for i in range(len(self.cards))]
        if self.strip_label:
            keys += ["strip"] + [f"strip.{i}" for i in range(len(self.strip_items))]
        return keys


class QCard(BaseModel):
    title: str = Field(..., max_length=16)
    question: str = Field(..., max_length=90)


class QuestionCardsScene(_SceneBase):
    kind: Literal["question_cards"] = "question_cards"
    headline: str = S(48)
    cards: list[QCard] = Field(..., min_length=2, max_length=3)

    def reveal_keys(self):
        return ["headline"] + [f"cards.{i}" for i in range(len(self.cards))]


class JourneyScene(_SceneBase):
    kind: Literal["journey"] = "journey"
    headline: str = S(40)
    question: str = Field("", max_length=100)
    steps: list[str] = Field(..., min_length=3, max_length=8, description="<=26 chars each")
    current: int = Field(0, ge=0, description="0-based index of the 'you are here' step")

    def reveal_keys(self):
        return ["headline", "question", "steps", "progress"]

    @model_validator(mode="after")
    def _current_in_range(self):
        if self.current >= len(self.steps):
            raise ValueError("journey.current must index into steps")
        return self


class CloserScene(_SceneBase):
    kind: Literal["closer"] = "closer"
    pre: str = Field("", max_length=30)
    headline: str = S(40)
    meta: str = Field("", max_length=60)

    def reveal_keys(self):
        return ["pre", "headline", "meta"]


Scene = Annotated[
    Union[TitleScene, SplitListScene, CardGridScene, QuestionCardsScene, JourneyScene, CloserScene],
    Field(discriminator="kind"),
]


class VideoPlan(BaseModel):
    title: str = Field(..., max_length=80)
    chrome_left: str = Field(..., max_length=40, description="Top-left label, e.g. 'Onboarding · Week 2'")
    chrome_right: str = Field("", max_length=30, description="Top-right label, e.g. 'New managers'")
    scenes: list[Scene] = Field(..., min_length=3, max_length=8)

    @model_validator(mode="after")
    def _shape(self):
        if self.scenes[0].kind != "title":
            raise ValueError("first scene must be kind='title'")
        if self.scenes[-1].kind != "closer":
            raise ValueError("last scene must be kind='closer'")
        return self

    def word_count(self) -> int:
        return sum(len(b.say.split()) for s in self.scenes for b in s.beats)


ARCHETYPE_GUIDE = """
Scene archetypes (choose per scene; first must be 'title', last must be 'closer'):
- title: eyebrow, kicker, headline (<=60), chips (<=3 short numbered aims). keys: headline, kicker, chips.N
- split_list: headline left (<=48), aside, tags (<=2), right panel with panel_label and 2-4 numbered items. keys: headline, aside, tags.N, panel, items.N
- card_grid: headline, sub, 2-4 cards {label<=20, text<=28}, optional strip_label + <=2 strip_items. keys: headline, sub, cards.N, strip, strip.N
- question_cards: headline, 2-3 cards {title<=16, question<=90}. keys: headline, cards.N
- journey: headline, question, 3-8 steps (<=26 chars), current index. keys: headline, question, steps, progress (sweeps to the end)
- closer: pre, headline (<=40), meta. keys: pre, headline, meta
Each beat: 'say' is narration (1-2 sentences), 'show' lists keys revealed as it starts. Reveal each key at most once;
keys never shown appear when the scene opens. Put the reveal on the beat that first talks about that element.
"""
