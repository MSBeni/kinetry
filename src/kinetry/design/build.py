"""Glue between the pipeline and the renderer: fonts for a style, then write the project."""

from __future__ import annotations

from pathlib import Path

from ..branding import BrandPack
from ..config import Settings
from ..fonts import FontResolver
from ..timing import Timeline
from .catalog import Catalog, load_catalog
from .icons import Icons
from .plan import VideoPlan2
from .render import RenderInput, resolve_design, write_project

MONO_FONT = "JetBrains Mono"


def style_fonts(pack: BrandPack, style_tokens: dict, fonts: FontResolver) -> dict:
    kit = pack.kit
    out = {
        "display": fonts.resolve(kit.display_font, "serif" if kit.display_weight <= 500 else "sans"),
        "body": fonts.resolve(kit.body_font, "sans"),
    }
    acc = style_tokens.get("accent_font")
    if acc:
        out["accent"] = fonts.resolve(acc["family"], acc.get("kind", "sans"))
    return out


def _default_images(pack: BrandPack, settings: Settings):
    from ..images import ImageResolver

    return ImageResolver(
        public_only=settings.public_urls_only,
        uploads_dir=settings.images_dir or settings.home / "images",
        brand_images=getattr(pack, "images", None) or [],
    )


def _models(pack: BrandPack) -> list:
    from ..brand3d import library_dir

    home = getattr(pack, "home", None)
    if not home:
        return []
    return [(a, library_dir(home) / a.file) for a in getattr(pack, "assets3d", []) if a.use]


def compose_project(
    plan: VideoPlan2,
    pack: BrandPack,
    timeline: Timeline,
    out_dir: Path,
    settings: Settings,
    *,
    fit: dict | None = None,
    catalog: Catalog | None = None,
    icons: Icons | None = None,
    fonts: FontResolver | None = None,
    images=None,
) -> Path:
    cat = catalog or load_catalog()
    fr = fonts or FontResolver(settings.cache_dir / "fonts")
    rd = resolve_design(plan, cat)
    fonts = style_fonts(pack, rd.style.tokens, fr)
    needs = {f for sc in plan.scenes if sc.type in cat.components for f in cat.components[sc.type].fonts}
    if "mono" in needs:  # code scenes: a monospace face, fetched only for plans that show code
        fonts["mono"] = fr.resolve(MONO_FONT, "sans")
    ri = RenderInput(
        plan=plan,
        brand=pack.kit,
        fonts=fonts,
        timeline=timeline,
        fit=fit or {},
        logo=pack.logo,
        catalog=cat,
        icons=icons or Icons(settings.tool_dir),
        images=images if images is not None else _default_images(pack, settings),
        vendor=settings.vendor_paths(),
        mark=getattr(pack, "mark", None),
        models=_models(pack),
    )
    return write_project(ri, out_dir, settings.gsap_path())
