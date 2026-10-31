"""The three LLM jobs. Any provider and model (see llm.py); Amazon Bedrock by default.

1. Brand agent   - tool-using agent: reads the client's site, checks contrast
                   and font availability, returns a BrandKit.
2. Planner       - turns source content into a plan of catalog scenes (design/planner.py);
                   validation errors are fed back for another attempt.
3. Repair agent  - rewrites on-screen copy that still doesn't fit after the
                   type has been shrunk as far as allowed.

Every LLM output is recorded to <run>/llm/<step>.json. With KINETRY_LLM=replay
the recorded outputs are loaded instead (offline runs, CI, regression tests).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .brand import BrandKit, Fetcher, contrast, extract_signals
from .config import Settings
from .fitcheck import Problem
from .fonts import SUBSTITUTES, FontResolver
from .llm import _TOOLS_UNSUPPORTED, LLMLike, invoke_structured, resolve


# ------------------------------------------------------------------ plumbing
class Recorder:
    def __init__(self, run_dir: Path, settings: Settings, replay_dir: Path | None = None):
        self.dir = run_dir / "llm"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.replay = settings.llm_provider == "replay"
        self.replay_dir = replay_dir or self.dir

    def call(self, name: str, model: type[BaseModel], fn: Callable[[], BaseModel]) -> BaseModel:
        if self.replay:
            src = self.replay_dir / f"{name}.json"
            if not src.exists():
                raise FileNotFoundError(f"replay mode: no recorded output {src}")
            obj = model.model_validate_json(src.read_text())
        else:
            obj = fn()
        (self.dir / f"{name}.json").write_text(obj.model_dump_json(indent=2))
        return obj


def get_llm(settings: Settings, llm: LLMLike = None, temperature: float = 0.3, role: str = "main"):
    """Caller's choice (chat model, LLMConfig, "provider:model" spec, or Models) wins;
    otherwise the configured default (KINETRY_LLM / KINETRY_LLM_FAST)."""
    return resolve(llm, settings.llm_spec(role), role=role, temperature=temperature)


# ------------------------------------------------------------------ 1. brand
BRAND_SYSTEM = """You are a brand designer preparing a design kit for short narrated training videos.
Use the tools to study the website, then return a BrandKit.

Rules:
- accent = the dominant brand color (logo/CTA/links), not a random utility color.
- accent2 = a secondary brand color with a clearly different hue, for decoration only.
- background must be light and calm (near-white, optionally tinted toward the brand); videos use dark text on it.
- ink must be a near-black from the brand if one exists. Check ink, muted and accent against the background
  with contrast_ratio: ink >= 9, muted >= 4.8, accent >= 4.6. Adjust shades if needed.
- fonts: prefer the site's real fonts. Call font_available for each; if unavailable, use the suggested open substitute.
  A serif display + sans body pairing is fine if the brand uses a serif; otherwise use the sans for both.
- radius: 0-8 for sharp corporate brands, 16-28 for friendly ones.
- display_weight: 400 for serif/elegant brands; 600-700 if the site's headings are bold sans.
- gradient: if buttons or hero use a signature gradient (see roles.buttons[].gradient or CSS variables like
  --color-a/--color-b), give its 2-3 stops; otherwise leave it empty.
- Ignore third-party colors: CMS presets (e.g. --wp--preset--*), widget libraries (--swiper-*), validation states.
- rationale: 2-4 sentences naming the evidence (CSS variables, frequencies, fonts) behind each choice.
"""


def run_brand_agent(
    url: str,
    settings: Settings,
    rec: Recorder,
    fonts: FontResolver,
    fetcher: Fetcher | None = None,
    signals: dict | None = None,
    llm=None,
) -> BrandKit:
    def _run() -> BrandKit:
        from langchain.agents import create_agent
        from langchain_core.tools import tool

        @tool
        def site_signals(page_url: str) -> str:
            """Extract colors (with frequencies), CSS variables, fonts and theme color from a web page and its stylesheets."""
            if signals is not None and page_url.rstrip("/") == url.rstrip("/"):
                return json.dumps(signals, default=str)
            if urlparse(page_url).netloc != urlparse(url).netloc:  # the brand's own site only
                return "only pages on the brand's own site can be read"
            return json.dumps(extract_signals(page_url, fetcher), default=str)

        @tool
        def contrast_ratio(foreground_hex: str, background_hex: str) -> float:
            """WCAG contrast ratio between two hex colors (1-21)."""
            return round(contrast(foreground_hex, background_hex), 2)

        @tool
        def font_available(family: str) -> str:
            """Whether a font family can be vendored (Fontsource). Suggests an open substitute if not."""
            if family.lower() in SUBSTITUTES:
                return f"not available (proprietary); use '{SUBSTITUTES[family.lower()]}'"
            return "available" if fonts.available(family) else "not available; use 'Inter' (sans) or 'Fraunces' (serif)"

        model = get_llm(settings, llm, 0.2)
        try:
            agent = create_agent(
                model,
                [site_signals, contrast_ratio, font_available],
                system_prompt=BRAND_SYSTEM,
                response_format=BrandKit,
            )
            out = agent.invoke(
                {"messages": [{"role": "user", "content": f"Build the BrandKit for {url}"}]}, {"recursion_limit": 30}
            )
            return out["structured_response"]
        except Exception as e:  # noqa: BLE001
            if not (isinstance(e, NotImplementedError) or _TOOLS_UNSUPPORTED.search(str(e))):
                raise
        # Model without tool calling: hand it the evidence up front instead (contrast is enforced in code anyway).
        evidence = signals if signals is not None else extract_signals(url, fetcher)
        user = (
            f"Build the BrandKit for {url}.\nSite signals:\n{json.dumps(evidence, default=str)[:30000]}\n"
            f"Proprietary fonts and their open substitutes: {json.dumps(SUBSTITUTES)}"
        )
        return invoke_structured(
            model, BrandKit, [{"role": "system", "content": BRAND_SYSTEM}, {"role": "user", "content": user}]
        )

    return rec.call("brand", BrandKit, _run)  # type: ignore[return-value]


# ------------------------------------------------------------------ 2. planner: see design/planner.py


# ------------------------------------------------------------------ 3. repair
class Rewrite(BaseModel):
    field: str
    text: str


class Rewrites(BaseModel):
    items: list[Rewrite] = Field(default_factory=list)


REPAIR_SYSTEM = """You fix on-screen text that does not fit its slot in a video template.
For each field, return a shorter rewrite that keeps the meaning and tone, adds no new facts,
and is at most the given character budget. Avoid ending on a single short word."""


def run_repair(problems: list[Problem], settings: Settings, rec: Recorder, round_no: int, llm=None) -> Rewrites:
    def _run() -> Rewrites:
        model = get_llm(settings, llm, 0.2, role="fast")
        items = [
            {
                "field": p.field,
                "current": p.text,
                "issue": p.issue,
                "detail": p.detail,
                "max_chars": max(8, int(len(p.text) * 0.75)),
            }
            for p in problems
        ]
        return invoke_structured(
            model,
            Rewrites,
            [{"role": "system", "content": REPAIR_SYSTEM}, {"role": "user", "content": json.dumps(items, indent=2)}],
        )

    return rec.call(f"repair-{round_no}", Rewrites, _run)  # type: ignore[return-value]
