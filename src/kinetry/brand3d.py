"""A brand's own 3D assets, and the agent that understands them.

Companies can share 3D models of their products, vehicles, mascots or logo (glTF binary, .glb). They're kept
with the brand pack (`assets3d/` + `assets3d.json`) and shown on the 3D stage (`design.effects.depth`) where a
scene leaves room. Nothing here is specific to any business: what an asset is and when to use it comes from
the asset itself (its names, parts, colors, size and built-in animations) and from what the brand says about it.

The agent:
  - checks a file before it's kept: GLB only, 25 MB, everything embedded (no external files are ever
    fetched while rendering), no compression extensions that need extra decoders (Draco, meshopt, Basis);
  - reads it: meshes, materials and their colors, size, triangle count, animations;
  - describes it: a sentence and tags from a model when one is configured, else from the names inside;
  - extracts what it can from the brand's website: 3D models the site links to, and the logo's symbol cut
    out of a logo that pairs a symbol with a wordmark (so it can be shown in 3D on its own);
  - picks, per video, which asset appears on which scene, matching tags to what each scene says.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

MAX_GLB_BYTES = 25 * 1024 * 1024
NEEDS_DECODER = {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_texture_basisu"}
ASSET_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


class AssetError(ValueError):
    pass


class Asset3D(BaseModel):
    id: str
    file: str  # inside the brand pack's assets3d/
    name: str = Field("", max_length=80)
    about: str = Field("", max_length=300, description="what it is, in one sentence")
    tags: list[str] = Field(default_factory=list, max_length=12)
    role: Literal["hero", "prop", "logo"] = "prop"  # hero/logo: title and closing scenes; prop: anywhere with room
    animations: list[str] = Field(default_factory=list)
    facts: dict = Field(default_factory=dict)
    source: str = ""  # "upload", "cli", or the page it came from
    use: bool = True


# ---------------------------------------------------------------- reading and checking a GLB
def read_glb(data: bytes) -> dict:
    """The glTF JSON of a GLB file, after the container checks."""
    if len(data) > MAX_GLB_BYTES:
        raise AssetError("3D model is larger than 25 MB")
    if len(data) < 20 or data[:4] != b"glTF":
        raise AssetError("not a binary glTF (.glb) file; export your model as .glb")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise AssetError(f"glTF version {version} isn't supported (needs 2.0)")
    if length > len(data):
        raise AssetError("the .glb file is truncated")
    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:  # "JSON"
        raise AssetError("the .glb file has no JSON chunk")
    try:
        return json.loads(data[20 : 20 + chunk_len].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise AssetError("the .glb file's JSON is unreadable") from e


def check_glb(data: bytes) -> dict:
    """Validate a GLB and return facts about it (no rendering needed)."""
    g = read_glb(data)
    required = set(g.get("extensionsRequired") or [])
    bad = sorted(required & NEEDS_DECODER)
    if bad:
        raise AssetError(f"the model uses {', '.join(bad)}, which needs a decoder; export it without compression")
    for i, b in enumerate(g.get("buffers") or []):
        uri = b.get("uri")
        if uri and not uri.startswith("data:"):
            raise AssetError(f"buffer {i} points to an external file ({uri[:60]}); export everything embedded (.glb)")
    for i, im in enumerate(g.get("images") or []):
        uri = im.get("uri")
        if uri and not uri.startswith("data:"):
            raise AssetError(f"texture {i} points to an external file ({uri[:60]}); export with embedded textures")
    if not g.get("meshes"):
        raise AssetError("the model has no meshes")

    accessors = g.get("accessors") or []
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    tris = 0
    for m in g["meshes"]:
        for p in m.get("primitives") or []:
            pos = (p.get("attributes") or {}).get("POSITION")
            if isinstance(pos, int) and pos < len(accessors):
                a = accessors[pos]
                if len(a.get("min") or []) == 3 and len(a.get("max") or []) == 3:
                    lo = [min(x, y) for x, y in zip(lo, a["min"], strict=True)]
                    hi = [max(x, y) for x, y in zip(hi, a["max"], strict=True)]
            idx = p.get("indices")
            if isinstance(idx, int) and idx < len(accessors):
                tris += accessors[idx].get("count", 0) // 3
            elif isinstance(pos, int) and pos < len(accessors):
                tris += accessors[pos].get("count", 0) // 3
    size = [round(b - a, 4) for a, b in zip(lo, hi, strict=True)] if lo[0] != float("inf") else []
    colors = []
    for mat in g.get("materials") or []:
        f = ((mat.get("pbrMetallicRoughness") or {}).get("baseColorFactor") or [])[:3]
        if len(f) == 3:
            colors.append("#" + "".join(f"{round(max(0, min(1, c)) ** (1 / 2.2) * 255):02x}" for c in f))
    names = lambda key: [x.get("name") for x in g.get(key) or [] if x.get("name")][:30]  # noqa: E731
    return {
        "bytes": len(data),
        "meshes": names("meshes"),
        "nodes": names("nodes"),
        "materials": names("materials"),
        "colors": colors[:12],
        "size": size,
        "triangles": tris,
        "textures": len(g.get("textures") or []),
        "animations": [a.get("name") or f"animation {i + 1}" for i, a in enumerate(g.get("animations") or [])],
        "generator": (g.get("asset") or {}).get("generator", "")[:80],
    }


# ---------------------------------------------------------------- describing
GENERIC = {
    "mesh", "meshes", "node", "nodes", "object", "objects", "material", "materials", "mat", "default", "scene",
    "root", "group", "geometry", "primitive", "cube", "plane", "cylinder", "sphere", "polysurface", "shape",
    "body", "part", "model", "lod", "lod0", "lod1", "copy", "new", "final", "export", "untitled", "armature",
    "texture", "glb", "gltf", "v1", "v2", "the", "and", "with", "of", "thing", "item", "asset",
}  # fmt: skip
LOGO_WORDS = {"logo", "logomark", "mark", "brandmark", "emblem", "symbol", "icon", "monogram"}


def nice_name(stem: str) -> str:
    """'WaterBottle_v2' -> 'Water Bottle': a readable name from a file name."""
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem or "")
    s = re.sub(r"[_\-.]+", " ", s)
    s = re.sub(r"\b[vV]?\d+\b", "", s)
    return re.sub(r"\s+", " ", s).strip()[:60]


def words_in(*texts: str) -> list[str]:
    out = []
    for t in texts:
        t = re.sub(r"([a-z])([A-Z])", r"\1 \2", t or "")
        for w in re.split(r"[^A-Za-z]+", t.lower()):
            if len(w) > 2 and w not in GENERIC and not re.fullmatch(r"[a-z]?\d+", w):
                out.append(w)
    return out


def heuristic_description(name: str, facts: dict) -> tuple[str, list[str], str]:
    ws = words_in(name, *facts.get("nodes", []), *facts.get("meshes", []), *facts.get("materials", []))
    seen: list[str] = []
    for w in ws:
        if w not in seen:
            seen.append(w)
    tags = sorted(seen, key=lambda w: -ws.count(w))[:8]  # words the file repeats say most about it
    role = "logo" if set(tags) & LOGO_WORDS else "prop"
    anim = f", animated ({', '.join(facts['animations'][:2])})" if facts.get("animations") else ""
    what = name or (" ".join(tags[:3]) if tags else "3D model")
    return f"{what.strip().capitalize()}{anim}.", tags, role


DESCRIBE_SYSTEM = """You catalog a company's 3D models for its videos. From the facts below (file name, the names
of its parts and materials, colors, size, animations, and what the company said about it), write:
- about: one plain sentence saying what the object is
- tags: up to 8 lowercase words a video script about it would use (the object, its category, what it's for)
- role: "logo" for a logo or brand mark, "hero" for the company's main product or mascot, else "prop"
Say only what the facts support; if they don't say what it is, describe the shape and keep tags general.
Answer with JSON: {"about": str, "tags": [str], "role": "logo"|"hero"|"prop"}"""


def describe(name: str, facts: dict, *, note: str = "", llm=None, settings=None) -> tuple[str, list[str], str]:
    """(about, tags, role) for an asset: a model's reading when one is available, else the names inside it."""
    base = heuristic_description(name, facts)
    # a model only when the caller gave one or the operator configured one (KINETRY_LLM): never a fallback default
    import os

    if llm is None and not (settings is not None and os.environ.get("KINETRY_LLM")):
        return base
    try:
        from .agents import get_llm

        if settings is None:
            from .config import Settings

            settings = Settings()
        model = get_llm(settings, llm, 0.2)
        user = json.dumps({"file_name": name, "company_note": note, **facts}, default=str)[:6000]
        msg = model.invoke([{"role": "system", "content": DESCRIBE_SYSTEM}, {"role": "user", "content": user}])
        text = getattr(msg, "content", msg)
        text = text if isinstance(text, str) else json.dumps(text)
        d = json.loads(text[text.find("{") : text.rfind("}") + 1])
        tags = [re.sub(r"[^a-z0-9 -]", "", str(t).lower())[:24] for t in d.get("tags") or []][:8]
        role = d.get("role") if d.get("role") in ("logo", "hero", "prop") else base[2]
        return str(d.get("about") or base[0])[:300], [t for t in tags if t] or base[1], role
    except Exception:  # noqa: BLE001  (no model, provider error, bad JSON): the names inside the file still help
        return base


# ---------------------------------------------------------------- the library inside a brand pack
def library_dir(brand_dir: str | Path) -> Path:
    return Path(brand_dir) / "assets3d"


def load_library(brand_dir: str | Path) -> list[Asset3D]:
    f = library_dir(brand_dir) / "assets3d.json"
    if not f.exists():
        return []
    items = [Asset3D.model_validate(x) for x in json.loads(f.read_text())]
    return [a for a in items if (library_dir(brand_dir) / a.file).is_file()]


def save_library(brand_dir: str | Path, items: list[Asset3D]) -> None:
    d = library_dir(brand_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "assets3d.json").write_text(json.dumps([a.model_dump() for a in items], indent=2))


def add_asset(
    brand_dir: str | Path,
    data: bytes,
    *,
    name: str = "",
    about: str = "",
    tags: list[str] | None = None,
    role: str | None = None,
    source: str = "upload",
    llm=None,
    settings=None,
) -> Asset3D:
    """Check, read, describe and store a GLB in the brand's library. The same file twice keeps one copy."""
    import hashlib

    facts = check_glb(data)
    digest = hashlib.sha256(data).hexdigest()[:12]
    items = load_library(brand_dir)
    for a in items:
        if a.file == f"{digest}.glb":
            return a
    auto_about, auto_tags, auto_role = describe(name, facts, note=about, llm=llm, settings=settings)
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "asset").lower()).strip("-")[:30] or "asset"
    aid = slug
    k = 2
    while any(a.id == aid for a in items):
        aid, k = f"{slug}-{k}", k + 1
    asset = Asset3D(
        id=aid,
        file=f"{digest}.glb",
        name=name[:80],
        about=(about or auto_about)[:300],
        tags=[t.strip().lower() for t in (tags or auto_tags) if t.strip()][:12],
        role=role if role in ("hero", "prop", "logo") else auto_role,
        animations=facts["animations"],
        facts=facts,
        source=source[:200],
    )
    d = library_dir(brand_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / asset.file).write_bytes(data)
    save_library(brand_dir, [*items, asset])
    return asset


