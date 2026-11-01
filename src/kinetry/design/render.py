"""Render a v2 plan into a HyperFrames project (index.html + assets).

Deterministic: same plan + brand + timeline + fit levels -> same HTML -> same video.
Every text element is tagged with `data-field` (its path in the plan) and `data-max-lines`
from the component manifest, so the fit check can measure it and the repair loop can
shrink or rewrite exactly that field.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from ..brand import BrandKit, contrast, logo_is_legible, luminance, mix
from ..fonts import FontFiles
from ..images import ImageResolver
from ..timing import Timeline
from ..voice import CURSIVE_RTL, is_rtl, lang_code
from .catalog import Catalog, Component, load_catalog
from .depth import logo_mark, scene_models
from .icons import Icons
from .plan import SIZES, VideoPlan2
from .tokens import FORMAT, build_tokens, css_block

SCALES = [1.0, 0.92, 0.85, 0.78, 0.72]
FMT_CLASS = {"16:9": "fmt-16x9", "9:16": "fmt-9x16", "1:1": "fmt-1x1"}
DEFAULT_STYLE = "editorial"


@dataclass
class RenderInput:
    plan: VideoPlan2
    brand: BrandKit
    fonts: dict[str, FontFiles]  # display, body, accent (optional)
    timeline: Timeline
    fit: dict[str, int] = field(default_factory=dict)
    logo: tuple[str, bytes] | None = None
    catalog: Catalog | None = None
    icons: Icons | None = None
    images: object | None = None  # kinetry.images.ImageResolver; needed by scenes with image fields
    # vendored players for the heavier motion layers: {"three": dir with three.module.min.js + three.core.min.js,
    # "lottie": lottie_light.min.js}; only copied into projects that use them
    vendor: dict[str, Path] = field(default_factory=dict)
    mark: tuple[str, bytes] | None = None  # the brand's logo symbol (SVG), for the 3D stage
    # the brand's own 3D models: (kinetry.brand3d.Asset3D, path to its .glb)
    models: list = field(default_factory=list)


@dataclass
class Resolved:
    style: object
    motion: str
    transition: str
    fmt: str
    captions: bool


CAPTION_WORDS = {"16:9": 14, "9:16": 8, "1:1": 9}  # at most two lines in each format


# Scripts written without spaces between words (Chinese, Japanese) are split by character instead of by word.
CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]")
CLOSE = set("、。，．！？：；」』）》〉】〕…‥ー・”’!?,.:;)%")  # never starts a line or a caption
OPEN = set("「『（《〈【〔“‘(")  # never ends one


def is_cjk(text: str) -> bool:
    """Mostly unspaced CJK: more CJK characters than spaces."""
    return len(CJK.findall(text)) > max(4, text.count(" "))


def tokens(text: str) -> list[tuple[int, str, bool]]:
    """(start index, token, space before) for animation-sized units: words, or single CJK characters with
    their punctuation attached (opening marks to the next character, closing marks to the previous one)."""
    out: list[tuple[int, str, bool]] = []
    i, n, space, pending = 0, len(text), False, ""
    pstart = 0
    while i < n:
        ch = text[i]
        if ch.isspace():
            space, i = True, i + 1
            continue
        if CJK.match(ch) or ch in CLOSE or ch in OPEN:
            if ch in OPEN:
                pending, pstart = pending + ch, (pstart if pending else i)
            elif ch in CLOSE and out and not space and not pending:
                s, t, sp = out[-1]
                out[-1] = (s, t + ch, sp)
            else:
                out.append((pstart if pending else i, pending + ch, space))
                pending = ""
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and not CJK.match(text[j]) and text[j] not in OPEN:
                j += 1
            while j < n and text[j] in CLOSE and not CJK.match(text[j]):
                j += 1
            out.append((pstart if pending else i, pending + text[i:j], space))
            pending, i = "", j
        space = False
    if pending:
        out.append((pstart, pending, space))
    return out


def text_weight(text: str) -> int:
    """How long a piece of text takes to say, in units comparable within one language (words or characters)."""
    return len([t for t in tokens(text)]) if is_cjk(text) else len(text.split())


def _cjk_chunks(text: str, max_chars: int) -> list[str]:
    pieces = [p for p in re.split(r"(?<=[。！？!?])", text.replace(" ", "")) if p]
    out: list[str] = []
    for p in pieces:
        while len(p) > max_chars:  # one long sentence: break at a comma near the middle, else hard
            cut = max((p.rfind(c, 0, max_chars) for c in "、，,"), default=-1)
            cut = cut + 1 if cut >= max_chars // 3 else max_chars
            while cut < len(p) and p[cut] in CLOSE:
                cut += 1
            out.append(p[:cut])
            p = p[cut:]
        if out and len(out[-1]) + len(p) <= max_chars and len(p) < max_chars // 2:
            out[-1] += p
        elif p:
            out.append(p)
    return out


def caption_cues(tl, fmt: str) -> list[dict]:
    """Every caption on the timeline: the narration cut into caption-sized pieces, each timed across its
    beat by how long it takes to say. The burnt-in captions and the exported caption file both use this."""
    cues = []
    for ts in tl.scenes:
        for b in ts.beats:
            chunks = caption_chunks(b.caption, CAPTION_WORDS.get(fmt, 12))
            total_w = sum(text_weight(c) for c in chunks) or 1
            done = 0
            for j, text in enumerate(chunks):
                a = b.start + b.duration * done / total_w
                done += text_weight(text)
                last = j == len(chunks) - 1
                end = b.start + b.duration * done / total_w + (0.12 if last else -0.03)
                cues.append(
                    {
                        "id": f"cap{ts.index + 1}-{b.index + 1}-{j + 1}",
                        "start": round(a, 3),
                        "end": round(end, 3),
                        "text": text,
                        "scene": ts.index,
                        "beat": b.index,
                        "voice": b.voice,
                    }
                )
    return cues


def caption_chunks(text: str, max_words: int) -> list[str]:
    """Split narration into caption-sized pieces, preferring sentence and clause breaks."""
    if is_cjk(text):
        return _cjk_chunks(text.strip(), round(max_words * 2.2))
    words = text.split()
    if len(words) <= max_words:
        return [" ".join(words)] if words else []
    chunks: list[list[str]] = [[]]
    for w in words:
        cur = chunks[-1]
        cur.append(w)
        n = len(cur)
        if n >= max_words or (n >= 3 and w[-1] in ".?!") or (n >= max_words * 0.5 and w[-1] in ",;:"):
            chunks.append([])
    chunks = [c for c in chunks if c]
    if len(chunks) > 1 and len(chunks[-1]) < 3:  # no one- or two-word stragglers
        tail = chunks.pop()
        if len(chunks[-1]) + len(tail) <= max_words + 2:
            chunks[-1] += tail
        else:
            both = chunks.pop() + tail
            half = (len(both) + 1) // 2
            chunks += [both[:half], both[half:]]
    return [" ".join(c) for c in chunks]


def ambient_light(p, level: str) -> tuple[list[str], list[float]]:
    """Colors and peak opacities for the two kinds of light pool on one palette's ground.

    Dark text on a light ground gets pools of the brand colors. Light text on the brand color (inverse
    scenes) gets deeper shades of that color, which only add contrast. Light text on a dark ground gets
    brand-colored glow. Peaks go as high as the level asks while text over a pool keeps its contrast class:
    4.5:1 for body text, 3:1 for the secondary brand color (used only for large or decorative text).
    """
    want = {"subtle": 0.18, "rich": 0.3}.get(level, 0.0) + (0.06 if p.dark else 0)
    light_text = luminance(p.ink) > luminance(p.bg)
    if not light_text:
        colors = [p.fill, p.fill2]
    elif luminance(p.bg) < 0.04:  # a near-black ground: brand-colored glow
        colors = [p.fill, p.accent]
    else:
        colors = [mix(p.bg, "#000000", 0.45), mix(p.bg, "#000000", 0.28)]
    texts = []
    for t, cap in ((p.ink, 4.5), (p.muted, 4.5), (p.accent, 4.5), (p.fill2, 3.0)):
        base = contrast(t, p.bg)
        need = min(cap, 4.5 if base >= 4.5 else 3.0 if base >= 3.0 else 0.0)
        if need:
            texts.append((t, need * 1.02))  # headroom for anti-aliased edges

    def ok(ground: str) -> bool:
        return all(contrast(t, ground) >= need for t, need in texts)

    peaks = []
    for light in colors:
        a = want
        while a > 0 and not ok(mix(p.bg, light, a)):
            a = round(a - 0.01, 3)
        peaks.append(max(0.0, a))
    # pools drift and overlap: the two kinds stacked must still pass
    f = 1.0
    while f > 0 and not ok(mix(mix(p.bg, colors[0], peaks[0] * f), colors[1], peaks[1] * f)):
        f = round(f - 0.05, 3)
    return colors, [round(a * max(f, 0.0), 3) for a in peaks]


def _ambient(level: str, kind: str, light: tuple[list[str], list[float]]) -> str:
    """Markup for the ambient layer inside a scene's ground. Colors come from `ambient_light` for this
    scene's ground; positions, drift and opacity are set by fx.js (seeded per scene)."""
    (c1, c2), (a1, a2) = light
    blobs = 3 if level == "subtle" else 4
    parts = [f'<i class="ab ab{i}"></i>' for i in range(blobs)]
    if kind == "grid":
        parts.insert(0, '<i class="ag"></i>')
    if level == "rich":
        parts += [f'<i class="pt pt{i}"></i>' for i in range(16)]
    style = f"--amb1:{c1};--amb2:{c2};--amb-a1:{a1};--amb-a2:{a2}"
    return f'<div class="amb amb-{kind}" style="{style}" aria-hidden="true">{"".join(parts)}</div>'


