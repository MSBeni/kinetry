"""Resolve brand fonts to local WOFF2 files via Fontsource (npm).

Renders must not fetch fonts at render time, so fonts are vendored into the
project. Proprietary brand fonts (not on Fontsource) fall back to a close open
alternative; the substitution is reported, never silent.
"""

from __future__ import annotations

import io
import re
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

import httpx

REGISTRY = "https://registry.npmjs.org"

# Common proprietary / system families -> open look-alikes on Fontsource
SUBSTITUTES = {
    "helvetica": "Inter",
    "helvetica neue": "Inter",
    "arial": "Inter",
    "segoe ui": "Inter",
    "-apple-system": "Inter",
    "blinkmacsystemfont": "Inter",
    "system-ui": "Inter",
    "sf pro": "Inter",
    "avenir": "Nunito Sans",
    "avenir next": "Nunito Sans",
    "proxima nova": "Montserrat",
    "gotham": "Montserrat",
    "futura": "Jost",
    "gill sans": "Lato",
    "frutiger": "Source Sans 3",
    "myriad pro": "Source Sans 3",
    "georgia": "Source Serif 4",
    "times new roman": "Source Serif 4",
    "garamond": "EB Garamond",
    "didot": "Playfair Display",
    "brandon grotesque": "Josefin Sans",
    "gilroy": "Plus Jakarta Sans",
    "circular": "DM Sans",
    "circular std": "DM Sans",
    "graphik": "Inter",
    "sofia pro": "Nunito Sans",
    "museo sans": "Nunito Sans",
    "tt norms": "Manrope",
    "aeonik": "Manrope",
}
FALLBACK_SANS, FALLBACK_SERIF = "Inter", "Fraunces"


@dataclass
class FontFiles:
    family: str  # family actually used
    requested: str
    files: dict[str, Path]  # "400", "500", "600", "400italic" -> path
    substituted: bool


def slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")


class FontResolver:
    def __init__(self, cache_dir: Path, client: httpx.Client | None = None):
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.http = client or httpx.Client(timeout=60, follow_redirects=True)

    def available(self, family: str) -> bool:
        return self.http.get(f"{REGISTRY}/@fontsource%2F{slug(family)}").status_code == 200

    def _download(self, family: str) -> Path:
        dest = self.cache / slug(family)
        if dest.exists() and any(dest.glob("*.woff2")):
            return dest
        meta = self.http.get(f"{REGISTRY}/@fontsource%2F{slug(family)}").json()
        tarball = meta["versions"][meta["dist-tags"]["latest"]]["dist"]["tarball"]
        data = self.http.get(tarball).content
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for m in tf.getmembers():
                name = Path(m.name).name
                if re.fullmatch(rf"{slug(family)}-latin-(400|500|600|700)-(normal|italic)\.woff2", name):
                    with tf.extractfile(m) as src, open(dest / name, "wb") as out:  # type: ignore[union-attr]
                        shutil.copyfileobj(src, out)
        return dest

    def resolve(self, requested: str, kind: str = "sans") -> FontFiles:
        family, substituted = requested.strip().strip("'\""), False
        if family.lower() in SUBSTITUTES:
            family, substituted = SUBSTITUTES[family.lower()], True
        if not self.available(family):
            family, substituted = (FALLBACK_SERIF if kind == "serif" else FALLBACK_SANS), True
        d = self._download(family)
        s = slug(family)
        files: dict[str, Path] = {}
        for w in ("400", "500", "600", "700"):
            p = d / f"{s}-latin-{w}-normal.woff2"
            if not p.exists():  # some families skip weights; fall back to nearest
                alts = sorted(d.glob(f"{s}-latin-*-normal.woff2"))
                p = alts[0] if alts else p
            files[w] = p
        it = d / f"{s}-latin-400-italic.woff2"
        files["400italic"] = it if it.exists() else files["400"]
        return FontFiles(family, requested, files, substituted)