def remove_asset(brand_dir: str | Path, asset_id: str) -> bool:
    items = load_library(brand_dir)
    keep = [a for a in items if a.id != asset_id]
    if len(keep) == len(items):
        return False
    gone = next(a for a in items if a.id == asset_id)
    if not any(a.file == gone.file for a in keep):
        (library_dir(brand_dir) / gone.file).unlink(missing_ok=True)
    save_library(brand_dir, keep)
    return True


def fetch_site_models(
    urls: list[str], brand_dir: str | Path, *, public_only: bool = True, page: str = "", settings=None
) -> list[str]:
    """Download the 3D models a brand's site links to into its library -> notes about what happened."""

    from .netguard import check_public_url
    from .netguard import client as make_client

    notes = []
    for url in urls[:4]:
        try:
            check_public_url(url, allow_private=not public_only, what="3D model URL")
            with make_client(public_only, follow_redirects=True, timeout=60) as c:
                with c.stream("GET", url) as r:
                    r.raise_for_status()
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > MAX_GLB_BYTES:
                            raise AssetError("larger than 25 MB")
            name = nice_name(Path(url.split("?")[0]).stem)
            a = add_asset(brand_dir, bytes(buf), name=name, source=page or url, settings=settings)
            notes.append(f"3D model from the site: {a.id} ({a.about})")
        except Exception as e:  # noqa: BLE001  (one bad file doesn't stop the brand)
            notes.append(f"skipped 3D model {url[:80]}: {str(e)[:120]}")
    return notes