def settled_times(plan: VideoPlan2, tl: Timeline, cat: Catalog | None = None) -> list[float]:
    """One moment per scene when everything is revealed and the outgoing transition hasn't started
    (QA frames, gallery snapshots)."""
    cat = cat or load_catalog()
    tr = cat.transitions.get(resolve_design(plan, cat).transition)
    lead = (tr.duration / 2 if tr and tr.kind != "cut" else 0) + 0.3
    out = []
    for k, sc in enumerate(tl.scenes):
        margin = 0.8 if k == len(tl.scenes) - 1 else lead  # the last scene fades the whole frame
        out.append(round(max(sc.start + 0.5, sc.end - margin), 3))
    return out


def resolve_design(plan: VideoPlan2, cat: Catalog) -> Resolved:
    d = plan.design
    style = cat.styles.get(d.style or DEFAULT_STYLE) or cat.styles[DEFAULT_STYLE]
    motion = d.motion if d.motion in cat.motions else style.motion
    transition = d.transition if d.transition in cat.transitions else style.transition
    fmt = d.resolved_format()
    return Resolved(style, motion, transition, fmt, d.resolved_captions())


def _get(d, path: str):
    cur = d
    for p in path.split("."):
        if cur is None:
            return None
        cur = (
            cur[int(p)]
            if p.isdigit() and isinstance(cur, list) and int(p) < len(cur)
            else (cur.get(p) if isinstance(cur, dict) else None)
        )
    return cur


