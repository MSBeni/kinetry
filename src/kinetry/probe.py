"""Get brand evidence from a live website with a real browser.

Computed styles catch what regex-scraping CSS misses (JS-rendered sites,
CSS-in-JS, design tokens set at runtime) and the probe can lift the actual
logo out of the page header.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

from .config import PKG_DIR, Settings


def probe_site(url: str, settings: Settings, out_json: Path) -> dict:
    env = settings.hf_env()
    res = subprocess.run(
        ["node", str(PKG_DIR / "js" / "brand_probe.mjs"), url, settings.resolve_browser(), str(out_json)],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    if res.returncode != 0:
        raise RuntimeError(f"brand probe failed: {res.stderr[-500:]}")
    return json.loads(out_json.read_text())


def logo_png_from_probe(probe: dict) -> bytes | None:
    """A raster copy of the best logo, drawn by the page (for cutting the symbol out of it)."""
    for cand in (probe.get("logos") or [])[:1]:
        m = re.match(r"data:image/png;base64,(.+)", cand.get("png") or "")
        if m:
            return base64.b64decode(m.group(1))
    return None


def logo_from_probe(probe: dict) -> tuple[str, bytes] | None:
    """Best logo candidate as (filename, bytes); SVG preferred."""
    for cand in probe.get("logos") or []:
        if cand.get("svg") and "<svg" in cand["svg"]:
            svg = cand["svg"]
            if "xmlns=" not in svg:
                svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
            return "logo.svg", svg.encode()
        m = re.match(r"data:image/(png|webp|jpeg);base64,(.+)", cand.get("dataUrl") or "")
        if m:
            ext = {"jpeg": "jpg"}.get(m.group(1), m.group(1))
            return f"logo.{ext}", base64.b64decode(m.group(2))
    return None