# ---------------------------------------------------------------- the logo's symbol
def rasterize_svg(svg: bytes, settings) -> bytes:
    """An SVG drawn to a transparent PNG in headless Chrome, 1200 px wide, with no network access."""
    import subprocess
    import tempfile

    from .config import PKG_DIR

    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "in.svg", Path(tmp) / "out.png"
        src.write_bytes(svg)
        res = subprocess.run(
            ["node", str(PKG_DIR / "js" / "raster.mjs"), str(src), settings.resolve_browser(), str(out)],
            capture_output=True,
            text=True,
            env=settings.hf_env(),
            timeout=120,
        )
        if res.returncode != 0 or not out.exists():
            raise RuntimeError(f"could not draw the SVG logo: {res.stderr[-300:]}")
        return out.read_bytes()


def extract_mark(logo: tuple[str, bytes] | None, *, color: str | None = None, png: bytes | None = None) -> bytes | None:
    """The symbol of a logo that pairs a symbol with a wordmark, traced to SVG; None when there isn't one.

    Works on a raster logo (or a raster copy of an SVG logo, `png`): transparent or plain background, shapes
    grouped by the gaps between them; the first group from the reading start is the symbol when it's roughly
    square and the rest is wider (the wordmark). Needs `potracer` (pip install 'kinetry[brand3d]')."""
    import io

    import numpy as np
    from PIL import Image

    raw = png
    if raw is None and logo and not logo[0].lower().endswith(".svg"):
        raw = logo[1]
    if not raw:
        return None
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    im.thumbnail((1200, 1200))
    a = np.asarray(im).astype(float)
    alpha = a[..., 3] / 255
    if alpha.min() > 0.9:  # opaque: the background is the corner color
        strength = np.clip(np.abs(a[..., :3] - a[0, 0, :3]).sum(-1) / 120, 0, 1)
    else:
        strength = alpha
    ink = strength > 0.5
    cols = ink.any(0)
    if cols.sum() < 8:
        return None
    # runs of columns with ink, merged across small gaps (letters), split at big ones (symbol | wordmark)
    h = max(1, int(ink.any(1).sum()))
    gap = max(4, int(h * 0.25))  # letters sit closer than this; a symbol stands further off its wordmark
    groups, start, last = [], None, None
    for x, on in enumerate(cols):
        if on:
            if start is None:
                start = x
            elif last is not None and x - last > gap:
                groups.append((start, last))
                start = x
            last = x
    if start is not None:
        groups.append((start, last))
    if len(groups) < 2:
        return None
    x0, x1 = groups[0]
    rows = ink[:, x0 : x1 + 1].any(1)
    y0, y1 = int(np.argmax(rows)), int(len(rows) - np.argmax(rows[::-1]) - 1)
    w, hh = x1 - x0 + 1, y1 - y0 + 1
    rest_w = groups[-1][1] - groups[1][0] + 1
    if not (0.55 <= w / hh <= 1.8) or rest_w < w * 1.2:
        return None
    try:
        import potrace
    except ImportError as e:
        raise RuntimeError("tracing the logo's symbol needs potracer: pip install 'kinetry[brand3d]'") from e
    if color is None:  # the symbol's own color
        px = a[y0 : y1 + 1, x0 : x1 + 1][ink[y0 : y1 + 1, x0 : x1 + 1]][:, :3]
        color = "#" + "".join(f"{int(v):02x}" for v in np.median(px, axis=0)) if len(px) else "#000000"
    # traced from the anti-aliased edges, scaled up, so curves come out smooth rather than in pixel steps
    pad = 4
    crop = strength[max(0, y0 - pad) : y1 + pad + 1, max(0, x0 - pad) : x1 + pad + 1]
    k = max(1.0, 800 / max(crop.shape))
    size = (round(crop.shape[1] * k), round(crop.shape[0] * k))
    big = np.asarray(Image.fromarray((crop * 255).astype("uint8")).resize(size, Image.BICUBIC)) > 127
    paths = potrace.Bitmap(~big).trace(turdsize=12, alphamax=1.1, opttolerance=0.3)  # potracer traces the zeros

    def curve(c) -> str:
        s = c.start_point
        d = [f"M{s.x:.1f} {s.y:.1f}"]
        for seg in c.segments:
            if seg.is_corner:
                d.append(f"L{seg.c.x:.1f} {seg.c.y:.1f}L{seg.end_point.x:.1f} {seg.end_point.y:.1f}")
            else:
                d.append(
                    f"C{seg.c1.x:.1f} {seg.c1.y:.1f} {seg.c2.x:.1f} {seg.c2.y:.1f} {seg.end_point.x:.1f} {seg.end_point.y:.1f}"
                )
        return "".join(d) + "Z"

    d = "".join(curve(c) for c in paths)
    if not d:
        return None
    H, W = big.shape
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">'
        f'<path fill="{color}" fill-rule="evenodd" d="{d}"/></svg>'
    ).encode()


