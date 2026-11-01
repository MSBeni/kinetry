"""Background video jobs, shared by the HTTP service, the MCP server and the LangChain tools.

Rendering takes minutes, so callers start a job and poll. Jobs and brand packs
are stored as plain files under a data directory, so a restart doesn't lose
finished work (jobs that were mid-render are marked 'interrupted').

This in-process runner fits one container. For fleet scale, put `run_job`
behind your own queue (SQS, Celery, Cloud Tasks) - it only needs the job dir.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import ValidationError

from .api import Kinetry
from .branding import BrandPack
from .design.catalog import load_catalog
from .design.plan import Design, VideoPlan2, load_plan
from .design.profile import BrandProfile
from .llm import PROVIDERS, LLMConfig
from .netguard import check_public_url
from .sources import Source
from .voice import GEMINI_TTS_MODELS, INWORLD_MODELS, VOICE_PREFIXES, parse_gemini, parse_inworld

ALLOWED_VOICE_PREFIXES = VOICE_PREFIXES
CLOUD_VOICES = ("openai:", "elevenlabs:", "inworld:", "gemini:")
VOICE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
ROLE_ID = re.compile(r"[A-Za-z0-9_]{1,24}")
__all__ = ["JobManager", "check_public_url", "check_voice", "check_llm", "check_design", "check_profile", "redact"]


def check_voice(voice: str | None, voice_api_key: str | None = None, mode: str | None = None) -> str | None:
    """Known providers only (KINETRY_VOICE_PROVIDERS narrows them). Cloud voices need the caller's
    own key unless the operator lends theirs (KINETRY_CLIENT_LLM=any)."""
    if not voice:
        return voice
    allowed = (
        tuple(f"{p.strip()}:" for p in os.environ.get("KINETRY_VOICE_PROVIDERS", "").split(",") if p.strip())
        or ALLOWED_VOICE_PREFIXES
    )
    if not voice.startswith(allowed):
        raise ValueError(f"voice must start with one of {allowed}")
    provider, _, vid = voice.partition(":")
    if provider == "inworld":  # inworld:<voice> or inworld:<model>:<voice>
        model, vid = parse_inworld(vid)
        if model not in INWORLD_MODELS:
            raise ValueError(f"inworld model must be one of {', '.join(INWORLD_MODELS)}")
        if not vid:
            raise ValueError("inworld voice needs a voice id: inworld:<voice_id> or inworld:<model>:<voice_id>")
    if provider == "gemini":  # gemini:<voice> or gemini:<model>:<voice>
        model, vid = parse_gemini(vid)
        if model not in GEMINI_TTS_MODELS:
            raise ValueError(f"gemini model must be one of {', '.join(GEMINI_TTS_MODELS)}")
    design_text = provider == "voicestudio" and vid.startswith("design=")
    if vid and not design_text and not VOICE_ID.fullmatch(vid):
        raise ValueError("voice ids may only contain letters, digits, '-' and '_'")
    if design_text and len(vid) > 300:
        raise ValueError("voice design description is too long")
    mode = (mode or os.environ.get("KINETRY_CLIENT_LLM", "byok")).lower()
    if voice.startswith(CLOUD_VOICES) and not voice_api_key and mode != "any":
        raise ValueError(f"send voice_api_key with '{voice.split(':')[0]}' voices; this server doesn't lend its own")
    return voice


def check_llm(
    llm: LLMConfig | dict | None,
    *,
    mode: str | None = None,
    providers: str | None = None,
    allow_private: bool = False,
    require_model: bool = True,
) -> LLMConfig | None:
    """Validate a caller-chosen model against the operator's policy.

    KINETRY_CLIENT_LLM:    off  - callers always get the server's model
                             byok - (default) callers may choose a model if they bring their own key
                             any  - callers may also choose models billed to the server's credentials
    KINETRY_LLM_PROVIDERS: comma list of providers callers may use (default: the built-in ones)
    """
    if llm is None:
        return None
    cfg = llm if isinstance(llm, LLMConfig) else LLMConfig(**llm)
    mode = (mode or os.environ.get("KINETRY_CLIENT_LLM", "byok")).lower()
    allowed = {
        p.strip() for p in (providers or os.environ.get("KINETRY_LLM_PROVIDERS") or ",".join(PROVIDERS)).split(",")
    }
    if mode == "off":
        raise ValueError("this server doesn't accept a caller-chosen llm (KINETRY_CLIENT_LLM=off)")
    if cfg.provider not in allowed:
        raise ValueError(f"llm provider '{cfg.provider}' isn't enabled here; allowed: {sorted(allowed)}")
    has_key = bool(cfg.api_key) or bool(cfg.aws_access_key_id and cfg.aws_secret_access_key)
    if mode == "byok" and not has_key:
        raise ValueError("send your own api_key (or AWS keys for bedrock) with llm; this server doesn't lend its own")
    if cfg.aws_profile:
        raise ValueError("aws_profile can't be chosen by callers")
    if cfg.extra:
        raise ValueError("llm.extra can't be set by callers")
    if cfg.base_url or cfg.provider in ("azure", "openai_compatible"):
        # a caller-chosen endpoint never gets the server's credentials
        if cfg.provider not in ("openai", "openai_compatible", "azure"):
            raise ValueError(f"base_url can't be set for provider '{cfg.provider}'")
        if not cfg.api_key:
            raise ValueError("send your own api_key with a custom base_url")
        if cfg.base_url:
            check_public_url(cfg.base_url, allow_private, what="llm.base_url")  # the key and prompts go there
            cfg.public_only = not allow_private  # and every connection goes to the address that was checked
    if require_model and not cfg.model:
        raise ValueError(f"llm.model is required for provider '{cfg.provider}'")
    return cfg


def check_package(p: dict | None) -> dict | None:
    """{"standard": "scorm12"|"scorm2004"|"web", "quiz": 0-6 questions, "mastery": 0-100} -> normalized, or None."""
    if not p:
        return None
    if not isinstance(p, dict):
        raise ValueError('package must be an object like {"standard": "scorm12"}')
    from .package import STANDARDS

    std = p.get("standard", "scorm12")
    if std not in STANDARDS:
        raise ValueError(f"package.standard must be one of {', '.join(STANDARDS)}")
    quiz = p.get("quiz", 3)
    if isinstance(quiz, bool) or not isinstance(quiz, int) or not 0 <= quiz <= 6:
        raise ValueError("package.quiz is the number of questions, 0-6 (0 leaves the knowledge check out)")
    mastery = p.get("mastery", 80)
    if isinstance(mastery, bool) or not isinstance(mastery, int) or not 0 <= mastery <= 100:
        raise ValueError("package.mastery is the passing score in percent, 0-100")
    extra = set(p) - {"standard", "quiz", "mastery"}
    if extra:
        raise ValueError(f"package: unknown field {sorted(extra)[0]!r}")
    return {"standard": std, "quiz": quiz, "mastery": mastery}


def check_design(design: dict | None) -> dict:
    """Validate a caller's design choices against the catalog."""
    if not design:
        return {}
    d = Design.model_validate(design)
    cat = load_catalog()
    for key, pool in (("style", cat.styles), ("motion", cat.motions), ("transition", cat.transitions)):
        v = getattr(d, key)
        if v and v not in pool:
            raise ValueError(f"design.{key} '{v}' unknown; use one of {sorted(pool)}")
    return d.model_dump(exclude_defaults=True)


