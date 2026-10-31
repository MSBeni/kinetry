"""Install and check the rendering toolchain (Node packages + Chrome).

Python can't vendor HyperFrames or Chrome, so `kinetry setup` installs pinned
versions into KINETRY_HOME (default ~/.cache/kinetry). Docker images run it
at build time.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from .config import Settings
from .design.icons import LUCIDE_VERSION


def setup(settings: Settings | None = None, *, browser: bool = True, voice: bool = True) -> list[str]:
    s = settings or Settings()
    log: list[str] = []
    if not shutil.which("node") or not shutil.which("npm"):
        raise RuntimeError("Node.js 22+ and npm are required (https://nodejs.org).")
    s.tool_dir.mkdir(parents=True, exist_ok=True)
    pkg = s.tool_dir / "package.json"
    if not pkg.exists():
        pkg.write_text(json.dumps({"name": "kinetry-tooling", "private": True}, indent=2))
    subprocess.run(
        [
            "npm",
            "install",
            "--no-audit",
            "--no-fund",
            f"hyperframes@{s.hyperframes_version}",
            f"gsap@{s.gsap_version}",
            f"lucide-static@{LUCIDE_VERSION}",
            f"three@{s.three_version}",
            f"lottie-web@{s.lottie_version}",
        ],
        cwd=s.tool_dir,
        check=True,
    )
    log.append(
        f"installed hyperframes@{s.hyperframes_version}, gsap@{s.gsap_version}, lucide-static@{LUCIDE_VERSION}, "
        f"three@{s.three_version}, lottie-web@{s.lottie_version} in {s.tool_dir}"
    )
    log.append(
        "each under its own license (THIRD_PARTY.md in Kinetry's source lists them); "
        "GSAP is free to use but not open source: "
        "https://gsap.com/standard-license"
    )
    if browser and not s.browser_path:
        try:
            subprocess.run(s.hf_bin() + ["browser", "ensure"], cwd=s.tool_dir, env=s.hf_env(), check=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            why = "timed out" if isinstance(e, subprocess.TimeoutExpired) else "failed"
            raise RuntimeError(
                f"Downloading Chrome (headless shell) {why}. If you have Chrome or Chromium already, run "
                "`kinetry setup --no-browser` and set KINETRY_BROWSER_PATH to it, e.g. "
                "KINETRY_BROWSER_PATH=/usr/bin/chromium."
            ) from e
        log.append("downloaded HyperFrames' Chrome headless shell")
    if voice:
        try:
            import kokoro_onnx  # noqa: F401

            log.append("kokoro-onnx present (local voice)")
        except ImportError:
            log.append("kokoro-onnx missing: pip install 'kinetry[kokoro]' for the free local voice")
    return log


def doctor(settings: Settings | None = None) -> dict[str, str]:
    s = settings or Settings()
    out: dict[str, str] = {}
    out["node"] = shutil.which("node") or "MISSING (Node 22+ required)"
    out["ffmpeg"] = shutil.which("ffmpeg") or "MISSING (required for rendering)"
    out["hyperframes"] = " ".join(s.hf_bin())
    try:
        out["gsap"] = str(s.gsap_path())
    except RuntimeError as e:
        out["gsap"] = f"MISSING ({e})"
    try:
        out["chrome"] = s.resolve_browser()
    except Exception as e:  # noqa: BLE001
        out["chrome"] = f"MISSING ({e})"
    try:
        import kokoro_onnx  # noqa: F401

        out["kokoro"] = "ok"
    except ImportError:
        out["kokoro"] = "not installed (optional)"
    icons = s.tool_dir / "node_modules" / "lucide-static" / "icon-nodes.json"
    out["icons"] = "ok (lucide)" if icons.exists() else "MISSING (run `kinetry setup`)"
    vendor = s.vendor_paths()
    out["3d stage"] = "ok (three.js)" if "three" in vendor else "not installed (run `kinetry setup`; only for depth)"
    out["lottie"] = "ok (lottie-web)" if "lottie" in vendor else "not installed (run `kinetry setup`; only for Lottie)"
    out["llm"] = "replay (recorded outputs)" if s.llm_provider == "replay" else s.llm_spec().spec
    if s.llm_provider != "replay":
        out["llm"] += _llm_installed(s.llm_spec().spec)
    if s.llm_fast:
        out["llm (fast)"] = s.llm_spec("fast").spec
    return out


def _llm_installed(spec: str) -> str:
    """'' when the provider's LangChain package is importable, else what to install (doctor only)."""
    import importlib.util

    from .llm import ALIASES, PROVIDERS

    provider = spec.split(":", 1)[0].lower()
    provider = ALIASES.get(provider, provider)
    extra = PROVIDERS.get(provider, (None, None))[1]
    module = {"anthropic": "langchain_anthropic", "openai": "langchain_openai", "bedrock": "langchain_aws",
              "google": "langchain_google_genai"}.get(extra or "")  # fmt: skip
    if not module or importlib.util.find_spec(module):
        return ""
    return f"  (not installed: pip install 'kinetry[{extra}]'; only needed to plan from your own content)"
