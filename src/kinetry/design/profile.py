"""Brand profiles: a company's standing design preferences, saved with its brand pack.

The creative director treats them as constraints (allowed styles, pinned format, scene types to
avoid) and hints (preferred scene types, notes). Anything a single request sets explicitly still wins.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .plan import Effects


class BrandProfile(BaseModel):
    styles: list[str] = Field(default_factory=list, description="Styles this brand may use (empty = any)")
    style: str | None = Field(None, description="Pin one style")
    format: str | None = Field(None, description="Pin a format: 16:9, 9:16 or 1:1")
    motion: str | None = None
    transition: str | None = None
    captions: bool | None = None
    pacing: str | None = None
    avoid_components: list[str] = Field(default_factory=list, description="Scene types never to use")
    prefer_components: list[str] = Field(default_factory=list, description="Scene types to favor")
    voices: dict[str, str] = Field(default_factory=dict, description="Role -> voice spec, e.g. narrator, a, b")
    music: str | None = Field(None, description="Path to a music bed (mixed under the voice)")
    music_volume: float = Field(0.16, ge=0, le=1)
    effects: Effects | None = Field(None, description="Default motion layers for this brand's videos")
    notes: str = Field("", max_length=600, description="Free-text guidance, e.g. 'formal tone, no slang'")

    def save(self, directory: str | Path) -> Path:
        p = Path(directory) / "profile.json"
        p.write_text(self.model_dump_json(indent=2, exclude_defaults=True))
        return p

    @classmethod
    def load(cls, directory: str | Path) -> BrandProfile:
        p = Path(directory) / "profile.json"
        return cls.model_validate_json(p.read_text()) if p.exists() else cls()
