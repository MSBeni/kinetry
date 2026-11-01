"""List prices for generated media, used for estimates and the spending cap (never for billing).

Copied from Google Cloud's Vertex AI generative AI pricing page on 2026-11-01. Prices change: check
https://cloud.google.com/vertex-ai/generative-ai/pricing before relying on them. Veo prices are per second of
generated video; image prices are per output image at about 1K resolution.
"""

from __future__ import annotations

PRICES_AS_OF = "2026-11-01"

# model -> USD per output image (about 1024 px)
IMAGE = {
    "gemini-2.5-flash-image": 0.039,
    "gemini-3.1-flash-image": 0.067,
    "gemini-3-pro-image": 0.134,
    "imagen-4.0-fast-generate-001": 0.02,
    "imagen-4.0-generate-001": 0.04,
    "imagen-4.0-ultra-generate-001": 0.06,
}

# model family -> {(resolution, with_audio): USD per second}
VIDEO = {
    "veo-3.1": {("720p", True): 0.40, ("1080p", True): 0.40, ("720p", False): 0.20, ("1080p", False): 0.20},
    "veo-3.1-fast": {("720p", True): 0.10, ("1080p", True): 0.12, ("720p", False): 0.08, ("1080p", False): 0.10},
    "veo-3.1-lite": {("720p", True): 0.05, ("1080p", True): 0.08, ("720p", False): 0.03, ("1080p", False): 0.05},
    "veo-3.0": {("720p", True): 0.40, ("1080p", True): 0.40, ("720p", False): 0.20, ("1080p", False): 0.20},
    "veo-3.0-fast": {("720p", True): 0.10, ("1080p", True): 0.12, ("720p", False): 0.08, ("1080p", False): 0.10},
}


def _family(model: str) -> str | None:
    m = model.lower()
    for fam in sorted(VIDEO, key=len, reverse=True):  # longest match first: veo-3.1-fast before veo-3.1
        if m.startswith(fam):
            return fam
    return None


def estimate_image(model: str, n: int = 1) -> float | None:
    """USD for n images, or None when the model's price isn't known (the cap then refuses to guess)."""
    m = model.lower()
    for k, v in IMAGE.items():
        if m.startswith(k):
            return round(v * n, 4)
    return None


def estimate_video(model: str, seconds: float, resolution: str = "720p", audio: bool = False) -> float | None:
    fam = _family(model)
    if fam is None:
        return None
    per = VIDEO[fam].get((resolution, audio))
    return None if per is None else round(per * seconds, 4)
