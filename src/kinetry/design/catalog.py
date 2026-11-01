"""The design catalog: components (scene types), style packs, motion packs and transitions.

Everything is data on disk, so adding a scene type or a style means adding a folder:

    components/<id>/component.json   manifest: purpose, fields + limits, reveal keys, layouts, example
    components/<id>/template.html    Jinja markup for the stage (receives `d`, `L`, `t()`, `icon()`...)
    components/<id>/style.css        CSS, scoped by `.c-<id>` and `.l-<layout>`
    components/<id>/motion.js        TF.comp("<id>", ctx => {...}): how it animates
    styles/<id>/style.json           tokens: type scale, ground, radius, accent font, motion, transition, chrome
    styles/<id>/style.css            background, decor and per-style touches, scoped by `.st-<id>`
    assets/motion/<id>.js            motion pack: how headlines, items, cards... enter and leave
    assets/transitions/<id>.json     transition manifest (+ <id>.js)

The same manifests drive validation, the planner's guide, docs/CATALOG.md and the gallery,
so the documentation can't drift from what the engine renders.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..textwidth import text_width

HERE = Path(__file__).parent
TOLERANCE = 1.1  # planners may exceed a char limit by 10%; the rendered fit check is the real gate


# ---------------------------------------------------------------- manifests
@dataclass
class FieldSpec:
    type: str  # text | list | object | enum | int | number | icon | bool
    max: int | None = None
    min: int | None = None
    lines: int = 1
    role: str = "body"
    optional: bool = False
    desc: str = ""
    of: FieldSpec | None = None
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    values: list[str] = field(default_factory=list)
    default: Any = None

    @classmethod
    def parse(cls, raw: dict) -> FieldSpec:
        raw = dict(raw)
        of = cls.parse(raw.pop("of")) if "of" in raw else None
        fields = {k: cls.parse(v) for k, v in raw.pop("fields", {}).items()}
        return cls(of=of, fields=fields, **raw)

    def describe(self) -> str:
        opt = ""  # callers mark optional fields with '?' on the field name
        if self.type == "text":
            return f"text<={self.max}{opt}"
        if self.type == "list":
            return f"[{self.min or 0}-{self.max} × {self.of.describe()}]"
        if self.type == "object":
            inner = ", ".join(f"{k}{'?' if v.optional else ''}: {v.describe()}" for k, v in self.fields.items())
            return "{" + inner + "}" + opt
        if self.type == "enum":
            return "|".join(self.values) + opt
        if self.type in ("int", "number"):
            rng = f" {self.min}..{self.max}" if self.min is not None or self.max is not None else ""
            return f"{self.type}{rng}{opt}"
        if self.type == "icon":
            return f"icon name{opt}"
        if self.type == "image":
            return f"image ref from context.images{opt}"
        if self.type == "animation":
            return f"Lottie ref from context.animations{opt}"
        return self.type + opt


@dataclass
class Reveal:
    key: str
    requires: str | None = None  # field that must be present for this key to exist
    of: str | None = None  # list field that 'x.*' counts, when it isn't named x


@dataclass
class Component:
    id: str
    name: str
    purpose: str
    use_when: list[str]
    avoid_when: list[str]
    tags: list[str]
    fields: dict[str, FieldSpec]
    reveals: list[Reveal]
    layouts: dict[str, dict]
    example: dict
    example_beats: list[dict]
    dir: Path
    speakers: bool = False  # beats carry voice roles from data (dialogue)
    lipsync: bool = False  # the renderer times mouth shapes from each speaker's own audio (kinetry.visemes)
    inverse_layouts: list[str] = field(default_factory=list)  # layouts set on the brand color
    # cross-field rules: {"needs": ["a", "b"]} (b required when a is set), {"index": "current", "of": "steps"}
    checks: list[dict] = field(default_factory=list)
    # the element the camera punches in on at that key's reveal: {"key": "value", "sel": ".val"}
    focus: dict | None = None
    # a motion layer this scene type depends on (e.g. "kinetic"); only offered when it's switched on
    requires: str | None = None
    # extra font roles the scene type needs, e.g. ["mono"] (resolved only for plans that use it)
    fonts: list[str] = field(default_factory=list)
    # where its design came from, for scene types adapted from the HyperFrames registry (THIRD_PARTY.md)
    adapted_from: str | None = None

    def layouts_for(self, fmt: str) -> list[str]:
        return [k for k, v in self.layouts.items() if fmt in v.get("formats", ["16:9", "9:16", "1:1"])]

    def spec_for(self, path: str) -> FieldSpec | None:
        """'items.2.title' -> the FieldSpec for items[].title"""
        cur: FieldSpec | None = FieldSpec("object", fields=self.fields)
        for part in path.split("."):
            if cur is None:
                return None
            if part.isdigit():
                cur = cur.of
            else:
                cur = cur.fields.get(part)
        return cur

    def keys(self, data: dict) -> list[str]:
        """Concrete reveal keys for this data, in manifest order."""
        out = []
        for r in self.reveals:
            base = r.key.split(".")[0]
            src = r.of or base
            need = r.requires or (src if src in self.fields else None)
            if need and not _present(data.get(need)):
                continue
            if r.key.endswith(".*"):
                out += [f"{base}.{i}" for i in range(len(data.get(src) or []))]
            else:
                out.append(r.key)
        return out

    def guide(self) -> str:
        data = ", ".join(f"{k}{'?' if v.optional else ''}: {v.describe()}" for k, v in self.fields.items())
        keys = ", ".join(r.key.replace(".*", ".N") for r in self.reveals)
        lines = [f"- {self.id}: {self.purpose}"]
        if self.use_when:
            lines.append(f"  use when: {'; '.join(self.use_when)}")
        if self.avoid_when:
            lines.append(f"  avoid when: {'; '.join(self.avoid_when)}")
        lines.append(f"  data: {{{data}}}")
        lines.append(f"  reveal keys: {keys}")
        if self.speakers:
            lines.append("  beats: one beat per line, with voice set to that line's speaker id ('a' or 'b')")
        return "\n".join(lines)


@dataclass
class Style:
    id: str
    name: str
    description: str
    best_for: list[str]
    tokens: dict
    dir: Path

    @property
    def motion(self) -> str:
        return self.tokens.get("motion", self.id)

    @property
    def transition(self) -> str:
        return self.tokens.get("transition", "exit")

    @property
    def chrome(self) -> str:
        return self.tokens.get("chrome", "rule")


@dataclass
class Transition:
    id: str
    name: str
    description: str
    kind: str  # exit | cut | overlap | overlay | subcomp
    duration: float
    js: str
    dir: Path


@dataclass
class Catalog:
    components: dict[str, Component]
    styles: dict[str, Style]
    motions: dict[str, str]  # id -> js source
    transitions: dict[str, Transition]
    root: Path

    # -------------------------------------------------------- validation
    def validate_scene(self, scene, where: str = "scene") -> list[str]:
        comp = self.components.get(scene.type)
        if comp is None:
            return [f"{where}: unknown type '{scene.type}'. Use one of: {', '.join(sorted(self.components))}"]
        errs = _check_object(comp.fields, scene.data, f"{where} ({scene.type}).data")
        for rule in comp.checks:
            if "needs" in rule:
                a, b = rule["needs"]
                if _present(scene.data.get(a)) and not _present(scene.data.get(b)):
                    errs.append(f"{where} ({scene.type}).data.{b} is required when {a} is set")
            elif "index" in rule:
                i, lst = scene.data.get(rule["index"]), scene.data.get(rule["of"]) or []
                if isinstance(i, int) and not 0 <= i < len(lst):
                    errs.append(
                        f"{where} ({scene.type}).data.{rule['index']} must point into {rule['of']} (0-{len(lst) - 1})"
                    )
        if scene.layout and scene.layout not in comp.layouts:
            errs.append(f"{where}: layout '{scene.layout}' doesn't exist for {scene.type}; use {list(comp.layouts)}")
        if errs:
            return errs
        valid = set(comp.keys(scene.data))
        for r in comp.reveals:  # whole-list keys ('items') are valid alongside items.N
            if r.key.endswith(".*") and _present(scene.data.get(r.of or r.key[:-2])):
                valid.add(r.key[:-2])
        seen: set[str] = set()
        for bi, b in enumerate(scene.beats):
            for k in b.show:
                if k not in valid:
                    errs.append(f"{where} beat {bi}: unknown reveal key '{k}'; valid: {sorted(valid)}")
                elif k in seen:
                    errs.append(f"{where} beat {bi}: '{k}' is revealed by more than one beat")
                seen.add(k)
            if (
                comp.speakers
                and b.voice not in (None, "narrator")
                and b.voice not in (scene.data.get("speakers") or {})
            ):
                errs.append(f"{where} beat {bi}: voice '{b.voice}' isn't one of the scene's speakers")
            if comp.speakers:  # a line is spoken by its own speaker's voice
                for k in b.show:
                    m = re.fullmatch(r"lines\.(\d+)", k)
                    lines = scene.data.get("lines") or []
                    if m and int(m.group(1)) < len(lines) and b.voice != lines[int(m.group(1))].get("who"):
                        who = lines[int(m.group(1))].get("who")
                        errs.append(f'{where} beat {bi}: reveals {k}, so set "voice": "{who}" (that line\'s speaker)')
        return errs

    def validate_plan(self, plan) -> list[str]:
        errs: list[str] = []
        d = plan.design
        if d.style and d.style not in self.styles:
            errs.append(f"design.style '{d.style}' unknown; use one of {sorted(self.styles)}")
        if d.motion and d.motion not in self.motions:
            errs.append(f"design.motion '{d.motion}' unknown; use one of {sorted(self.motions)}")
        if d.transition and d.transition not in self.transitions:
            errs.append(f"design.transition '{d.transition}' unknown; use one of {sorted(self.transitions)}")
        for i, sc in enumerate(plan.scenes):
            errs += self.validate_scene(sc, f"scenes[{i}]")
            if sc.layout and d.format and sc.layout in self.components.get(sc.type, _NONE).layouts:
                fmts = self.components[sc.type].layouts[sc.layout].get("formats", ["16:9", "9:16", "1:1"])
                if d.format not in fmts:
                    errs.append(f"scenes[{i}]: layout '{sc.layout}' doesn't support {d.format}")
        return errs

    # -------------------------------------------------------- guides and docs
    def planner_guide(self, allowed: list[str] | None = None) -> str:
        comps = [c for c in self.components.values() if not allowed or c.id in allowed]
        return "Scene types (components):\n" + "\n".join(c.guide() for c in comps)

    def styles_guide(self) -> str:
        return "\n".join(f"- {s.id}: {s.description} Best for: {', '.join(s.best_for)}." for s in self.styles.values())

    def to_dict(self) -> dict:
        return {
            "components": {
                c.id: {
                    "name": c.name,
                    "purpose": c.purpose,
                    "use_when": c.use_when,
                    "avoid_when": c.avoid_when,
                    "tags": c.tags,
                    "data": {k: v.describe() for k, v in c.fields.items()},
                    "reveal_keys": [r.key for r in c.reveals],
                    "layouts": c.layouts,
                }
                for c in self.components.values()
            },
            "styles": {
                s.id: {
                    "name": s.name,
                    "description": s.description,
                    "best_for": s.best_for,
                    "motion": s.motion,
                    "transition": s.transition,
                    "chrome": s.chrome,
                }
                for s in self.styles.values()
            },
            "motions": sorted(self.motions),
            "transitions": {
                t.id: {"name": t.name, "description": t.description, "kind": t.kind} for t in self.transitions.values()
            },
            "formats": ["16:9", "9:16", "1:1"],
        }

    def combinations(self) -> dict:
        layouts = {f: sum(len(c.layouts_for(f)) for c in self.components.values()) for f in ("16:9", "9:16", "1:1")}
        renderings = sum(layouts.values()) * len(self.styles)
        return {
            "components": len(self.components),
            "layouts": sum(len(c.layouts) for c in self.components.values()),
            "styles": len(self.styles),
            "motions": len(self.motions),
            "transitions": len(self.transitions),
            "formats": 3,
            "scene_renderings": renderings,
        }

    def to_markdown(self) -> str:
        n = self.combinations()
        out = [
            "# Kinetry design catalog",
            "",
            "Generated from the manifests in `src/kinetry/design/` by `kinetry catalog --markdown`. "
            "Don't edit by hand; CI checks it's current.",
            "",
            f"**{n['components']} scene types · {n['layouts']} layouts · {n['styles']} styles · {n['motions']} motion "
            f"packs · {n['transitions']} transitions · 3 formats** → {n['scene_renderings']} distinct scene renderings "
            "before brand colors, fonts and content.",
            "",
            "## Styles",
            "",
            "| Style | Description | Best for | Motion | Transition | Chrome |",
            "|---|---|---|---|---|---|",
        ]
        for s in self.styles.values():
            out.append(
                f"| `{s.id}` | {s.description} | {', '.join(s.best_for)} | {s.motion} | {s.transition} | {s.chrome} |"
            )
        out += ["", "## Transitions", "", "| Transition | Kind | What it does |", "|---|---|---|"]
        for t in self.transitions.values():
            out.append(f"| `{t.id}` | {t.kind} | {t.description} |")
        out += [
            "",
            "## Motion layers (opt-in)",
            "",
            "Off by default, so a plain video looks exactly like the styles above. Set `design.effects.level` to "
            "`subtle` or `rich`, or each layer on its own (`camera`, `kinetic`, `ambient`). `illustration`, `depth` "
            "and `characters` are heavier and only on when named.",
            "",
            "| Layer | subtle | rich |",
            "|---|---|---|",
            "| `camera` | slow push-in on every scene, background parallax | directional drift, plus a punch-in on "
            "each scene's key moment |",
            "| `kinetic` | headline words rise and tilt into place; key words pop | words flip in with 3D depth; "
            "enables the `statement` scene type, whose words land as they're spoken |",
            "| `ambient` | soft pools of brand color drifting behind the scene (a moving spotlight in `technical`) | "
            "stronger light plus slow-rising particles |",
            "| `illustration` (by name only) | enables the `illustration` scene type: animated illustrations or the "
            "caller's Lottie | parts keep moving gently; a Lottie loops |",
            "| `depth` (by name only) | a Three.js stage behind the scenes: a camera that glides from scene to scene "
            "past the brand's own 3D models where a scene leaves room (when the brand has shared some), its logo "
            "mark in 3D on title and closing scenes, and abstract shapes in its colors | more movement, a slow "
            "camera sway |",
            "| `characters` (by name only) | enables the `character` scene type: one or two animated people in a "
            "simple set who blink, breathe, change expression on cue and move their mouths while their own lines "
            "are voiced; thought bubbles for what they think | the same (reserved for richer acting) |",
            "",
            "## Scene types",
            "",
        ]
        for c in self.components.values():
            out += [f"### `{c.id}` · {c.name}", "", c.purpose, ""]
            if c.requires:
                out += [f"*Needs the `{c.requires}` motion layer; the planner offers it only when that's on.*", ""]
            if c.use_when:
                out.append("**Use when:** " + "; ".join(c.use_when) + ".")
            if c.avoid_when:
                out.append("**Avoid when:** " + "; ".join(c.avoid_when) + ".")
            out += ["", "| Field | Shape | Notes |", "|---|---|---|"]
            for k, v in c.fields.items():
                out.append(f"| `{k}` | `{v.describe()}` | {v.desc} |")
            out += ["", "**Reveal keys:** " + ", ".join(f"`{r.key.replace('.*', '.N')}`" for r in c.reveals), ""]
            out += ["| Layout | Formats | Description |", "|---|---|---|"]
            for lid, lv in c.layouts.items():
                out.append(
                    f"| `{lid}` | {', '.join(lv.get('formats', ['16:9', '9:16', '1:1']))} | {lv.get('desc', '')} |"
                )
            out += [
                "",
                "<details><summary>Example data</summary>",
                "",
                "```json",
                json.dumps(c.example, indent=2, ensure_ascii=False),
                "```",
                "",
                "</details>",
                "",
            ]
        return "\n".join(out)


_NONE = Component("", "", "", [], [], [], {}, [], {}, {}, [], HERE)


def _present(v) -> bool:
    return v not in (None, "", [], {})


def _check(spec: FieldSpec, v, where: str) -> list[str]:
    if not _present(v) and not isinstance(v, (int, float, bool)):
        return [] if spec.optional else [f"{where} is required"]
    t = spec.type
    if t == "text":
        if not isinstance(v, str):
            return [f"{where} must be text"]
        if spec.max and text_width(v) > spec.max * TOLERANCE:  # visual width: CJK counts 2, marks 0
            return [f"{where} is {text_width(v)} wide; max {spec.max}: '{v[:60]}'"]
    elif t == "list":
        if not isinstance(v, list):
            return [f"{where} must be a list"]
        if spec.min and len(v) < spec.min:
            return [f"{where} has {len(v)} entries; needs at least {spec.min}"]
        if spec.max and len(v) > spec.max:
            return [f"{where} has {len(v)} entries; max {spec.max}"]
        errs: list[str] = []
        for i, item in enumerate(v):
            errs += _check(spec.of, item, f"{where}[{i}]")
        return errs
    elif t == "object":
        if not isinstance(v, dict):
            return [f"{where} must be an object"]
        return _check_object(spec.fields, v, where)
    elif t == "enum":
        if v not in spec.values:
            return [f"{where} must be one of {spec.values}"]
    elif t in ("int", "number"):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (t == "int" and not float(v).is_integer()):
            return [f"{where} must be a {t}"]
        if spec.min is not None and v < spec.min or spec.max is not None and v > spec.max:
            return [f"{where} must be between {spec.min} and {spec.max}"]
    elif t == "icon":
        if not isinstance(v, str) or not re.fullmatch(r"[a-z0-9-]{1,40}", v):
            return [f"{where} must be an icon name like 'coffee' or 'shield-check'"]
    elif t == "image":
        if not isinstance(v, str) or not 0 < len(v) <= 2000:
            return [f"{where} must be an image reference: an https URL, upload:<id> or brand:<n>"]
    elif t == "animation":
        if not isinstance(v, str) or not 0 < len(v) <= 2000:
            return [f"{where} must be a Lottie reference: an https URL or upload:<id>"]
    elif t == "bool" and not isinstance(v, bool):
        return [f"{where} must be true or false"]
    return []


def _check_object(fields: dict[str, FieldSpec], data: dict, where: str) -> list[str]:
    if not isinstance(data, dict):
        return [f"{where} must be an object"]
    errs = [f"{where}.{k}: unknown field; known: {list(fields)}" for k in data if k not in fields]
    for k, spec in fields.items():
        errs += _check(spec, data.get(k), f"{where}.{k}")
    return errs


# ---------------------------------------------------------------- loading
def _load_component(d: Path) -> Component:
    m = json.loads((d / "component.json").read_text())
    return Component(
        id=m["id"],
        name=m["name"],
        purpose=m["purpose"],
        use_when=m.get("use_when", []),
        avoid_when=m.get("avoid_when", []),
        tags=m.get("tags", []),
        fields={k: FieldSpec.parse(v) for k, v in m["fields"].items()},
        reveals=[Reveal(r) if isinstance(r, str) else Reveal(**r) for r in m["reveals"]],
        layouts=m["layouts"],
        example=m["example"],
        example_beats=m.get("example_beats", []),
        dir=d,
        speakers=m.get("speakers", False),
        lipsync=m.get("lipsync", False),
        inverse_layouts=m.get("inverse_layouts", []),
        checks=m.get("checks", []),
        focus=m.get("focus"),
        requires=m.get("requires"),
        fonts=m.get("fonts", []),
        adapted_from=m.get("adapted_from"),
    )


@lru_cache(maxsize=4)
def load_catalog(root: str | None = None) -> Catalog:
    base = Path(root) if root else HERE
    comps = {}
    for d in sorted((base / "components").iterdir()):
        if (d / "component.json").exists():
            c = _load_component(d)
            comps[c.id] = c
    styles = {}
    for d in sorted((base / "styles").iterdir()):
        if (d / "style.json").exists():
            m = json.loads((d / "style.json").read_text())
            styles[m["id"]] = Style(m["id"], m["name"], m["description"], m.get("best_for", []), m, d)
    motions = {p.stem: p.read_text() for p in sorted((base / "assets" / "motion").glob("*.js"))}
    transitions = {}
    for p in sorted((base / "assets" / "transitions").glob("*.json")):
        m = json.loads(p.read_text())
        js = p.with_suffix(".js")
        transitions[m["id"]] = Transition(
            m["id"],
            m["name"],
            m["description"],
            m["kind"],
            m.get("duration", 0.5),
            js.read_text() if js.exists() else "",
            p.parent,
        )
    return Catalog(comps, styles, motions, transitions, base)