def _script_json(obj) -> str:
    """JSON that is safe inside an inline <script>: no '</script>', no HTML comment openers."""
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _find(text: str, mark: str | None) -> tuple[int, int]:
    """(start, end) of `mark` in `text`, case-insensitive, in `text`'s own indices; (-1, -1) if absent."""
    m = re.search(re.escape(mark.strip()), text, re.I) if mark and mark.strip() else None
    return (m.start(), m.end()) if m else (-1, -1)


RTL_CHARS = re.compile(r"[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")
LTR_STRONG = re.compile(r"[A-Za-z0-9\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff]")


def _ltr_runs(toks: list[tuple[int, str, bool]], text: str) -> list[tuple[int, str, bool]]:
    """In right-to-left text, each word box is placed right to left, so a run of Latin words ("Microsoft Teams",
    "v2.0") would come out reversed. Keep each such run in one box; it then reads left to right inside."""
    out: list[tuple[int, str, bool]] = []
    prev_ltr = False
    for start, w, space in toks:
        ltr = bool(LTR_STRONG.search(w)) and not RTL_CHARS.search(w)
        if ltr and prev_ltr and out:
            s0, _, sp0 = out[-1]
            out[-1] = (s0, text[s0 : start + len(w)], sp0)
        else:
            out.append((start, w, space))
        prev_ltr = ltr
    return out


def _words(text: str, mark: str | None = None, rtl: bool = False) -> str:
    """Wrap each word (each character, for Chinese and Japanese) for masked reveals; words inside `mark` get
    the highlight class. In right-to-left text, runs of Latin words stay together (see _ltr_runs)."""
    lo, hi = _find(text, mark)
    out = []
    toks = tokens(text)
    for start, w, space in _ltr_runs(toks, text) if rtl else toks:
        end = start + len(w)
        hl = lo >= 0 and start < hi and end > lo
        out.append(
            (" " if space and out else "") + f'<span class="w{" hlw" if hl else ""}"><span>{escape(w)}</span></span>'
        )
    return "".join(out)


def _marked(text: str, mark: str | None) -> str:
    lo, hi = _find(text, mark)
    if lo < 0:
        return escape(text)
    return f'{escape(text[:lo])}<span class="hl">{escape(text[lo:hi])}</span>{escape(text[hi:])}'


