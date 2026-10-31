"""Video kinds: what a request is for, which shapes the plan.

A kind sets the planner's structure (how the video opens, what it covers, how it ends), a default length,
the scene types that suit it and a pacing hint. It never overrides what the caller asked for: an explicit
length, design or profile still wins. Leave it out and the planner works as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VideoKind:
    id: str
    name: str
    purpose: str
    structure: str  # planner guidance: the arc of the video
    length: str  # default when the request doesn't give one
    prefer: list[str] = field(default_factory=list)
    pacing: str | None = None


KINDS: dict[str, VideoKind] = {
    k.id: k
    for k in [
        VideoKind(
            "lesson",
            "Lesson",
            "Teach one idea or skill from a course section.",
            "Open with why it matters to the viewer, teach the idea with one concrete example, show what doing it "
            "well looks like (and a common mistake if the source has one), then close with one thing to try.",
            "90s",
            ["definition", "do_dont", "instead_try", "numbered_steps", "dialogue"],
        ),
        VideoKind(
            "course_summary",
            "Course summary",
            "Preview or recap a whole course or program: what it covers and what you'll be able to do.",
            "Open with who the course is for and the outcome, walk through the modules or sessions in order "
            "(one line each), then close with how to start or what comes next.",
            "75s",
            ["agenda_timeline", "journey", "card_grid", "icon_grid"],
        ),
        VideoKind(
            "session_recap",
            "Session recap",
            "Recap a live session, meeting or workshop for people who attended or missed it.",
            "Say which session this was, recap the two or three key takeaways (with any decision or number that "
            "was agreed), then close with the actions or homework and the next session.",
            "60s",
            ["checklist", "pull_quote", "big_stat", "chapter"],
            "brisk",
        ),
        VideoKind(
            "explainer",
            "Explainer",
            "Explain one concept, policy or system to people who are new to it.",
            "Open with the problem or question, explain the idea in plain words with one analogy or example, show "
            "how it works step by step, then close with why it matters to the viewer.",
            "75s",
            ["definition", "steps_path", "comparison", "decision", "line_chart"],
        ),
        VideoKind(
            "how_to",
            "How-to",
            "Show how to do one task, step by step.",
            "Say what the viewer will be able to do, give what they need first, walk through the steps in order "
            "(each step one action), then close with how to check it worked.",
            "60s",
            ["numbered_steps", "steps_path", "code_snippet", "annotated_mock", "checklist"],
        ),
        VideoKind(
            "announcement",
            "Announcement",
            "Tell people about a change, launch or news, and what it means for them.",
            "Lead with the news in one sentence, say what changes and when, what the viewer needs to do (if "
            "anything), then close with where to find more.",
            "45s",
            ["big_stat", "chapter", "pull_quote", "agenda_timeline"],
            "brisk",
        ),
        VideoKind(
            "onboarding",
            "Onboarding",
            "Welcome new people and get them through their first days.",
            "Welcome the viewer, say what their first days or weeks look like, the people and places that help, "
            "and close with the one thing to do first.",
            "75s",
            ["journey", "agenda_timeline", "image_caption", "icon_grid", "sticky_tip"],
        ),
    ]
}


def get_kind(kind: str | None) -> VideoKind | None:
    if not kind:
        return None
    k = KINDS.get(str(kind).strip().lower().replace("-", "_").replace(" ", "_"))
    if k is None:
        raise ValueError(f"unknown video kind '{kind}'; choose one of: {', '.join(KINDS)}")
    return k


def kinds_guide() -> list[dict]:
    """For pickers in a UI, GET /v1/kinds and agents."""
    return [{"id": k.id, "name": k.name, "purpose": k.purpose, "length": k.length} for k in KINDS.values()]
