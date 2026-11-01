"""Google generative media: Gemini image models / Imagen for images, Veo for video clips.

Two ways in, both with the caller's own account:

- Vertex AI (bills to a Google Cloud project, so cloud credits apply): `project` + `location`, with
  credentials from GOOGLE_APPLICATION_CREDENTIALS (a service account JSON with the Vertex AI User role).
- Gemini API: an `api_key` (KINETRY_GOOGLE_API_KEY or GEMINI_API_KEY).

Requires `pip install 'kinetry[media]'` (google-genai).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from .base import Budget, MediaCache, MediaError, MediaResult
from .pricing import estimate_image, estimate_video

DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"
DEFAULT_VIDEO_MODEL = "veo-3.1-fast-generate-001"  # Vertex AI
DEFAULT_API_VIDEO_MODEL = "gemini-omni-1.1-flash"  # the Gemini API retired Veo for Omni (Interactions API)
VEO_SECONDS = (4, 6, 8)
OMNI_SECONDS = range(3, 11)
OMNI_USD_PER_TOKEN = 17.50 / 1_000_000  # video output; for the actual cost recorded from usage


def _sniff(data: bytes) -> tuple[str, str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise MediaError("reference images must be PNG, JPEG or WebP")


class GoogleMedia:
    name = "google"

    def __init__(
        self,
        *,
        cache: MediaCache,
        budget: Budget | None = None,
        project: str | None = None,
        location: str | None = None,
        api_key: str | None = None,
        image_model: str = DEFAULT_IMAGE_MODEL,
        video_model: str = DEFAULT_VIDEO_MODEL,
        client=None,
        sleep=time.sleep,
        poll_every: float = 10.0,
        timeout: float = 900.0,
    ):
        self.cache, self.budget = cache, budget or Budget(None)
        self.image_model, self.video_model = image_model, video_model
        self.project = project or os.environ.get("KINETRY_GOOGLE_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.environ.get("KINETRY_GOOGLE_LOCATION") or "us-central1"
        self.api_key = api_key or os.environ.get("KINETRY_GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        self._client, self._sleep, self.poll_every, self.timeout = client, sleep, poll_every, timeout

    @property
    def vertex(self) -> bool:
        return bool(self.project) and not self.api_key

    def client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError as e:
                raise MediaError("Google media needs: pip install 'kinetry[media]'") from e
            if self.vertex:
                self._client = genai.Client(vertexai=True, project=self.project, location=self.location)
            elif self.api_key:
                self._client = genai.Client(api_key=self.api_key)
            else:
                raise MediaError(
                    "No Google credentials: set KINETRY_GOOGLE_PROJECT (Vertex AI, with "
                    "GOOGLE_APPLICATION_CREDENTIALS) or KINETRY_GOOGLE_API_KEY (Gemini API)"
                )
        return self._client

    # ------------------------------------------------------------------ images
    def image(
        self, prompt: str, refs: list[bytes] | None = None, aspect: str = "1:1", model: str | None = None
    ) -> MediaResult:
        from google.genai import types

        model = model or self.image_model
        refs = list(refs or [])
        req = {"kind": "image", "prompt": prompt, "aspect": aspect}
        key = MediaCache.key(self.name, model, req, refs)
        hit = self.cache.get(key)
        if hit:
            return MediaResult(hit[0], hit[1].get("mime", "image/png"), 0.0, True, hit[1])
        usd = estimate_image(model)
        self.budget.charge(f"image ({model})", usd)
        try:
            parts = [types.Part.from_bytes(data=b, mime_type=_sniff(b)[0]) for b in refs] + [prompt]
            resp = self.client().models.generate_content(
                model=model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"], image_config=types.ImageConfig(aspect_ratio=aspect)
                ),
            )
            data = None
            for cand in resp.candidates or []:
                for part in (cand.content.parts if cand.content else None) or []:
                    if part.inline_data and part.inline_data.data:
                        data = part.inline_data.data
                        break
                if data:
                    break
            if not data:
                raise MediaError(f"{model} returned no image (it may have been filtered): {str(resp)[:300]}")
        except Exception:
            self.budget.refund(usd or 0.0)
            raise
        mime, ext = _sniff(data)
        meta = {"provider": self.name, "model": model, "request": req, "mime": mime, "usd": usd}
        return MediaResult(self.cache.put(key, data, ext, meta), mime, usd or 0.0, False, meta)

    # ------------------------------------------------------------------ video
    def video(
        self,
        prompt: str,
        image: bytes | None = None,
        seconds: int = 8,
        aspect: str = "9:16",
        resolution: str = "720p",
        audio: bool = False,
        negative: str | None = None,
        model: str | None = None,
    ) -> MediaResult:
        from google.genai import types

        model = model or (
            self.video_model if self.vertex or self.video_model != DEFAULT_VIDEO_MODEL else DEFAULT_API_VIDEO_MODEL
        )
        omni = model.startswith("gemini-omni")
        if omni and seconds not in OMNI_SECONDS:
            raise MediaError(f"Gemini Omni makes clips of 3 to 10 seconds, not {seconds}")
        if not omni and seconds not in VEO_SECONDS:
            raise MediaError(f"Veo makes clips of {VEO_SECONDS} seconds, not {seconds}")
        req = {
            "kind": "video",
            "prompt": prompt,
            "seconds": seconds,
            "aspect": aspect,
            "resolution": resolution,
            "audio": audio,
            "negative": negative,
        }
        key = MediaCache.key(self.name, model, req, [image] if image else [])
        hit = self.cache.get(key)
        if hit:
            return MediaResult(hit[0], "video/mp4", 0.0, True, hit[1])
        # The Gemini API doesn't take generate_audio (Veo 3 adds sound there anyway): price it with audio
        priced_audio = audio if self.vertex else True
        usd = estimate_video(model, seconds, resolution, priced_audio)
        self.budget.charge(f"{seconds}s video ({model}, {resolution})", usd)
        if omni:
            try:
                data, actual = self._omni(model, prompt, image, seconds, aspect, resolution)
            except Exception:
                self.budget.refund(usd or 0.0)
                raise
            meta = {
                "provider": self.name,
                "model": model,
                "request": req,
                "mime": "video/mp4",
                "usd": usd,
                "usd_from_usage": actual,
            }
            return MediaResult(self.cache.put(key, data, "mp4", meta), "video/mp4", usd or 0.0, False, meta)
        try:
            cfg = types.GenerateVideosConfig(
                number_of_videos=1,
                duration_seconds=seconds,
                aspect_ratio=aspect,
                resolution=resolution,
                negative_prompt=negative,
                **({"generate_audio": audio} if self.vertex else {}),
            )
            img = types.Image(image_bytes=image, mime_type=_sniff(image)[0]) if image else None
            cl = self.client()
            op = cl.models.generate_videos(model=model, prompt=prompt, image=img, config=cfg)
            waited = 0.0
            while not op.done:
                if waited >= self.timeout:
                    raise MediaError(f"{model} didn't finish within {self.timeout:.0f}s (operation {op.name})")
                self._sleep(self.poll_every)
                waited += self.poll_every
                op = cl.operations.get(op)
            if op.error:
                raise MediaError(f"{model} failed: {op.error}")
            vids = (op.response.generated_videos if op.response else None) or []
            if not vids:
                why = getattr(op.response, "rai_media_filtered_reasons", None) if op.response else None
                raise MediaError(f"{model} returned no video{f' (filtered: {why})' if why else ''}")
            v = vids[0].video
            data = v.video_bytes
            if not data and not self.vertex:
                data = cl.files.download(file=v)
            if not data:
                raise MediaError(
                    f"{model} stored the video at {v.uri}; Kinetry needs it returned inline (no output bucket)"
                )
        except Exception:
            self.budget.refund(usd or 0.0)
            raise
        meta = {"provider": self.name, "model": model, "request": req, "mime": "video/mp4", "usd": usd}
        return MediaResult(self.cache.put(key, data, "mp4", meta), "video/mp4", usd or 0.0, False, meta)

    def _omni(self, model, prompt, image, seconds, aspect, resolution) -> tuple[bytes, float | None]:
        """Gemini Omni through the Interactions API: a background interaction, polled until it's done."""
        import base64

        cl = self.client()
        parts = []
        if image:
            parts.append({"type": "image", "data": base64.b64encode(image).decode(), "mime_type": _sniff(image)[0]})
        parts.append({"type": "text", "text": prompt})
        it = cl.interactions.create(
            model=model,
            input=parts,
            response_modalities=["video"],
            response_format={
                "type": "video",
                "aspect_ratio": aspect,
                "resolution": resolution,
                "duration": f"{seconds}s",
                "delivery": "inline",
            },
            generation_config={"video_config": {"task": "image_to_video" if image else "text_to_video"}},
            background=True,
        )
        waited = 0.0
        state = lambda i: str(i.status).lower().rsplit(".", 1)[-1]  # noqa: E731
        while state(it) in ("in_progress", "queued", "pending", "running"):
            if waited >= self.timeout:
                raise MediaError(f"{model} didn't finish within {self.timeout:.0f}s (interaction {it.id})")
            self._sleep(self.poll_every)
            waited += self.poll_every
            it = cl.interactions.get(id=it.id)
        if state(it) != "completed" or it.output_video is None or not it.output_video.data:
            raise MediaError(f"{model} returned no video (status {it.status}): {it.errors}")
        d = it.output_video.data
        data = base64.b64decode(d) if isinstance(d, str) else bytes(d)
        out_tokens = None
        for m in (getattr(it.usage, "output_tokens_by_modality", None) or []) if it.usage else []:
            if str(m.modality).lower().endswith("video"):
                out_tokens = m.tokens
        return data, (round(out_tokens * OMNI_USD_PER_TOKEN, 4) if out_tokens else None)


def make_google(cache_dir: Path, cap: float | None = None, **kw) -> GoogleMedia:
    return GoogleMedia(cache=MediaCache(cache_dir), budget=Budget(cap), **kw)