# ---------------------------------------------------------------- which asset goes on which scene
def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def scene_text(sc) -> set[str]:
    parts = [b.say for b in sc.beats]
    for v in sc.data.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts += [x for x in v if isinstance(x, str)]
            parts += [str(y) for x in v if isinstance(x, dict) for y in x.values() if isinstance(y, str)]
    return {_stem(w) for w in words_in(" ".join(parts))}


def pick_assets(
    plan, items: list[Asset3D], *, hero_scenes: set[int], has_mark: bool = False
) -> tuple[dict[int, list[str]], list[str]]:
    """Which of the brand's models may stand on which scene: ({scene index: model ids, best first}, spare ids).

    Hero models (products, mascots) open on title scenes and the logo closes the video (a logo model, else the
    brand's mark, which the stage builds itself). Other scenes list the models whose tags their words mention,
    best match first. Spare models are shown on any scene with room, so each model appears at least once. The
    stage makes the final call per scene, because only the settled layout says where there's room."""
    items = [a for a in items if a.use]
    if not items:
        return {}, []
    products = [a for a in items if a.role == "hero"]
    logos = [a for a in items if a.role == "logo"]
    props = [a for a in items if a.role != "logo"]
    out: dict[int, list[str]] = {}
    order = sorted(hero_scenes)
    for k, i in enumerate(order):
        closing = k == len(order) - 1 and len(order) > 1
        if closing and (logos or has_mark):
            pick = logos[0] if logos else None
        else:
            pool = products or logos
            pick = pool[k % len(pool)] if pool else None
        if pick:
            out[i] = [pick.id]
    for i, sc in enumerate(plan.scenes):
        if i in hero_scenes:
            continue
        ws = scene_text(sc)
        scored = []
        for a in props:
            s = len(ws & {_stem(t) for t in a.tags}) + 0.5 * len(ws & {_stem(w) for w in words_in(a.name)})
            if s > 0:
                scored.append((-s, a.id))
        if scored:
            out[i] = [aid for _, aid in sorted(scored)]
    spare = [a.id for a in props if a.role == "prop"] or [a.id for a in products]
    return out, spare
