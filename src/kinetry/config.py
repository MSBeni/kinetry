"""Runtime settings. Every field can be set in code or with a KINETRY_* env var."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent


def _home() -> Path:
    return Path(os.environ.get("KINETRY_HOME", Path.home() / ".cache" / "kinetry"))


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"KINETRY_{name}", default)


@dataclass
class Settings:
    # Where Kinetry keeps its Node tooling (HyperFrames + GSAP), fonts and voice cache.
    home: Path = field(default_factory=_home)
    # Chrome/Chromium used to measure layouts, probe sites and render. Unset: HyperFrames'
    # own managed browser (`kinetry setup` downloads it).
    browser_path: str | None = field(
        default_factory=lambda: _env("BROWSER_PATH") or os.environ.get("HYPERFRAMES_BROWSER_PATH")
    )
    # LLM: a "provider:model" spec ("anthropic:claude-sonnet-5-5", "openai:gpt-4.1",
    # "bedrock:<any model id or inference profile>", "google:gemini-2.5-pro", ...), a bare provider
    # ("bedrock", "openai") for its default model, or "replay" for recorded outputs.
    # Code can pass a spec, an LLMConfig or any LangChain chat model as Kinetry(llm=...).
    llm_provider: str = field(default_factory=lambda: _env("LLM", "bedrock"))
    # Optional cheaper model for small copy rewrites; defaults to the main model.
    llm_fast: str | None = field(default_factory=lambda: _env("LLM_FAST"))
    bedrock_model: str = field(
        default_factory=lambda: _env("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    )
    aws_region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1"))
    # Voice
    voicestudio_url: str = field(default_factory=lambda: _env("VOICESTUDIO_URL", "http://127.0.0.1:3900"))
    voicestudio_key: str | None = field(default_factory=lambda: _env("VOICESTUDIO_API_KEY"))
    # Service mode: every URL fetched for a caller (brand site, its stylesheets, redirects, the browser
    # probe's requests) must resolve to a public address. The job service turns this on.
    public_urls_only: bool = field(default_factory=lambda: _env("PUBLIC_URLS_ONLY", "") == "1")
    # Loops and output
    max_plan_attempts: int = 3
    max_fit_rounds: int = 6  # 4 shrink steps, then room for a copy rewrite
    fps: int = 30
    # Output encoding: draft | standard | high, or a CRF number (see hf.QUALITY)
    quality: str = field(default_factory=lambda: _env("QUALITY", "standard"))
    # where uploaded images live (upload:<id> references); the job service points it at its data dir
    images_dir: Path | None = None
    hyperframes_version: str = "0.8.112"
    gsap_version: str = "3.14.2"
    three_version: str = "0.181.2"  # the 3D stage (design.effects.depth)
    lottie_version: str = "5.12.2"  # callers' Lottie animations (illustration scenes)

    def llm_spec(self, role: str = "main"):
        """The configured default model for a step, as an LLMConfig."""
        from .llm import LLMConfig

        if role == "fast" and self.llm_fast:
            return LLMConfig.from_spec(self.llm_fast, region=self.aws_region)
        spec = self.llm_provider or "bedrock"
        if spec in ("bedrock", "replay"):
            spec = f"bedrock:{self.bedrock_model}"
        return LLMConfig.from_spec(spec, region=self.aws_region)

    @property
    def tool_dir(self) -> Path:
        return self.home / "tooling"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    def hf_bin(self) -> list[str]:
        local = self.tool_dir / "node_modules" / ".bin" / "hyperframes"
        if local.exists():
            return [str(local)]
        if shutil.which("hyperframes"):
            return ["hyperframes"]
        return ["npx", "--yes", f"hyperframes@{self.hyperframes_version}"]

    def gsap_path(self) -> Path:
        p = self.tool_dir / "node_modules" / "gsap" / "dist" / "gsap.min.js"
        if not p.exists():
            raise RuntimeError("GSAP not found. Run `kinetry setup` once to install the rendering toolchain.")
        return p

    def vendor_paths(self) -> dict[str, Path]:
        """Players for the heavier motion layers, when installed (`kinetry setup`)."""
        nm = self.tool_dir / "node_modules"
        out: dict[str, Path] = {}
        if (nm / "three" / "build" / "three.module.min.js").is_file():
            out["three"] = nm / "three" / "build"
        if (nm / "lottie-web" / "build" / "player" / "lottie_light.min.js").is_file():
            out["lottie"] = nm / "lottie-web" / "build" / "player" / "lottie_light.min.js"
        return out

    def hf_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.browser_path:
            env["HYPERFRAMES_BROWSER_PATH"] = self.browser_path
            env.setdefault("PUPPETEER_EXECUTABLE_PATH", self.browser_path)
        env.setdefault("HYPERFRAMES_SKIP_SKILLS", "1")
        # the local voice runs in Python: use this one (where kinetry[kokoro] is installed), not whatever
        # python3 comes first on PATH
        env.setdefault("HYPERFRAMES_PYTHON", sys.executable)
        env["KINETRY_TOOL_DIR"] = str(self.tool_dir)
        env["KINETRY_PUBLIC_URLS_ONLY"] = "1" if self.public_urls_only else ""
        return env

    def resolve_browser(self) -> str:
        """Chrome path for our own puppeteer scripts (measure, probe)."""
        if self.browser_path:
            return self.browser_path
        import subprocess

        res = subprocess.run(
            self.hf_bin() + ["browser", "path"],
            capture_output=True,
            text=True,
            env=self.hf_env(),
            cwd=self.tool_dir if self.tool_dir.exists() else None,
            timeout=120,
        )
        path = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
        if res.returncode != 0 or not Path(path).exists():
            raise RuntimeError("No Chrome found. Run `kinetry setup` or set KINETRY_BROWSER_PATH.")
        self.browser_path = path
        return path