class SceneContext:
    """Helpers a component template sees."""

    def __init__(
        self, si: int, comp: Component, data: dict, fit: dict, icons: Icons, fmt: str, layout: str, rtl: bool = False
    ):
        self.si, self.comp, self.d, self.fit, self.icons, self.fmt, self.L = si, comp, data, fit, icons, fmt, layout
        self.rtl = rtl
        self.images = None
        self.lotties: dict[str, str] = {}

    def img(self, path: str) -> str:
        """Project-relative src of an image field (copied into the project's assets)."""
        ref = _get(self.d, path)
        if not ref:
            return ""
        return self.images.src(str(ref))

    def lottie(self, path: str) -> str:
        """Id of the <script type="application/json"> holding an animation field's Lottie (see write_project)."""
        ref = _get(self.d, path)
        if not ref:
            return ""
        lid = f"lottie-{self.si + 1}-{len(self.lotties) + 1}"
        self.lotties[lid] = self.images.lottie_json(str(ref))
        return lid

    def get(self, path: str):
        return _get(self.d, path)

    def has(self, path: str) -> bool:
        return _get(self.d, path) not in (None, "", [], {})

    def t(
        self,
        path: str,
        role: str | None = None,
        tag: str = "div",
        cls: str = "",
        split: bool | None = None,
        mark: str | None = None,
        lines: int | None = None,
        attrs: str = "",
    ) -> Markup:
        val = _get(self.d, path)
        if val in (None, ""):
            return Markup("")
        val = str(val)
        spec = self.comp.spec_for(path)
        role = role or (spec.role if spec else "body")
        lines = lines or (spec.lines if spec else 2)
        fp = f"scenes.{self.si}.data.{path}"
        # a field's own fit level, or its scene's (set when the scene as a whole doesn't fit)
        lvl = min(max(self.fit.get(fp, 0), self.fit.get(f"scenes.{self.si}", 0)), len(SCALES) - 1)
        style = f' style="--fit:{SCALES[lvl]}"' if lvl else ""
        split = role in ("display", "h2") if split is None else split
        inner = _words(val, mark, self.rtl) if split else _marked(val, mark)
        return Markup(
            f'<{tag} class="tx r-{role} {cls}" data-field="{fp}" data-max-lines="{lines}"{style}{attrs}>{inner}</{tag}>'
        )

    def icon(self, name: str | None, cls: str = "") -> Markup:
        return Markup(self.icons.svg(name, cls))

    @staticmethod
    def num(i: int, width: int = 2) -> str:
        return str(i).zfill(width)