def check_profile(profile: dict | BrandProfile) -> BrandProfile:
    """Validate a brand profile from a caller: catalog names, formats, voices; no server paths."""
    prof = profile if isinstance(profile, BrandProfile) else BrandProfile.model_validate(profile)
    if prof.music:
        raise ValueError("music beds are configured on the server, not per request")
    cat = load_catalog()
    bad = [s for s in prof.styles + ([prof.style] if prof.style else []) if s not in cat.styles]
    bad += [c for c in prof.avoid_components + prof.prefer_components if c not in cat.components]
    if prof.motion and prof.motion not in cat.motions:
        bad.append(prof.motion)
    if prof.transition and prof.transition not in cat.transitions:
        bad.append(prof.transition)
    if bad:
        raise ValueError(f"unknown styles, scene types, motions or transitions: {bad}")
    if prof.format and prof.format not in ("16:9", "9:16", "1:1"):
        raise ValueError("format must be 16:9, 9:16 or 1:1")
    if prof.pacing and prof.pacing not in ("calm", "normal", "brisk"):
        raise ValueError("pacing must be calm, normal or brisk")
    for role, spec in prof.voices.items():
        if not ROLE_ID.fullmatch(str(role)):
            raise ValueError(f"bad voice role '{role}'")
        check_voice(spec)
    return prof


