"""The visual catalog: every scene type and layout, rendered in every style and format.

`kinetry gallery --out gallery/` composes example projects from the manifests' example data
(silent, estimated timing), runs `hyperframes check` on each, snapshots every scene once its
reveals have finished, and writes an index.html to browse them. It is both documentation
(what can I pick?) and a regression test (did a change break a style?).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from html import escape
from pathlib import Path

from .. import hf
from ..branding import BrandPack
from ..config import Settings
from ..fitcheck import find_problems, measure, plan_repairs
from ..fonts import FontResolver
from ..timing import build_timeline, silent_clips
from .build import compose_project
from .catalog import Catalog, load_catalog
from .icons import Icons
from .plan import SIZES, Beat, Design, Scene, VideoPlan2
from .render import settled_times

log = logging.getLogger("kinetry")
CHUNK = 12


@dataclass
class Shot:
    style: str
    fmt: str
    component: str
    layout: str
    path: Path
    project: Path


def example_scenes(cat: Catalog, fmt: str, components: list[str] | None = None) -> list[Scene]:
    out = []
    for c in cat.components.values():
        if components and c.id not in components:
            continue
        for lay in c.layouts_for(fmt):
            beats = [Beat(**b) for b in c.example_beats] or [Beat(say=c.purpose)]
            out.append(
                Scene(type=c.id, layout=lay, nav=c.name[:20], data=json.loads(json.dumps(c.example)), beats=beats)
            )
    return out


def build_gallery(
    out_dir: Path,
    settings: Settings,
    *,
    pack: BrandPack | None = None,
    styles: list[str] | None = None,
    formats: list[str] | None = None,
    components: list[str] | None = None,
    check: bool = True,
    snapshots: bool = True,
    fit_rounds: int = 4,
    effects: str = "off",
    lang: str = "en",
    depth: str = "off",
) -> dict:
    """`effects`: render with motion layers (subtle | rich); their frames are named with a -fx suffix.
    `lang`: page language; a right-to-left one (fa, ar, he, ur) audits every layout mirrored."""
    cat = load_catalog()
    pack = pack or BrandPack.default()
    icons = Icons(settings.tool_dir)
    fonts = FontResolver(settings.cache_dir / "fonts")
    shots: list[Shot] = []
    checks: dict[str, dict] = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for style in styles or list(cat.styles):
        for fmt in formats or ["16:9", "9:16", "1:1"]:
            scenes = example_scenes(cat, fmt, components)
            for ci in range(0, len(scenes), CHUNK):
                chunk = scenes[ci : ci + CHUNK]
                if len(chunk) < 2:
                    chunk = chunk + scenes[:1]
                plan = VideoPlan2(
                    title=f"{style} {fmt}",
                    chrome_left="Kinetry gallery",
                    chrome_right=style,
                    design=Design(
                        style=style,
                        format=fmt,
                        transition="cut",
                        effects={"level": effects, "illustration": effects, "depth": depth},
                        lang=lang,
                    ),
                    scenes=chunk,
                )
                tl = build_timeline(plan, silent_clips(plan))
                tag = (
                    ("" if effects == "off" else f"-fx{effects}")
                    + ("" if depth == "off" else f"-3d{depth}")
                    + ("" if lang == "en" else f"-{lang}")
                )
                name = f"{style}-{fmt.replace(':', 'x')}{tag}-{ci // CHUNK}"
                proj = out_dir / "projects" / name
                fit: dict[str, int] = {}
                compose_project(plan, pack, tl, proj, settings, catalog=cat, icons=icons, fonts=fonts)
                for rnd in range(fit_rounds if check else 0):
                    # same shrink step the pipeline runs: smaller type where the example copy doesn't fit
                    rep = measure(proj / "index.html", settings, proj / f"fit-{rnd}.json", SIZES[fmt])
                    new_fit, _ = plan_repairs(find_problems(rep), fit)
                    if new_fit == fit:
                        break
                    fit = new_fit
                    compose_project(plan, pack, tl, proj, settings, fit=fit, catalog=cat, icons=icons, fonts=fonts)
                if check:
                    res = hf.check(proj, settings)
                    checks[name] = {"ok": res["ok"], "errors": res["errors"][:20]}
                    log.info(
                        "gallery %s: check %s (%d errors)", name, "ok" if res["ok"] else "FAILED", len(res["errors"])
                    )
                if snapshots:
                    times = settled_times(plan, tl, cat)
                    frames = hf.snapshot(proj, times, proj / "frames", settings)
                    for sc, fr in zip(chunk[: len(frames)], frames, strict=False):
                        dest = out_dir / "img" / f"{style}-{fmt.replace(':', 'x')}-{sc.type}-{sc.layout}{tag}.png"
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(fr.read_bytes())
                        shots.append(Shot(style, fmt, sc.type, sc.layout, dest, proj))
    (out_dir / "checks.json").write_text(json.dumps(checks, indent=2))
    if shots:
        (out_dir / "index.html").write_text(_index(cat, shots, checks))
    return {
        "shots": len(shots),
        "projects": len(checks) or None,
        "failed": sorted(k for k, v in checks.items() if not v["ok"]),
    }


def _index(cat: Catalog, shots: list[Shot], checks: dict) -> str:
    by_comp: dict[str, list[Shot]] = {}
    for s in shots:
        by_comp.setdefault(s.component, []).append(s)
    parts = []
    for cid, items in by_comp.items():
        c = cat.components[cid]
        cells = "".join(
            f'<figure class="f{s.fmt.replace(":", "x")}"><img loading="lazy" src="img/{s.path.name}" alt="">'
            f"<figcaption>{escape(s.style)} · {escape(s.layout)} · {s.fmt}</figcaption></figure>"
            for s in items
        )
        parts.append(
            f'<section><h2>{escape(c.name)} <code>{cid}</code></h2><p>{escape(c.purpose)}</p><div class="grid">{cells}</div></section>'
        )
    n = cat.combinations()
    bad = [k for k, v in checks.items() if not v["ok"]]
    return f"""<!doctype html><meta charset="utf-8"><title>Kinetry gallery</title>
<style>body{{font:15px system-ui;margin:0;padding:24px;background:#f4f5f2;color:#16181b}}h1{{margin:0 0 6px}}
section{{margin:36px 0}}.grid{{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start}}figure{{margin:0}}
figure img{{display:block;border:1px solid #d8dbd5;border-radius:6px}}.f16x9 img{{width:384px}}.f9x16 img{{width:162px}}.f1x1 img{{width:216px}}
figcaption{{font:12px ui-monospace,monospace;color:#5a6068;margin-top:4px}}code{{font-size:.8em;color:#5a6068}}</style>
<h1>Kinetry gallery</h1><p>{n["components"]} scene types · {n["layouts"]} layouts · {n["styles"]} styles · {n["transitions"]} transitions ·
3 formats. Checks: {len(checks) - len(bad)}/{len(checks)} projects pass{(" (failing: " + ", ".join(bad) + ")") if bad else ""}.</p>
{"".join(parts)}"""
