"""Brand resolution: website (or saved probe/HTML) -> BrandPack.

A BrandPack is the reusable result: a contrast-safe BrandKit plus the logo.
Resolve it once per client and reuse it for every video (it is also the most
expensive LLM step), e.g. `pack.save("brands/acme")` / `BrandPack.load(...)`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .agents import Recorder, run_brand_agent
from .brand import (
    BrandKit,
    enforce,
    extract_signals,
    heuristic_kit,
    http_fetcher,
    logo_is_legible,
    signals_from_probe,
)
from .config import Settings
from .design.profile import BrandProfile
from .fonts import FontResolver
from .probe import logo_from_probe, probe_site

DEFAULT_KIT = BrandKit(
    name="Kinetry default",
    background="#f6f7f9",
    surface="#ffffff",
    ink="#161b26",
    muted="#545d6e",
    line="#dfe3ea",
    accent="#2453e3",
    accent2="#c4620c",
    display_font="Fraunces",
    body_font="Inter",
    radius=24,
    rationale="built-in default",
)


@dataclass
class BrandPack:
    kit: BrandKit
    logo: tuple[str, bytes] | None = None
    notes: list[str] = field(default_factory=list)
    profile: BrandProfile = field(default_factory=BrandProfile)  # standing design preferences
    images: list[str] = field(default_factory=list)  # the site's own preview images: brand:<n> in plans
    mark: tuple[str, bytes] | None = None  # the logo's symbol alone (SVG), shown in 3D on the depth stage
    # the brand's own 3D models (kinetry.brand3d), kept in <pack>/assets3d/; `home` is the pack's folder
    assets3d: list = field(default_factory=list)
    home: Path | None = None

    def save(self, directory: str | Path) -> Path:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        (d / "brand.json").write_text(self.kit.model_dump_json(indent=2))
        if self.profile.model_dump(exclude_defaults=True):
            self.profile.save(d)
        meta = {"logo": self.logo[0] if self.logo else None, "notes": self.notes, "images": self.images}
        if self.logo:
            (d / self.logo[0]).write_bytes(self.logo[1])
        if self.mark:
            meta["mark"] = self.mark[0]
            (d / self.mark[0]).write_bytes(self.mark[1])
        (d / "pack.json").write_text(json.dumps(meta, indent=2))
        if self.home and self.assets3d and Path(self.home).resolve() != d.resolve():
            import shutil

            from .brand3d import library_dir

            shutil.copytree(library_dir(self.home), library_dir(d), dirs_exist_ok=True)
            self.home = d
        return d

    @classmethod
    def load(cls, directory: str | Path) -> BrandPack:
        d = Path(directory)
        kit = BrandKit.model_validate_json((d / "brand.json").read_text())
        meta = json.loads((d / "pack.json").read_text()) if (d / "pack.json").exists() else {}
        logo = None
        if meta.get("logo") and (d / meta["logo"]).exists():
            logo = (meta["logo"], (d / meta["logo"]).read_bytes())
        imgs = [u for u in meta.get("images", []) if isinstance(u, str) and u.startswith(("https://", "http://"))]
        mark = None
        name = meta.get("mark")
        if isinstance(name, str) and "/" not in name and name.endswith(".svg") and (d / name).exists():
            mark = (name, (d / name).read_bytes())
        from .brand3d import load_library

        try:
            models = load_library(d)
        except ValueError:  # an unreadable library doesn't stop the brand
            models = []
        return cls(kit, logo, meta.get("notes", []), BrandProfile.load(d), imgs[:6], mark, models, d)

    @classmethod
    def default(cls) -> BrandPack:
        return cls(DEFAULT_KIT.model_copy())


def resolve_brand(
    source: str | None,
    settings: Settings,
    run_dir: Path,
    *,
    llm=None,
    replay_dir: Path | None = None,
    use_logo: bool = True,
    fonts: FontResolver | None = None,
) -> BrandPack:
    """`source`: https URL (probed in headless Chrome), saved .html page, probe .json, a BrandPack
    directory, or None for the default kit."""
    run_dir.mkdir(parents=True, exist_ok=True)
    if not source:
        pack = BrandPack.default()
    elif Path(source).is_dir() and (Path(source) / "brand.json").exists():
        pack = BrandPack.load(source)
        pack.notes.append(f"loaded brand pack {source}")
    else:
        pack = _from_site(
            source, settings, run_dir, llm, replay_dir, use_logo, fonts or FontResolver(settings.cache_dir / "fonts")
        )
    kit, fixes = enforce(pack.kit)
    pack.kit = kit
    pack.notes += fixes
    if (
        pack.logo
        and pack.logo[0].endswith(".svg")
        and not logo_is_legible(pack.logo[1].decode(errors="ignore"), kit.background)
    ):
        pack.notes.append("logo dropped: its colors don't stand out on the video background")
        pack.logo = None
    return pack


def _from_site(src, settings, run_dir, llm, replay_dir, use_logo, fonts) -> BrandPack:
    notes: list[str] = []
    fetcher = http_fetcher(public_only=settings.public_urls_only)
    signals = probe = None
    path = Path(src)
    if path.suffix == ".json" and path.exists():  # probe captured earlier / in another browser
        probe = json.loads(path.read_text())
    elif path.exists():  # saved HTML page
        signals = extract_signals(path.read_text(errors="ignore"), base_url="file://" + str(path.resolve()))
    else:  # live URL: real browser first, CSS scraping fallback
        try:
            probe = probe_site(src, settings, run_dir / "probe.json")
        except Exception as e:  # noqa: BLE001
            notes.append(f"browser probe unavailable ({str(e)[:100]}); scraped CSS instead")
            signals = extract_signals(src, fetcher)
    logo = None
    if probe is not None:
        signals = signals_from_probe(probe)
        logo = logo_from_probe(probe) if use_logo else None
    (run_dir / "signals.json").write_text(json.dumps(signals, indent=2, default=str))
    label = probe.get("url", src) if probe else (src if not path.exists() else f"file://{path.resolve()}")
    try:
        kit = run_brand_agent(
            label, settings, Recorder(run_dir, settings, replay_dir), fonts, fetcher=fetcher, signals=signals, llm=llm
        )
    except Exception as e:  # noqa: BLE001  (LLM unavailable -> deterministic fallback, but say so)
        kit = heuristic_kit(signals)
        notes.append(f"brand agent unavailable ({type(e).__name__}: {str(e)[:120]}); used heuristic kit")
    pack = BrandPack(kit, logo, notes, images=list(signals.get("images") or [])[:6])
    if probe is not None:
        _site_3d(pack, probe, settings, run_dir, use_logo)
    return pack


def _site_3d(pack: BrandPack, probe: dict, settings, run_dir: Path, use_logo: bool) -> None:
    """What the asset agent can take from the site for the 3D stage: the logo's symbol, and the site's models
    (kept in the run folder until the pack is saved)."""
    from . import brand3d
    from .probe import logo_png_from_probe

    if use_logo and pack.logo:
        try:
            png = logo_png_from_probe(probe)
            if png is None and pack.logo[0].endswith(".svg"):
                png = brand3d.rasterize_svg(pack.logo[1], settings)
            svg = brand3d.extract_mark(pack.logo, png=png)
            if svg:
                pack.mark = ("mark.svg", svg)
                pack.notes.append("logo symbol cut out of the logo for the 3D stage")
        except Exception as e:  # noqa: BLE001  (potracer missing, odd image): the stage still has shapes
            pack.notes.append(f"logo symbol not extracted: {str(e)[:120]}")
    urls = [u for u in probe.get("models") or [] if isinstance(u, str)]
    if urls:
        pack.notes += brand3d.fetch_site_models(
            urls, run_dir, public_only=settings.public_urls_only, page=probe.get("url", ""), settings=settings
        )
        pack.assets3d = brand3d.load_library(run_dir)
        pack.home = run_dir