def _env(cat: Catalog) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(cat.root / "components")),
        autoescape=select_autoescape(default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def schedule(comp: Component, data: dict, ts, lead: float = 0.35) -> dict[str, float]:
    """Reveal time for every concrete key: the beat that shows it, or an idle slot at the scene start."""
    keys = comp.keys(data)
    R: dict[str, float] = {}
    idle = []
    for k in keys:
        base = k.split(".")[0]
        if k in ts.reveals:
            R[k] = ts.reveals[k]
        elif base in ts.reveals and base != k:
            R[k] = round(ts.reveals[base] + 0.12 * int(k.split(".")[1]), 3)
        else:
            idle.append(k)
    idle.sort(key=lambda k: (0 if k in ("headline", "title", "term", "quote", "value") else 1, keys.index(k)))
    for n, k in enumerate(idle):
        R[k] = round(ts.start + lead + 0.22 * n, 3)
    for k, t in ts.reveals.items():  # whole-list keys (e.g. 'steps') stay addressable
        R.setdefault(k, t)
    return R


def write_project(ri: RenderInput, out_dir: Path, gsap_js: Path) -> Path:
    cat = ri.catalog or load_catalog()
    icons = ri.icons or Icons()
    plan, tl = ri.plan, ri.timeline
    rd = resolve_design(plan, cat)
    style = rd.style
    tok = build_tokens(ri.brand, style.tokens, rd.fmt, rd.captions)
    fx = plan.design.effects.resolved()
    fx_on = plan.design.effects.any()
    amb_kind = style.tokens.get("ambient", "blobs")
    amb_norm = ambient_light(tok["palette"], fx["ambient"])
    amb_inv = ambient_light(tok["inverse_palette"], fx["ambient"])
    W, H = tok["size"]
    pal = tok["palette"]

    out_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("assets/fonts", "assets/js", "audio"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy(gsap_js, out_dir / "assets" / "js" / "gsap.min.js")

    logo_src = None
    if ri.logo:
        name, data = ri.logo
        legible = not name.endswith(".svg") or logo_is_legible(data.decode(errors="ignore"), pal.bg)
        if legible:
            (out_dir / "assets" / name).write_bytes(data)
            logo_src = f"assets/{name}"

    faces = []
    for role, ff in ri.fonts.items():
        if ff is None:
            continue
        for key, src in ff.files.items():
            dest = out_dir / "assets" / "fonts" / f"{role}-{key}.woff2"
            shutil.copy(src, dest)
            faces.append(
                {
                    "family": f"TF {role.capitalize()}",
                    "src": f"assets/fonts/{dest.name}",
                    "weight": key.replace("italic", "") or "400",
                    "style": "italic" if "italic" in key else "normal",
                }
            )

    env = _env(cat)
    trans = cat.transitions[rd.transition]
    n_sc = len(plan.scenes)
    inverse_types = set(style.tokens.get("inverse_scenes", []))
    scenes_html, spec_scenes, used = [], [], []
    lotties: dict[str, str] = {}
    # without a resolver only bundled samples and public https images resolve (no local files)
    images = (ri.images or ImageResolver(public_only=True)).bind(out_dir / "assets")
    for si, (sc, ts) in enumerate(zip(plan.scenes, tl.scenes, strict=True)):
        comp = cat.components[sc.type]
        if sc.type not in used:
            used.append(sc.type)
        layout = sc.layout if sc.layout in comp.layouts else (comp.layouts_for(rd.fmt) or list(comp.layouts))[0]
        ctx = SceneContext(si, comp, sc.data, ri.fit, icons, rd.fmt, layout, is_rtl(plan.design.lang))
        ctx.images = images
        body = env.get_template(f"{comp.id}/template.html").render(
            d=sc.data,
            L=layout,
            fmt=rd.fmt,
            port=rd.fmt == "9:16",
            sq=rd.fmt == "1:1",
            land=rd.fmt == "16:9",
            t=ctx.t,
            icon=ctx.icon,
            has=ctx.has,
            get=ctx.get,
            num=ctx.num,
            img=ctx.img,
            lottie=ctx.lottie,
            i=si,
            style=style.id,
        )
        lotties.update(ctx.lotties)
        # a component with inverse layouts decides per layout; otherwise the style decides per scene type
        inv = layout in comp.inverse_layouts if comp.inverse_layouts else sc.type in inverse_types
        overlap = trans.duration if trans.kind == "overlap" and si < n_sc - 1 else 0.0
        sid = f"s{si + 1}"
        stage = f'<div class="stage">{body}</div>'
        if fx["camera"] != "off":  # two camera rigs: a slow move, and a punch-in toward the key moment
            stage = f'<div class="cam"><div class="cam2">{stage}</div></div>'
        ground = _ambient(fx["ambient"], amb_kind, amb_inv if inv else amb_norm) if fx["ambient"] != "off" else ""
        scenes_html.append(
            f'<section id="{sid}" class="clip scene c-{comp.id} l-{layout}{" inv" if inv else ""}" '
            f'data-start="{ts.start}" data-duration="{round(ts.duration + overlap, 3)}" data-track-index="{10 + si}">'
            f'<div class="sc"><div class="ground">{ground}</div>{stage}</div></section>'
        )
        speakers = sc.data.get("speakers") or {}
        spec_scenes.append(
            {
                "id": sid,
                "type": comp.id,
                "layout": layout,
                "start": ts.start,
                "end": round(ts.end, 3),
                "R": schedule(comp, sc.data, ts),
                "B": sorted(ts.reveals),  # keys a beat names explicitly (others are scheduled)
                **(
                    {
                        "focus": comp.focus,  # where the camera punches in (rich)
                        # beat window per revealed key: kinetic text spreads its words across the sentence
                        "W": {k: [b.start, round(b.start + b.duration, 3)] for b in ts.beats for k in b.show},
                    }
                    if fx_on
                    else {}
                ),
                "inv": inv,
                "eyebrow": bool(sc.data.get("eyebrow")),
                "n": {k: len(v) for k, v in sc.data.items() if isinstance(v, list)},
                "speak": [[b.voice, b.start, round(b.start + b.duration, 3)] for b in ts.beats if b.voice in speakers],
                **({"mouth": _mouths(ts, speakers)} if comp.lipsync else {}),
                "data": _js_data(comp, sc.data),
            }
        )

    # transitions
    trans_specs, overlays, subcomps = [], [], []
    for k in range(n_sc - 1):
        at = tl.scenes[k + 1].start
        trans_specs.append(
            {"name": trans.id, "from": f"s{k + 1}", "to": f"s{k + 2}", "at": at, "d": trans.duration, "k": k}
        )
        if trans.id == "wipe":
            overlays.append(f'<div class="tr-panel" id="tr-{k}"></div>')
        elif trans.id == "scan":
            overlays.append(f'<div class="tr-scan" id="tr-{k}"></div>')
        elif trans.kind == "subcomp":
            # one file and one id per instance: HyperFrames keys timelines by composition id, and the
            # vendored markup uses element ids, so shared copies would fight over both
            cid = f"tf-{trans.id}-{k}"
            subcomps.append(
                f'<div data-composition-id="{cid}" data-composition-src="compositions/{cid}.html" '
                f'data-start="{round(max(0, at - trans.duration / 2), 3)}" data-duration="{trans.duration}" '
                f'data-track-index="{60 + k}" data-width="{W}" data-height="{H}"></div>'
            )
    if subcomps:
        (out_dir / "compositions").mkdir(exist_ok=True)
        src = (trans.dir / f"{trans.id}.html").read_text()
        src = (
            src.replace("{{W}}", str(W))
            .replace("{{H}}", str(H))
            .replace("{{COLOR}}", pal.fill)
            .replace("{{BANDS}}", str(max(6, round(H / 155))))
        )
        for k in range(len(subcomps)):
            cid = f"tf-{trans.id}-{k}"
            inst = src.replace("{{ID}}", cid).replace("hw-st-", f"hw-st{k}-")
            (out_dir / "compositions" / f"{cid}.html").write_text(inst)

    # captions + audio
    caps, caps_html, audio = [], [], []
    for ts in tl.scenes:
        for b in ts.beats:
            if b.audio is not None:
                dest = out_dir / "audio" / b.audio.name
                if b.audio.resolve() != dest.resolve():
                    shutil.copy(b.audio, dest)
                audio.append(
                    {
                        "id": f"a{ts.index + 1}-{b.index + 1}",
                        "src": f"audio/{b.audio.name}",
                        "start": b.start,
                        "dur": b.duration,
                    }
                )
    if rd.captions:
        for cue in caption_cues(tl, rd.fmt):
            caps.append({"id": cue["id"], "a": cue["start"], "b": cue["end"]})
            caps_html.append(f'<div class="cap" id="{cue["id"]}">{escape(cue["text"])}</div>')

    total = tl.duration
    spec = {
        "fmt": rd.fmt,
        "W": W,
        "H": H,
        "total": total,
        "motion": rd.motion,
        "chrome": style.chrome,
        "scenes": spec_scenes,
        "trans": trans_specs,
        "caps": caps,
        **({"fx": {**fx, "kind": amb_kind}} if fx_on else {}),
    }
    css = [
        "\n".join(
            f'@font-face {{ font-family: "{f["family"]}"; src: url("{f["src"]}") format("woff2"); '
            f"font-weight: {f['weight']}; font-style: {f['style']}; }}"
            for f in faces
        ),
        css_block(":root", tok["root"]),
        css_block(".inv", tok["inverse"]),
        (cat.root / "assets" / "base.css").read_text(),
        (style.dir / "style.css").read_text() if (style.dir / "style.css").exists() else "",
    ]
    for cid in used:
        p = cat.components[cid].dir / "style.css"
        if p.exists():
            css.append(p.read_text())
    js = [(cat.root / "assets" / "runtime.js").read_text(), cat.motions["minimal"]]
    if rd.motion != "minimal":
        js.append(cat.motions[rd.motion])
    if trans.js:  # a transition can ship its own TF.transition(...) code next to its manifest
        js.append(trans.js)
    if fx_on:  # motion layers: nothing of this reaches a video that doesn't ask for it
        css.append((cat.root / "assets" / "fx" / "fx.css").read_text())
        js.append((cat.root / "assets" / "fx" / "fx.js").read_text())
    head_js = ""
    if lotties:  # the caller's Lottie files, played by lottie-web's light player (no expressions)
        src = ri.vendor.get("lottie")
        if not src or not Path(src).is_file():
            raise RuntimeError("Lottie animations need lottie-web: run `kinetry setup` once")
        shutil.copy(src, out_dir / "assets" / "js" / "lottie_light.min.js")
        # hidden from HyperFrames' own Lottie discovery, which would play them on the composition clock;
        # TF.lottie registers scene-timed players instead
        head_js = (
            '<script src="assets/js/lottie_light.min.js"></script>\n'
            "<script>window.__tfLottie = window.lottie; try { delete window.lottie; } catch (e) { window.lottie = undefined; }</script>"
        )
        js.append((cat.root / "assets" / "fx" / "lottie.js").read_text())
    depth_html = depth_js = ""
    if fx["depth"] != "off":  # the 3D stage (Three.js), rendered from the composition clock on hf-seek
        tdir = ri.vendor.get("three")
        if not tdir or not (Path(tdir) / "three.module.min.js").is_file():
            raise RuntimeError("The 3D stage needs three.js: run `kinetry setup` once")
        for f in ("three.module.min.js", "three.core.min.js"):
            shutil.copy(Path(tdir) / f, out_dir / "assets" / "js" / f)
        # loaders for the logo in 3D and the brand's models, pointed at the vendored modules instead of "three"
        jsm = Path(tdir).parent / "examples" / "jsm"
        for f in ("loaders/SVGLoader.js", "loaders/GLTFLoader.js", "utils/BufferGeometryUtils.js",
                  "environments/RoomEnvironment.js"):  # fmt: skip
            if not (jsm / f).is_file():
                raise RuntimeError("The 3D stage needs three.js's example modules: run `kinetry setup` once")
            text = (jsm / f).read_text().replace("from 'three';", "from './three.module.min.js';")
            text = text.replace("from '../utils/BufferGeometryUtils.js';", "from './BufferGeometryUtils.js';")
            (out_dir / "assets" / "js" / Path(f).name).write_text(text)
        hero = {
            i
            for i, x in enumerate(spec_scenes)
            if x["type"] in ("title", "closer") and x["layout"] not in ("center", "band") and not x["inv"]
        }
        by_id = {a.id: (a, Path(p)) for a, p in ri.models}
        mark = logo_mark(ri.mark, ri.logo)
        picks, spare = scene_models(plan, [a for a, _ in ri.models], hero, has_mark=bool(mark))
        ship = sorted({x for ids in picks.values() for x in ids} | set(spare))
        models = {}
        if ship:
            (out_dir / "assets" / "3d").mkdir(parents=True, exist_ok=True)
        for aid in ship:
            a, src = by_id[aid]
            shutil.copy(src, out_dir / "assets" / "3d" / f"{aid}.glb")
            models[aid] = {"src": f"assets/3d/{aid}.glb", "role": a.role, "anims": len(a.animations)}
        (out_dir / "assets" / "fx").mkdir(parents=True, exist_ok=True)
        shutil.copy(cat.root / "assets" / "fx" / "depth.mjs", out_dir / "assets" / "fx" / "depth.mjs")
        css.append((cat.root / "assets" / "fx" / "depth.css").read_text())
        depth_html = (
            f'<div class="clip depth" data-start="0" data-duration="{total}" data-track-index="1">'
            f'<canvas id="tf-depth" width="{W}" height="{H}"></canvas></div>'
        )
        dspec = {
            "W": W,
            "H": H,
            "level": fx["depth"],
            "seed": plan.design.seed,
            "colors": [pal.fill, pal.accent, pal.fill2, pal.surface2],
            "bg": pal.bg,
            "dark": pal.dark,
            "rtl": is_rtl(plan.design.lang),
            "caps": bool(rd.captions),
            "mark": mark,
            "models": models,
            "spare": spare,
            "scenes": [
                {
                    "id": x["id"],
                    "start": x["start"],
                    "end": x["end"],
                    "inv": x["inv"],
                    # title and closing scenes that leave one side free get a hero model or the mark in 3D
                    "hero": i in hero,
                    "models": picks.get(i, []),
                }
                for i, x in enumerate(spec_scenes)
            ],
        }
        depth_js = (
            f"<script>window.TF_DEPTH = {_script_json(dspec)};</script>\n"
            '<script type="module" src="assets/fx/depth.mjs"></script>'
        )
    for cid in used:
        p = cat.components[cid].dir / "motion.js"
        if p.exists():
            js.append(p.read_text())
    rtl = is_rtl(plan.design.lang)
    root_cls = " ".join(
        [
            FMT_CLASS[rd.fmt],
            f"st-{style.id}",
            f"mo-{rd.motion}",
            "caps-on" if rd.captions else "caps-off",
            f"caps-{style.tokens.get('captions', 'bar')}",
            "dark" if pal.dark else "light",
            *(["rtl", *(["cursive"] if lang_code(plan.design.lang) in CURSIVE_RTL else [])] if rtl else []),
            *(
                [
                    f"fx-cam-{fx['camera']}",
                    f"fx-kin-{fx['kinetic']}",
                    f"fx-amb-{fx['ambient']}",
                    f"fx-ill-{fx['illustration']}",
                    f"fx-dep-{fx['depth']}",
                    f"fx-chr-{fx['characters']}",
                ]
                if fx_on
                else []
            ),
        ]
    )
    html = f"""<!doctype html>
<html lang="{escape(plan.design.lang)}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={W}, height={H}" />
<title>{escape(plan.title)}</title>
<script src="assets/js/gsap.min.js"></script>
{head_js}
<style>
{chr(10).join(css)}
</style>
</head>
<body>
<div id="root" class="{root_cls}" data-composition-id="main" data-start="0" data-duration="{total}" data-width="{W}" data-height="{H}">
{depth_html}
{chr(10).join(scenes_html)}
<div class="clip chrome" data-start="0" data-duration="{total}" data-track-index="40">{_chrome(style.chrome, plan, ri.brand, logo_src, n_sc)}</div>
{f'<div class="clip caps" data-start="0" data-duration="{total}" data-track-index="41">{"".join(caps_html)}</div>' if caps_html else ""}
{f'<div class="clip trs" data-start="0" data-duration="{total}" data-track-index="42">{"".join(overlays)}</div>' if overlays else ""}
{chr(10).join(subcomps)}
{chr(10).join(f'<audio id="{a["id"]}" src="{a["src"]}" data-start="{a["start"]}" data-duration="{a["dur"]}" data-track-index="90" data-volume="1"></audio>' for a in audio)}
</div>
{chr(10).join(f'<script type="application/json" id="{k}">{v.replace("<", chr(92) + "u003c")}</script>' for k, v in lotties.items())}
<script>
{chr(10).join(js)}
TF.run({_script_json(spec)});
</script>
{depth_js}
</body>
</html>
"""
    (out_dir / "index.html").write_text(html)
    (out_dir / "hyperframes.json").write_text(
        json.dumps({"paths": {"assets": "assets"}, "media": {"autoProxy": True}}, indent=2)
    )
    (out_dir / "meta.json").write_text(json.dumps({"id": out_dir.name, "name": plan.title}, indent=2))
    (out_dir / "design.json").write_text(
        json.dumps(
            {
                "style": style.id,
                "motion": rd.motion,
                "transition": rd.transition,
                "format": rd.fmt,
                "captions": rd.captions,
                "layouts": [s["layout"] for s in spec_scenes],
            },
            indent=2,
        )
    )
    return out_dir / "index.html"


def _mouths(ts, speakers: dict) -> dict[str, list]:
    """Mouth shapes per speaker, at absolute times, from each of their voiced lines (previews have no audio)."""
    try:
        from ..visemes import mouth_cues
    except ImportError:  # numpy/soundfile come with the local voice extra; without them, the simple mouth
        return {}

    out: dict[str, list] = {}
    for b in ts.beats:
        if b.voice in speakers and b.audio and Path(b.audio).exists():
            try:
                cues = mouth_cues(Path(b.audio), b.say)
            except ImportError:
                return {}
            out.setdefault(b.voice, []).extend([round(b.start + t, 3), v] for t, v in cues)
    return out


def _js_data(comp: Component, data: dict) -> dict:
    """Small non-text values a component's motion needs (counter targets, indices)."""
    out = {}
    for k, spec in comp.fields.items():
        if spec.type in ("int", "number", "bool", "enum") and k in data:
            out[k] = data[k]
    if "bars" in data:
        out["bars"] = [b.get("value", 0) for b in data["bars"]]
    if "lines" in data and comp.speakers:
        out["who"] = [ln.get("who") for ln in data["lines"]]
    if "callouts" in data:
        out["targets"] = [c.get("target") for c in data["callouts"]]
    return out


def _chrome(kind: str, plan: VideoPlan2, kit: BrandKit, logo: str | None, n: int) -> str:
    left = (
        f'<span data-field="chrome_left" data-max-lines="1">{escape(plan.chrome_left)}</span>'
        if plan.chrome_left
        else ""
    )
    right = (
        f'<span data-field="chrome_right" data-max-lines="1">{escape(plan.chrome_right)}</span>'
        if plan.chrome_right
        else ""
    )
    mark = f'<img class="logo" src="{logo}" alt="" />' if logo else '<span class="dot"></span>'
    counter = "".join(f'<span class="cn{i}">{i + 1:02d} / {n:02d}</span>' for i in range(n))
    ticks = "".join(f'<i class="tick"><b class="tk{i}"></b></i>' for i in range(n))
    if kind == "none":
        return ""
    if kind == "rule":
        return (
            f'<div class="top"><span class="brandmark">{mark}{left}</span>{right}</div><div class="hair"></div>'
            f'<div class="bottom"><div class="count">{counter}</div></div>'
        )
    if kind == "status":  # the brand's logo when it has one, else the status dot
        return f'<div class="top"><span class="brandmark">{mark}{left}</span>{right}</div><div class="bottom">{ticks}</div>'
    if kind == "wordmark":
        # no brand given (the built-in kit): the plan's own label is the better wordmark
        own = kit.name == "Kinetry default" and plan.chrome_left
        word = plan.chrome_left if own else kit.name
        field = ' data-field="chrome_left" data-max-lines="1"' if own else ""  # kit.name isn't plan copy
        name = mark if logo else f'<span class="wm"{field}>{escape(word)}</span>'
        return f'<div class="top"><span class="brandmark">{name}</span>{right if own else (left or right)}</div>'
    if kind == "corner":
        return f'<div class="top"><span class="brandmark">{mark}</span>{left}</div><div class="bottom"><div class="count">{counter}</div></div>'
    if kind == "line":
        return f'<div class="top"><span class="brandmark">{mark}{left}</span>{right}</div><div class="bottom"><div class="pline"><i class="pl"></i></div></div>'
    if kind == "navbar":
        # labels only when every one fits its slot on one line; otherwise bars alone (the count says where we are)
        w, _ = SIZES[plan.design.resolved_format()]
        slot = (w - 2 * FORMAT[plan.design.resolved_format()]["px"]) / max(1, n) - 10
        longest = max((len(s.nav or "") for s in plan.scenes), default=0)
        fs = min(24 * FORMAT[plan.design.resolved_format()]["k"], slot / max(1, longest) / 0.62)
        show = fs >= 15
        navs = "".join(
            f'<div class="nav"><div class="bar"><i class="nf{i}"></i></div><span class="lbl nl{i}" data-field="scenes.{i}.nav" '
            f'data-max-lines="1">{escape(s.nav or "")}</span></div>'
            if show
            else f'<div class="nav"><div class="bar"><i class="nf{i}"></i></div></div>'
            for i, s in enumerate(plan.scenes)
        )
        style = f' style="--fs-nav:{fs:.1f}px"' if show else ""
        return (
            f'<div class="top"><span class="brandmark">{mark}{left}</span>{right}</div>'
            f'<div class="bottom"{style}>{navs}</div>'
        )
    if kind == "bar":
        return f'<div class="top"><span class="brandmark">{mark}{left}</span>{right}</div><div class="bottom">{ticks}</div>'
    return ""
