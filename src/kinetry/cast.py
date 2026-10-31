"""Casts: named characters with a voice, for role-play and dialogue videos.

A cast file lists characters once (id, label, voice spec, and optionally how the character looks on an
avatar platform). Videos then say which character plays which speaker role:

    cast = load_cast("roleplay-cast.json")
    tf.render(plan, voices=cast.voices({"a": "gatekeeper_female", "b": "rookie_male"}), voice_api_key=key)

`appearance` is carried as metadata for a downstream avatar step (for example a LiveAvatar avatar name);
Kinetry itself doesn't render avatars.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from .voice import INWORLD_MODELS, parse_inworld

CHAR_ID = re.compile(r"[a-z0-9_]{1,40}")


class Character(BaseModel):
    id: str = Field(..., description="lower_snake id, e.g. gatekeeper_female")
    label: str = Field("", max_length=80, description="Display name, e.g. 'Gatekeeper (female)'")
    voice: str = Field(..., description="Voice spec, e.g. inworld:Bianca or inworld:inworld-tts-2:Bianca")
    appearance: str | None = Field(None, max_length=120, description="Avatar look on another platform (metadata)")
    tags: dict[str, str] = Field(default_factory=dict, description="Free-form, e.g. {'persona': 'gatekeeper'}")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not CHAR_ID.fullmatch(v):
            raise ValueError(f"character id '{v}' must be lower_snake (a-z, 0-9, _)")
        return v


class Cast(BaseModel):
    name: str = ""
    model: str | None = Field(None, description="Inworld model for inworld:<voice> entries that don't name one")
    characters: list[Character]

    @model_validator(mode="after")
    def _check(self) -> Cast:
        from .jobs import check_voice  # same rules as every other voice: known providers, safe ids

        if self.model and self.model not in INWORLD_MODELS:
            raise ValueError(f"cast model must be one of {', '.join(INWORLD_MODELS)}")
        seen = set()
        for c in self.characters:
            if c.id in seen:
                raise ValueError(f"character '{c.id}' is listed twice")
            seen.add(c.id)
            check_voice(c.voice, mode="any")
        return self

    def __getitem__(self, cid: str) -> Character:
        for c in self.characters:
            if c.id == cid:
                return c
        raise KeyError(f"no character '{cid}' in cast {self.name or ''}".strip())

    def spec(self, cid: str) -> str:
        """The character's voice spec, with the cast's Inworld model filled in when the entry has none."""
        v = self[cid].voice
        if self.model and v.startswith("inworld:") and ":" not in v.split(":", 1)[1]:
            return f"inworld:{self.model}:{v.split(':', 1)[1]}"
        return v

    def voices(self, assign: dict[str, str]) -> dict[str, str]:
        """{speaker role: character id} -> {speaker role: voice spec}, ready for `voices=`."""
        return {role: self.spec(cid) for role, cid in assign.items()}

    def inworld_ids(self) -> dict[str, str]:
        """character id -> Inworld voice id, for every Inworld character."""
        out = {}
        for c in self.characters:
            if c.voice.startswith("inworld:"):
                out[c.id] = parse_inworld(c.voice.split(":", 1)[1])[1]
        return out

    def verify_inworld(self, available: list[dict]) -> dict[str, bool]:
        """Which Inworld characters use a voice id the account can see (from InworldProvider.list_voices())."""
        ids = {v.get("voiceId") for v in available}
        return {cid: vid in ids for cid, vid in self.inworld_ids().items()}


def load_cast(path: str | Path) -> Cast:
    return Cast.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def parse_assign(pairs: list[str] | None) -> dict[str, str]:
    """['a=gatekeeper_female', 'narrator=coach'] -> {'a': 'gatekeeper_female', 'narrator': 'coach'}"""
    out = {}
    for kv in pairs or []:
        role, sep, cid = kv.partition("=")
        if not sep or not role or not cid:
            raise ValueError(f"expected ROLE=CHARACTER, got '{kv}'")
        out[role.strip()] = cid.strip()
    return out
