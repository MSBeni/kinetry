"""Ready-made videos that render with no keys, no account and no network model calls.

Each demo is a reviewed plan and a brand pack shipped inside the package, voiced by the free local Kokoro
voice. `kinetry demo` renders one; it's the quickest way to see that the toolchain works end to end.

    from kinetry.demos import DEMOS, render_demo
    result = render_demo("welcome", out="kinetry-demo.mp4")
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

ROOT = resources.files(__package__)


@dataclass(frozen=True)
class Demo:
    name: str
    title: str
    about: str
    plan: str  # file in plans/
    brand: str  # folder in brands/
    voices: dict = field(default_factory=dict)  # role -> voice spec; the narrator is "narrator"
    seconds: int = 40  # about how long the video runs

    def plan_data(self) -> dict:
        return json.loads((ROOT / "plans" / self.plan).read_text(encoding="utf-8"))

    def brand_dir(self) -> Path:
        return Path(str(ROOT / "brands" / self.brand))


DEMOS: dict[str, Demo] = {
    d.name: d
    for d in [
        Demo(
            "welcome",
            "Your first Kinetry video",
            "What just happened on your machine, and what to run next. Two voices, classic style.",
            "welcome.json",
            "kinetry",
            {"narrator": "kokoro:af_heart", "co": "kokoro:am_michael"},
            seconds=40,
        ),
        Demo(
            "developer",
            "Kinetry from your own code",
            "Install, the Python API, the HTTP service and every way to plug it in. Technical style, code scenes.",
            "developer.json",
            "kinetry",
            {"narrator": "kokoro:af_heart", "co": "kokoro:am_michael"},
            seconds=70,
        ),
        Demo(
            "spanish",
            "Feedback que ayuda",
            "A micro-lesson in Spanish with captions and a two-person dialogue, for a made-up school.",
            "spanish.json",
            "aula-norte",
            {"narrator": "kokoro:ef_dora", "co": "kokoro:em_santa", "a": "kokoro:em_alex", "b": "kokoro:ef_dora"},
            seconds=75,
        ),
    ]
}


def missing_tools(settings) -> list[str]:
    """What has to be installed before a render can run, as ready-to-follow fixes."""
    import shutil

    from ..tooling import doctor

    fixes = []
    if not shutil.which("ffmpeg"):
        fixes.append(
            "FFmpeg isn't installed: install it with your package manager (for example `brew install ffmpeg`)."
        )
    if not shutil.which("node"):
        fixes.append("Node.js 22+ isn't installed: get it from https://nodejs.org.")
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        fixes.append("The free local voice isn't installed: run `pip install 'kinetry[kokoro]'`.")
    status = doctor(settings)
    if any(str(status.get(k, "")).startswith("MISSING") for k in ("gsap", "icons")):
        fixes.append("The renderer isn't set up yet: run `kinetry setup` (once, about a minute).")
    elif str(status.get("chrome", "")).startswith("MISSING"):
        fixes.append(
            "No Chrome to render with: run `kinetry setup` to download one, or point KINETRY_BROWSER_PATH at "
            "an installed Chrome or Chromium."
        )
    return fixes


def render_demo(
    name: str = "welcome",
    *,
    out: str | Path | None = None,
    settings=None,
    workdir: str | Path | None = None,
    quality: str | None = None,
    on_step: Callable[[str, float], None] | None = None,
):
    """Render a bundled demo; returns the engine's Result. Never calls a model: a demo plan is already
    reviewed, and if any text didn't fit, the run would stop as needs_review rather than ask a model."""
    from ..api import Kinetry
    from ..branding import BrandPack
    from ..config import Settings

    if name not in DEMOS:
        raise KeyError(f"no demo called {name!r}; choose one of: {', '.join(DEMOS)}")
    demo = DEMOS[name]
    s = settings or Settings()
    s.llm_provider = "replay"  # nothing here may reach a model, or need a key
    tf = Kinetry(settings=s, workdir=workdir)
    started = time.monotonic()

    def event(ev: dict) -> None:
        if on_step and ev.get("step"):
            on_step(ev["step"], time.monotonic() - started)

    voices = dict(demo.voices)
    narrator = voices.pop("narrator", None)
    return tf.render(
        demo.plan_data(),
        brand=BrandPack.load(demo.brand_dir()),
        out=out or f"kinetry-{name}.mp4",
        voice=narrator,
        voices=voices,
        qa_frames=False,
        quality=quality,
        on_event=event,
    )