def redact(text: str | None, cfg: LLMConfig | None, *extra: str | None) -> str | None:
    if not text:
        return text
    secrets = list(extra)
    if cfg is not None:
        secrets += [
            s.get_secret_value()
            for s in (cfg.api_key, cfg.aws_access_key_id, cfg.aws_secret_access_key, cfg.aws_session_token)
            if s
        ]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


class JobManager:
    def __init__(
        self,
        tf: Kinetry | None = None,
        data_dir: str | Path | None = None,
        workers: int | None = None,
        allow_private_urls: bool | None = None,
    ):
        self.tf = tf or Kinetry()
        self.data = Path(data_dir or os.environ.get("KINETRY_DATA_DIR", self.tf.settings.home / "data"))
        (self.data / "jobs").mkdir(parents=True, exist_ok=True)
        (self.data / "brands").mkdir(parents=True, exist_ok=True)
        self.allow_private = (
            allow_private_urls
            if allow_private_urls is not None
            else os.environ.get("KINETRY_ALLOW_PRIVATE_URLS", "") == "1"
        )
        self.tf.settings.public_urls_only = not self.allow_private  # brand fetches, redirects, probe requests
        from .delivery import S3Storage

        self.storage = S3Storage.from_env()  # None unless KINETRY_S3_BUCKET is set
        self.tf.settings.images_dir = self.data / "images"  # upload:<id> images (POST /v1/images)
        self.public_url = os.environ.get("KINETRY_PUBLIC_URL", "").rstrip("/")  # for absolute links in callbacks
        self.pool = ThreadPoolExecutor(max_workers=workers or int(os.environ.get("KINETRY_WORKERS", "1")))
        self._lock = threading.Lock()
        for f in (self.data / "jobs").glob("*/job.json"):  # recover after restart
            j = json.loads(f.read_text())
            if j["status"] in ("queued", "running"):
                j.update(status="interrupted", error="service restarted before the job finished")
                f.write_text(json.dumps(j, indent=2))

    # ------------------------------------------------------------ brands
    def check_llm(self, llm: LLMConfig | dict | None, require_model: bool = True) -> LLMConfig | None:
        return check_llm(llm, allow_private=self.allow_private, require_model=require_model)

    def create_brand(self, url: str, use_logo: bool = True, llm: LLMConfig | dict | None = None) -> dict:
        check_public_url(url, self.allow_private)
        cfg = self.check_llm(llm)
        bid = uuid.uuid4().hex[:12]
        pack = self.tf.brand(url, use_logo=use_logo, run_dir=self.data / "brands" / bid / "run", llm=cfg)
        pack.notes = [redact(n, cfg) for n in pack.notes]
        pack.save(self.data / "brands" / bid)
        return self.brand_info(bid)

    def brand_dir(self, brand_id: str) -> Path:
        if not brand_id.isalnum():
            raise ValueError("bad brand id")
        d = self.data / "brands" / brand_id
        if not (d / "brand.json").exists():
            raise KeyError(brand_id)
        return d

    def brand_info(self, brand_id: str) -> dict:
        pack = BrandPack.load(self.brand_dir(brand_id))
        return {
            "brand_id": brand_id,
            "kit": pack.kit.model_dump(),
            "logo": bool(pack.logo),
            "mark": bool(pack.mark),
            "notes": pack.notes,
            "profile": pack.profile.model_dump(exclude_defaults=True),
            "assets3d": [a.model_dump(exclude={"facts"}) for a in pack.assets3d],
        }

    # the brand's own 3D models and logo symbol (kinetry.brand3d)
    def add_asset3d(
        self,
        brand_id: str,
        data: bytes,
        *,
        name: str = "",
        about: str = "",
        tags: list[str] | None = None,
        role: str | None = None,
        llm: LLMConfig | dict | None = None,
    ) -> dict:
        from .brand3d import add_asset

        d = self.brand_dir(brand_id)
        cfg = self.check_llm(llm, require_model=False) if llm else None
        a = add_asset(d, data, name=name, about=about, tags=tags, role=role, source="upload", llm=cfg,
                      settings=self.tf.settings)  # fmt: skip
        return a.model_dump(exclude={"facts"}) | {"facts": a.facts}

    def assets3d(self, brand_id: str) -> list[dict]:
        from .brand3d import load_library

        return [a.model_dump() for a in load_library(self.brand_dir(brand_id))]

    def remove_asset3d(self, brand_id: str, asset_id: str) -> bool:
        from .brand3d import remove_asset

        return remove_asset(self.brand_dir(brand_id), asset_id)

    def set_mark(self, brand_id: str, svg: bytes) -> dict:
        from .design.depth import logo_mark

        d = self.brand_dir(brand_id)
        if not logo_mark(("mark.svg", svg), None):
            raise ValueError("the mark must be an SVG file with <path> shapes, under 300 KB")
        pack = BrandPack.load(d)
        pack.mark = ("mark.svg", svg)
        pack.save(d)
        return self.brand_info(brand_id)

    def set_profile(self, brand_id: str, profile: dict) -> dict:
        """Standing design preferences for a brand. Server file paths (music) can't be set by callers."""
        d = self.brand_dir(brand_id)
        check_profile(profile).save(d)
        return self.brand_info(brand_id)

    def plan(self, source: Source, *, brand_id: str | None = None, design: dict | None = None, llm=None) -> VideoPlan2:
        """A reviewable plan in the brand's look and within its profile. Nothing is kept on disk."""
        design = check_design(design)
        brand = BrandPack.load(self.brand_dir(brand_id)) if brand_id else None
        with tempfile.TemporaryDirectory(prefix="kinetry-plan-") as tmp:
            return self.tf.plan(source, brand=brand, design=design, llm=llm, run_dir=tmp)

    def brief(self, message: str, *, llm=None):
        """A request in plain words -> brief.Brief (kind, audience, length, look, pasted content, questions)."""
        from .brief import make_brief

        return make_brief(message, llm=llm, settings=self.tf.settings)

    # ------------------------------------------------------------ videos
    def _job_path(self, job_id: str) -> Path:
        if not job_id.isalnum():
            raise ValueError("bad job id")
        return self.data / "jobs" / job_id / "job.json"

    def _save(self, job: dict) -> None:
        with self._lock:
            p = self._job_path(job["job_id"])
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(job, indent=2, default=str))
            tmp.replace(p)

    def get(self, job_id: str) -> dict:
        p = self._job_path(job_id)
        if not p.exists():
            raise KeyError(job_id)
        return json.loads(p.read_text())

    def _check_images(self, context: dict) -> None:
        """Fail at submit time, not mid-render: the service takes only https URLs, uploads, brand and samples."""
        import re

        from .design.planner import context_images

        for im in context_images(context) + context_images(context, "animations"):
            ref = im["ref"]
            if re.match(r"(?i)^https?://", ref):
                check_public_url(ref, self.allow_private, what="context.images")
            elif not re.match(r"^(upload|brand|catalog):", ref):
                raise ValueError(
                    f"context.images: '{ref[:80]}' must be an https URL, upload:<id> (POST /v1/images) or brand:<n>"
                )

    def start(
        self,
        *,
        source: Source | None = None,
        plan: VideoPlan2 | dict | None = None,
        brand_id: str | None = None,
        brand_url: str | None = None,
        voice: str | None = None,
        use_logo: bool = True,
        metadata: dict | None = None,
        llm: LLMConfig | dict | None = None,
        voice_api_key: str | None = None,
        design: dict | None = None,
        voices: dict | None = None,
        voice_check: bool = False,
        stt_api_key: str | None = None,
        quality: str | int | None = None,
        callback_url: str | None = None,
        package: dict | None = None,
    ) -> dict:
        """`llm`: optional caller-chosen model (see check_llm). Its keys live only in memory for
        the duration of the job; job.json records provider and model only.
        `design`: explicit look (style, format, transition, captions, pacing); the rest is chosen automatically.
        `voices`: voice per speaker role for dialogue scenes, e.g. {"a": "kokoro:am_michael"}.
        `voice_check`: transcribe every narrated beat with Inworld inworld-stt-1 and score it against the script.
        Needs the caller's Inworld key (`stt_api_key`, or `voice_api_key` when the narrator is an inworld: voice)."""
        if (source is None) == (plan is None):
            raise ValueError("give exactly one of source or plan")
        if brand_id and brand_url:
            raise ValueError("give brand_id or brand_url, not both")
        brand: str | None = None
        if brand_id:
            brand = str(self.brand_dir(brand_id))
        elif brand_url:
            brand = check_public_url(brand_url, self.allow_private)
        check_voice(voice, voice_api_key)
        for role, spec in (voices or {}).items():
            if not ROLE_ID.fullmatch(str(role)):
                raise ValueError(f"bad voice role '{role}'")
            check_voice(spec, voice_api_key)
        design = check_design(design)
        if source is not None:
            self._check_images(source.context)
        if callback_url:
            if not callback_url.startswith(("https://", "http://")) or len(callback_url) > 2000:
                raise ValueError("callback_url must be an http(s) URL")
            try:
                check_public_url(callback_url, self.allow_private, what="callback_url")
            except ValueError as e:
                raise ValueError(f"callback_url: {e}") from e
        if quality is not None:
            from . import hf

            hf.quality_args(quality)
        if voice_check:
            if not stt_api_key and (voice or "").startswith("inworld:"):
                stt_api_key = voice_api_key  # same Inworld account for speaking and listening
            if not stt_api_key:
                raise ValueError("voice_check needs your Inworld key (stt_api_key); this server doesn't lend its own")
        else:
            stt_api_key = None
        package = check_package(package)
        cfg = self.check_llm(llm)
        if plan is not None:
            try:
                plan = load_plan(plan)
            except (ValidationError, TypeError, KeyError, AttributeError) as e:
                raise ValueError(f"plan isn't a valid video plan: {str(e)[:300]}") from e
            for role, spec in plan.voices.items():  # voices inside a plan follow the same policy
                if not ROLE_ID.fullmatch(str(role)):
                    raise ValueError(f"bad voice role '{role}' in plan.voices")
                check_voice(spec, voice_api_key)
            errs = load_catalog().validate_plan(plan)
            if errs:
                raise ValueError("plan doesn't match the catalog: " + "; ".join(errs[:8]))
        job_id = uuid.uuid4().hex[:16]
        job = {
            "job_id": job_id,
            "status": "queued",
            "step": None,
            "created": time.time(),
            "error": None,
            "metadata": metadata or {},
            "brand": brand_id or brand_url,
            "voice": voice,
            "voices": voices or {},
            "design": design,
            "voice_check": bool(voice_check),
            "quality": quality,
            "callback_url": callback_url,
            "package": package,
            "llm": cfg.public() if cfg else None,
        }
        self._save(job)
        self.pool.submit(
            self._run,
            job_id,
            source,
            plan,
            brand,
            voice,
            use_logo,
            cfg,
            voice_api_key,
            design,
            voices,
            stt_api_key,
            quality,
            package,
        )
        return job

    def _run(
        self,
        job_id,
        source,
        plan,
        brand,
        voice,
        use_logo,
        llm=None,
        voice_api_key=None,
        design=None,
        voices=None,
        stt_api_key=None,
        quality=None,
        package=None,
    ) -> None:
        job = self.get(job_id)
        job["status"] = "running"
        self._save(job)
        run_dir = self.data / "jobs" / job_id / "run"
        out = self.data / "jobs" / job_id / "video.mp4"

        def on_event(ev: dict) -> None:
            j = self.get(job_id)
            j["step"] = ev["step"]
            self._save(j)

        try:
            common = dict(
                brand=brand,
                out=out,
                voice=voice,
                run_dir=run_dir,
                use_logo=use_logo,
                on_event=on_event,
                llm=llm,
                design=design,
                voices=voices,
                voice_api_key=voice_api_key,  # memory only: used to build cloud voices, never stored
                voice_check=bool(stt_api_key),
                stt_api_key=stt_api_key,  # memory only, like voice_api_key
                quality=quality,
            )
            res = self.tf.render(plan, **common) if plan is not None else self.tf.generate(source, **common)
            job = self.get(job_id)
            job.update(
                status=res.status,
                error=redact(res.error, llm, voice_api_key, stt_api_key),
                duration=res.duration,
                finished=time.time(),
                video=str(res.video) if res.video else None,
                frames=len(res.qa_frames),
                plan=res.plan.model_dump() if res.plan else None,
                voice_check=res.voice_check,
            )
            if package and res.status == "done":
                job["package"] = self._package(job_id, res, package, llm)
        except Exception as e:  # noqa: BLE001
            job = self.get(job_id)
            job.update(
                status="error",
                error=redact(f"{type(e).__name__}: {e}", llm, voice_api_key, stt_api_key),
                finished=time.time(),
            )
        self._save(job)
        self._deliver(job_id)

    def _package(self, job_id: str, res, opts: dict, llm=None) -> dict:
        """The finished video as an LMS package next to it; a failure here leaves the video done."""
        dest = self.data / "jobs" / job_id / "package.zip"
        try:
            pkg = self.tf.package(
                res,
                out=dest,
                standard=opts["standard"],
                quiz=opts["quiz"] > 0,
                questions=opts["quiz"] or 3,
                mastery=opts["mastery"],
                llm=llm,
            )
            return {**opts, "file": str(pkg.path), "questions": pkg.questions, "notes": pkg.notes}
        except Exception as e:  # noqa: BLE001
            return {**opts, "error": redact(f"{type(e).__name__}: {e}", llm)[:300]}

    def package_path(self, job_id: str) -> Path:
        j = self.get(job_id)
        f = (j.get("package") or {}).get("file")
        if j.get("status") != "done" or not f or not Path(f).exists():
            raise FileNotFoundError(job_id)
        return Path(f)

    def _deliver(self, job_id: str) -> None:
        """Upload the finished video (when storage is configured), then call the caller back (when asked)."""
        from .delivery import callback_secret, notify

        job = self.get(job_id)
        if self.storage and job["status"] == "done" and job.get("video") and Path(job["video"]).exists():
            try:
                job["storage"] = self.storage.upload(job_id, Path(job["video"]))
            except Exception as e:  # noqa: BLE001  (the video is still served locally)
                job["storage"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            self._save(job)
        if job.get("callback_url"):
            base = f"{self.public_url}/v1/videos/{job_id}"
            payload = {
                "event": "video.finished",
                "job_id": job_id,
                "status": job["status"],
                "error": job.get("error"),
                "duration": job.get("duration"),
                "metadata": job.get("metadata") or {},
                "status_url": base,
                **({"video_url": f"{base}/video"} if job["status"] == "done" else {}),
                **({"package_url": f"{base}/package"} if (job.get("package") or {}).get("file") else {}),
                **({"storage": job["storage"]} if job.get("storage") else {}),
            }
            job["callback"] = notify(
                job["callback_url"], payload, allow_private=self.allow_private, secret=callback_secret()
            )
            self._save(job)

    def video_path(self, job_id: str) -> Path:
        j = self.get(job_id)
        if j.get("status") != "done" or not j.get("video"):
            raise FileNotFoundError(job_id)
        return Path(j["video"])

    def frame_path(self, job_id: str, n: int) -> Path:
        frames = sorted((self.data / "jobs" / job_id / "run" / "qa").glob("frame-*.png"))
        if not 0 <= n < len(frames):
            raise FileNotFoundError(n)
        return frames[n]

    def wait(self, job_id: str, timeout: float = 1800, poll: float = 2.0) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            j = self.get(job_id)
            if j["status"] not in ("queued", "running"):
                return j
            time.sleep(poll)
        raise TimeoutError(job_id)
