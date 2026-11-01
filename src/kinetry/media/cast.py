"""A character pack from one photo: a styled cartoon of the person, their expressions, mouth shapes and a blink.

    pack = build_cast(photo_bytes, Path("cast/moe"), media, consent=True)

1. The photo becomes one base character (head and shoulders, facing the camera, plain background).
2. Every variant (each expression, each mouth shape from kinetry.visemes, eyes closed) is generated as an
   edit of that base, so the person stays the same.
3. Generated edits never line up to the pixel, so each variant is registered to the base (phase
   correlation) before use. Mouth shapes and the blink are then cut out as small patches over one shared box,
   with feathered edges; only the expressions swap the whole picture (with a crossfade). That keeps the face
   from jittering when the mouth moves.

The result is a folder with pack.json and PNGs that the `character` scene uses through a speaker's `sprite`.
Only ever build a pack from a photo of the person who asked for it: `consent=True` records that they did.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from .base import MediaError

STYLE = (
    "a clean, modern flat 2D vector cartoon character for an animated explainer video: bold smooth outlines, "
    "flat colors with soft cel shading, friendly proportions"
)
BASE_PROMPT = (
    "Turn the person in this photo into {style}. Head and shoulders, facing the camera, centered in the frame, "
    "relaxed neutral expression, mouth closed, eyes open, looking at the viewer. Plain solid light background "
    "(#efece6), no props, no text. Keep them clearly recognisable: same face shape, hairstyle and hair color, "
    "glasses, facial hair, skin tone and clothing."
)
EDIT = (
    "Edit this cartoon character image. Keep EVERYTHING identical: same character, same pose, same framing, "
    "same size and position in the frame, same background, same lighting and line style. Change ONLY {what}."
)
MOODS = {
    "happy": "the expression to a warm, genuine smile (eyes slightly narrowed by the smile)",
    "worried": "the expression to worried: inner eyebrows raised and drawn together, small frown",
    "annoyed": "the expression to annoyed: eyebrows lowered and pulled together, lips pressed flat",
    "thinking": "the expression to thoughtful: one eyebrow slightly raised, eyes glancing up and to the side",
    "calm": "the expression to calm and confident: relaxed brows, a small gentle closed-mouth smile",
}
MOUTHS = {
    "A": "the mouth: lips gently pressed together, closed, as when saying 'm', 'b' or 'p'",
    "B": "the mouth: slightly open with the upper teeth just visible, as when saying 's' or 't'",
    "C": "the mouth: open to a medium height, as when saying 'eh'",
    "D": "the mouth: wide open with teeth and tongue visible, as when saying 'ah'",
    "E": "the mouth: open in a rounded 'o' shape",
    "F": "the mouth: lips puckered forward into a small round 'oo' shape",
    "G": "the mouth: upper front teeth resting on the lower lip, as when saying 'f' or 'v'",
}
BLINK = "the eyes: both eyes fully closed in a relaxed blink (eyelids down), nothing else"


def _img(data: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def _gray(im, size):
    import numpy as np

    return np.asarray(im.convert("L").resize(size), dtype=np.float32)


def register(base, img):
    """Shift `img` (PIL, any size) onto `base`: returns the aligned image and the (dx, dy) applied."""
    import numpy as np
    from PIL import Image

    img = img.resize(base.size)
    a, b = _gray(base, base.size), _gray(img, base.size)
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-9
    corr = np.abs(np.fft.ifft2(r))
    dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    h, w = a.shape
    dy = dy - h if dy > h // 2 else dy
    dx = dx - w if dx > w // 2 else dx
    out = Image.new("RGB", base.size, base.getpixel((2, 2)))
    out.paste(img, (int(dx), int(dy)))
    return out, (int(dx), int(dy))


def change_box(base, variants, region, thresh: float = 28.0, pad: float = 0.04):
    """The box (pixels) covering where `variants` differ from `base`, searched inside `region` (fractions
    x0, y0, x1, y1 of the frame). Falls back to the whole region when nothing changed."""
    import numpy as np

    w, h = base.size
    x0, y0, x1, y1 = int(region[0] * w), int(region[1] * h), int(region[2] * w), int(region[3] * h)
    a = np.asarray(base, dtype=np.int16)[y0:y1, x0:x1]
    mask = np.zeros(a.shape[:2], dtype=bool)
    for v in variants:
        d = np.abs(np.asarray(v, dtype=np.int16)[y0:y1, x0:x1] - a).max(axis=2)
        mask |= d > thresh
    ys, xs = np.nonzero(mask)
    if len(xs) < 40:
        return (x0, y0, x1, y1)
    lo_x, hi_x = np.percentile(xs, [1, 99]).astype(int)
    lo_y, hi_y = np.percentile(ys, [1, 99]).astype(int)
    px, py = int(pad * w), int(pad * h)
    return (max(0, x0 + lo_x - px), max(0, y0 + lo_y - py), min(w, x0 + hi_x + px), min(h, y0 + hi_y + py))


def patch(img, box, feather: float = 0.22):
    """Crop `box` from `img` with an elliptical, feathered alpha so it blends into the face under it."""
    import numpy as np
    from PIL import Image

    crop = img.crop(box).convert("RGBA")
    w, h = crop.size
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    alpha = np.clip((1.0 - r) / feather, 0, 1)
    crop.putalpha(Image.fromarray((alpha * 255).astype("uint8")))
    return crop


def cutout(im, thresh: int = 34):
    """Make the plain background transparent: flood-fill from the frame's edges (so light colors inside the
    character stay), then soften the edge by a pixel."""
    from PIL import Image, ImageDraw, ImageFilter

    rgb = im.convert("RGB")
    probe = rgb.copy()
    key = (255, 0, 255)
    w, h = probe.size
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (0, h // 3), (w - 1, h // 3)]:
        if probe.getpixel((x, y)) != key:
            ImageDraw.floodfill(probe, (x, y), key, thresh=thresh)
    import numpy as np

    bg = (np.asarray(probe) == np.array(key)).all(axis=2)
    alpha = Image.fromarray(np.where(bg, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1.2))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def build_cast(photo: bytes, out_dir: Path, media, *, consent: bool, style: str = STYLE, moods=None) -> dict:
    """Generate a character pack into out_dir; returns pack.json's content."""
    if not consent:
        raise MediaError(
            "A character pack is only made from a photo of the person who asked for it. "
            "Confirm that with consent=True (CLI: --consent)."
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cost = 0.0
    r = media.image(BASE_PROMPT.format(style=style), refs=[photo], aspect="3:4")
    cost += r.cost
    base_bytes = r.path.read_bytes()
    base = _img(base_bytes)
    (out_dir / "base.png").write_bytes(_png(cutout(base)))

    def variant(what: str):
        nonlocal cost
        res = media.image(EDIT.format(what=what), refs=[base_bytes], aspect="3:4")
        cost += res.cost
        aligned, shift = register(base, _img(res.path.read_bytes()))
        return aligned, shift

    pack: dict = {
        "version": 1,
        "size": list(base.size),
        "base": "base.png",
        "moods": {"neutral": "base.png"},
        "shifts": {},
    }
    for m in moods or list(MOODS):
        im, shift = variant(MOODS[m])
        (out_dir / f"mood-{m}.png").write_bytes(_png(cutout(im)))
        pack["moods"][m], pack["shifts"][f"mood-{m}"] = f"mood-{m}.png", shift

    mouths = {}
    for v, what in MOUTHS.items():
        mouths[v], pack["shifts"][f"mouth-{v}"] = variant(what)
    mbox = change_box(base, list(mouths.values()), region=(0.25, 0.42, 0.75, 0.80))
    pack["mouth"] = {"box": _frac(mbox, base.size), "shapes": {}}
    for v, im in mouths.items():
        (out_dir / f"mouth-{v}.png").write_bytes(_png(patch(im, mbox)))
        pack["mouth"]["shapes"][v] = f"mouth-{v}.png"

    blink, pack["shifts"]["blink"] = variant(BLINK)
    bbox = change_box(base, [blink], region=(0.2, 0.2, 0.8, 0.55))
    (out_dir / "blink.png").write_bytes(_png(patch(blink, bbox, feather=0.3)))
    pack["blink"] = {"box": _frac(bbox, base.size), "file": "blink.png"}

    pack.update(
        {
            "consent": True,
            "model": getattr(media, "image_model", ""),
            "usd": round(cost, 4),
            "background": "#{:02x}{:02x}{:02x}".format(*base.getpixel((4, 4))),
        }
    )
    (out_dir / "pack.json").write_text(json.dumps(pack, indent=2))
    return pack


def _frac(box, size) -> list[float]:
    w, h = size
    x0, y0, x1, y1 = box
    return [round(x0 / w, 4), round(y0 / h, 4), round((x1 - x0) / w, 4), round((y1 - y0) / h, 4)]


def load_pack(path: Path) -> dict:
    p = Path(path) / "pack.json"
    if not p.is_file():
        raise MediaError(f"no character pack at {path} (expected pack.json; make one with `kinetry media cast`)")
    pack = json.loads(p.read_text())
    if not pack.get("consent"):
        raise MediaError(f"{path}: this pack wasn't made with consent recorded")
    return pack
