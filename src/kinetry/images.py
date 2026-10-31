"""Images for scenes: where they may come from, and checks before they reach a video.

An image field in a plan holds a reference:
    https://...       a public image URL (fetched through the private-address guard in service mode)
    upload:<id>       an image uploaded to the service (POST /v1/images)
    brand:<n>         the n-th image found on the brand's website (its og:image / twitter:image), 1-based
    catalog:<scene>/<file>  a sample bundled with a scene type (the gallery and docs examples)
    <local path>      a file on disk; library and CLI only, never accepted by the service

Animation fields (the illustration scene) take Lottie JSON the same ways (https, upload:, local files outside the
service), up to 3 MB, with any images embedded as data URIs; nothing is fetched while rendering. Lottie files play
with lottie-web's light player, which ignores expressions (no script runs).

Only PNG, JPEG, WebP and GIF are accepted (checked from the file's bytes, not its name), up to 15 MB. SVG is
refused: it can carry scripts and external references. Use images you have the rights to; a brand's site images
belong to the brand, so use them only with its permission.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_LOTTIE_BYTES = 3 * 1024 * 1024
UPLOAD_ID = re.compile(r"[a-f0-9]{16,64}")


class ImageError(ValueError):
    pass


def sniff(data: bytes) -> str | None:
    """File type from magic bytes -> extension, or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def check_image(data: bytes, what: str = "image") -> str:
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(f"{what} is larger than 15 MB")
    ext = sniff(data)
    if not ext:
        raise ImageError(f"{what} isn't a PNG, JPEG, WebP or GIF image")
    return ext


def check_lottie(data: bytes, what: str = "animation") -> dict:
    """Parse and check a Lottie JSON file -> its dict. Refuses anything that would load from elsewhere."""
    import json

    if len(data) > MAX_LOTTIE_BYTES:
        raise ImageError(f"{what} is larger than 3 MB")
    try:
        d = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ImageError(f"{what} isn't a Lottie JSON file") from e
    if (
        not isinstance(d, dict)
        or not isinstance(d.get("layers"), list)
        or not all(k in d for k in ("fr", "op", "w", "h"))
    ):
        raise ImageError(f"{what} isn't a Lottie animation (no layers, frame rate or size)")
    try:
        fr, ip, op = float(d["fr"]), float(d.get("ip", 0)), float(d["op"])
    except (TypeError, ValueError) as e:
        raise ImageError(f"{what}: bad frame rate or length") from e
    if not (1 <= fr <= 120 and 0 < op - ip <= fr * 600):
        raise ImageError(f"{what}: frame rate or length out of range")
    for a in d.get("assets") or []:
        p = a.get("p") if isinstance(a, dict) else None
        if isinstance(p, str) and (a.get("u") or not p.startswith("data:")) and "layers" not in a:
            raise ImageError(f"{what}: images must be embedded (data URIs); external files aren't loaded")
    return d


def is_lottie(data: bytes) -> bool:
    return data.lstrip()[:1] == b"{"


def is_ref(v: str) -> bool:
    return isinstance(v, str) and 0 < len(v) <= 2000


class ImageResolver:
    """Turns image references into files inside a project. One per run: fetched bytes are cached across the
    fit loop's recompositions."""

    def __init__(
        self,
        *,
        public_only: bool = False,
        uploads_dir: Path | None = None,
        brand_images: list[str] | None = None,
        base_dir: Path | None = None,
        fetch=None,
    ):
        self.public_only, self.uploads_dir = public_only, uploads_dir
        self.brand_images, self.base_dir = list(brand_images or []), base_dir
        self._fetch, self._cache = fetch, {}
        self.out_dir: Path | None = None

    def bind(self, assets_dir: Path) -> ImageResolver:
        self.out_dir = assets_dir
        return self

    def load(self, ref: str) -> tuple[bytes, str]:
        if ref in self._cache:
            return self._cache[ref]
        data = self._raw(ref)
        out = (data, check_image(data, ref.strip()[:80]))
        self._cache[ref] = out
        return out

    def _raw(self, ref: str, exts: tuple[str, ...] = ("png", "jpg", "webp", "gif")) -> bytes:
        ref = ref.strip()
        if ref.startswith("brand:"):
            try:
                url = self.brand_images[int(ref.split(":", 1)[1]) - 1]
            except (ValueError, IndexError) as e:
                raise ImageError(f"{ref}: the brand pack has {len(self.brand_images)} site images") from e
            return self._get(url)
        if ref.startswith("upload:"):
            uid = ref.split(":", 1)[1]
            if not UPLOAD_ID.fullmatch(uid) or self.uploads_dir is None:
                raise ImageError(f"{ref}: unknown upload")
            hits = sorted(p for p in self.uploads_dir.glob(f"{uid}.*") if p.suffix[1:] in exts)
            if not hits:
                raise ImageError(f"{ref}: unknown upload")
            return hits[0].read_bytes()
        if re.match(r"(?i)^https?://", ref):
            return self._get(ref)
        if ref.startswith("catalog:"):
            rel = ref.split(":", 1)[1]
            if not re.fullmatch(r"[a-z_]+/[a-z0-9_-]+\.(png|jpg|webp|gif|json)", rel):
                raise ImageError(f"{ref}: not a bundled sample")
            from .design.catalog import load_catalog

            p = load_catalog().root / "components" / rel
            if not p.is_file():
                raise ImageError(f"{ref}: not a bundled sample")
            return p.read_bytes()
        if self.public_only:
            raise ImageError("image must be an https URL or an upload: reference")
        p = Path(ref)
        if not p.is_absolute() and self.base_dir:
            p = self.base_dir / p
        if not p.is_file():
            raise ImageError(f"image file not found: {ref}")
        return p.read_bytes()

    def lottie_json(self, ref: str) -> str:
        """A Lottie reference -> checked, compact JSON text to embed in the page."""
        import json

        key = "lottie:" + ref
        if key not in self._cache:
            data = self._raw(ref, exts=("json",))
            self._cache[key] = (json.dumps(check_lottie(data, ref[:80]), separators=(",", ":")), "json")
        return self._cache[key][0]

    def _get(self, url: str) -> bytes:
        from .netguard import check_public_url

        check_public_url(url, allow_private=not self.public_only, what="image URL")
        if self._fetch:
            return self._fetch(url)
        from .netguard import client as make_client

        with make_client(
            self.public_only,
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (kinetry)"},
        ) as c:
            with c.stream("GET", url) as r:
                r.raise_for_status()
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > MAX_IMAGE_BYTES:
                        raise ImageError(f"{url[:80]} is larger than 15 MB")
                return bytes(buf)

    def src(self, ref: str) -> str:
        """Copy the image into the project and return its path relative to index.html."""
        if self.out_dir is None:
            raise RuntimeError("ImageResolver.bind(assets_dir) first")
        data, ext = self.load(ref)
        name = f"img-{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        dest = self.out_dir / name
        if not dest.exists():
            dest.write_bytes(data)
        return f"assets/{name}"


def save_upload(data: bytes, uploads_dir: Path) -> str:
    """Store an uploaded image or Lottie animation -> 'upload:<id>' (content-addressed: same file, same id)."""
    if is_lottie(data):
        check_lottie(data, "upload")
        ext = "json"
    else:
        ext = check_image(data, "upload")
    uid = hashlib.sha256(data).hexdigest()[:32]
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / f"{uid}.{ext}").write_bytes(data)
    return f"upload:{uid}"
