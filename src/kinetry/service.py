"""HTTP API. Run with `kinetry serve` or `uvicorn kinetry.service:app`.

    GET  /v1/catalog                                                      -> scene types, layouts, styles, transitions
    POST /v1/brands              {"url": "https://acme.com"}              -> brand pack (cache it per client)
    GET  /v1/brands/{id}
    PUT  /v1/brands/{id}/profile {"styles": [...], "format": "9:16", ...} -> standing design preferences
    POST /v1/brands/{id}/assets3d  multipart: file (.glb), name?, about?, tags?, role?  -> the brand's 3D model
    GET  /v1/brands/{id}/assets3d                                         -> its 3D models, as the asset agent read them
    DELETE /v1/brands/{id}/assets3d/{asset_id}
    PUT  /v1/brands/{id}/mark    multipart: file (SVG)                    -> the logo's symbol, shown in 3D
    POST /v1/plans               {"source", "brand_id"?, "design"?}       -> plan JSON (design + layouts filled) to review
    POST /v1/videos              {"source"|"plan", "brand_id"|"brand_url", "voice", "voices", "design", "llm"} -> 202
    POST /v1/models              {"llm": {"provider": ..., "api_key": ...}}  -> models those credentials can use
    POST /v1/voices/design       {"name", "description"}                  -> VoiceStudio profile (voice "voicestudio:<id>")
    POST /v1/voices/clone        multipart: name, ref_audio, consent_audio, consent_text  (KINETRY_VOICE_CLONING=1)
    GET  /v1/videos/{id}                                                  -> status, step, duration, plan
    GET  /v1/videos/{id}/video                                            -> MP4
    GET  /v1/videos/{id}/frames/{n}                                       -> QA frame PNG

Auth: set KINETRY_API_KEY and send `Authorization: Bearer <key>`. Without a key the
service only accepts requests from localhost.

Model choice: brands, plans and videos take an optional "llm" block, e.g.
    {"provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": "sk-ant-..."}
    {"provider": "bedrock", "model": "amazon.nova-pro-v1:0", "region": "us-west-2",
     "aws_access_key_id": "...", "aws_secret_access_key": "..."}
    {"provider": "openai_compatible", "model": "meta-llama/llama-3.3-70b-instruct",
     "base_url": "https://openrouter.ai/api/v1", "api_key": "..."}
Keys are used for that request only: never stored, logged or returned. The operator controls this
with KINETRY_CLIENT_LLM (off | byok | any) and KINETRY_LLM_PROVIDERS.
"""

from __future__ import annotations

import hmac
import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr

from . import __version__
from .design.catalog import load_catalog
from .design.plan import Design
from .jobs import JobManager, check_design, check_voice, redact
from .llm import LLMConfig
from .sources import Source

app = FastAPI(title="Kinetry", version=__version__)
_jobs: JobManager | None = None


def jobs() -> JobManager:
    global _jobs
    if _jobs is None:
        _jobs = JobManager()
    return _jobs


def set_job_manager(jm: JobManager) -> None:
    """Inject a configured JobManager (custom LLM, voice, data dir) when embedding the app."""
    global _jobs
    _jobs = jm


def auth(request: Request) -> None:
    key = os.environ.get("KINETRY_API_KEY")
    if key:
        got = request.headers.get("authorization", "")
        if not hmac.compare_digest(got, f"Bearer {key}"):
            raise HTTPException(401, "invalid or missing bearer token")
    elif request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "set KINETRY_API_KEY to accept non-local requests")


class LLMRequest(BaseModel):
    provider: str = Field(description="anthropic | openai | bedrock | google | azure | openai_compatible | ...")
    model: str = Field("", description="model id; for bedrock any model id or inference profile")
    api_key: SecretStr | None = Field(None, description="your key; for bedrock, a Bedrock API key")
    base_url: str | None = None
    api_version: str | None = None
    region: str | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None

    def config(self) -> LLMConfig:
        return LLMConfig(**self.model_dump())


def _cfg(llm: LLMRequest | None) -> LLMConfig | None:
    return jobs().check_llm(llm.config()) if llm else None


class BrandRequest(BaseModel):
    url: str
    use_logo: bool = True
    llm: LLMRequest | None = None


class PlanRequest(BaseModel):
    source: Source
    brand_id: str | None = None
    design: Design | None = Field(None, description="Pin any part of the look; the rest is chosen automatically")
    llm: LLMRequest | None = None


class ModelsRequest(BaseModel):
    llm: LLMRequest


class VideoRequest(BaseModel):
    source: Source | None = None
    plan: dict | None = Field(None, description="A reviewed plan (v2; v1 plans are upgraded)")
    design: Design | None = Field(None, description="Pin any part of the look: style, format, transition, captions...")
    voices: dict[str, str] = Field(
        default_factory=dict, description="Voice per dialogue speaker, e.g. {'a': 'kokoro:am_michael'}"
    )
    brand_id: str | None = None
    brand_url: str | None = None
    voice: str | None = Field(
        None,
        description="kokoro:<voice>, voicestudio:<profile_id>, openai:<voice>, elevenlabs:<voice_id> or "
        "inworld:[<model>:]<voice_id>",
    )
    voice_api_key: SecretStr | None = Field(None, description="your key for openai:/elevenlabs:/inworld: voices")
    voice_check: bool = Field(
        False, description="Listen back to every narrated line with Inworld inworld-stt-1 and score it vs the script"
    )
    stt_api_key: SecretStr | None = Field(
        None, description="your Inworld key for voice_check (defaults to voice_api_key with inworld: voices)"
    )
    use_logo: bool = True
    callback_url: str | None = Field(
        None, max_length=2000, description="POSTed a signed JSON summary when the job finishes (see delivery.py)"
    )
    quality: str | int | None = Field(
        None, description="draft | standard (default, small files) | high (near-lossless), or a CRF number 0-51"
    )
    metadata: dict = Field(default_factory=dict, description="Your ids (course, session, tenant); echoed back")
    package: dict | None = Field(
        None,
        description='Also build an LMS package: {"standard": "scorm12" | "scorm2004" | "web", "quiz": 0-6, '
        '"mastery": 0-100}. Download it from /v1/videos/{id}/package',
    )
    llm: LLMRequest | None = None


def _bad(e: Exception):
    raise HTTPException(400, str(e)) from e


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/v1/catalog", dependencies=[Depends(auth)])
def catalog() -> dict:
    cat = load_catalog()
    return {**cat.to_dict(), "combinations": cat.combinations()}


@app.get("/v1/kinds", dependencies=[Depends(auth)])
def video_kinds() -> dict:
    """Video kinds a source can name (source.kind): what each is for and its default length."""
    from .kinds import kinds_guide

    return {"kinds": kinds_guide()}


class BriefRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=200_000, description="The request in plain words, any language")
    llm: LLMRequest | None = None


@app.post("/v1/briefs", dependencies=[Depends(auth)])
def create_brief(req: BriefRequest) -> dict:
    """Turn a request in plain words into a structured brief and a request body for /v1/plans or /v1/videos.
    `brief.questions` lists what's missing (most often the content); `request.source` is null until there is
    source text, and `request.pending_source.url` is a link to read with /v1/sources/url."""
    try:
        cfg = _cfg(req.llm)
    except ValueError as e:
        _bad(e)
    try:
        b = jobs().brief(req.message, llm=cfg)
    except ValueError as e:
        _bad(e)
    return {"brief": b.model_dump(), "request": b.to_request()}


@app.post("/v1/brands", dependencies=[Depends(auth)])
def create_brand(req: BrandRequest) -> dict:
    try:
        return jobs().create_brand(req.url, req.use_logo, llm=_cfg(req.llm))
    except ValueError as e:
        _bad(e)


@app.get("/v1/brands/{brand_id}", dependencies=[Depends(auth)])
def get_brand(brand_id: str) -> dict:
    try:
        return jobs().brand_info(brand_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(404, "brand not found") from e


@app.put("/v1/brands/{brand_id}/profile", dependencies=[Depends(auth)])
def put_profile(brand_id: str, profile: dict) -> dict:
    try:
        return jobs().set_profile(brand_id, profile)
    except KeyError as e:
        raise HTTPException(404, "brand not found") from e
    except ValueError as e:
        _bad(e)


@app.post("/v1/brands/{brand_id}/assets3d", dependencies=[Depends(auth)])
async def add_asset3d(
    brand_id: str,
    file: UploadFile = File(..., description="A 3D model as binary glTF (.glb), everything embedded, up to 25 MB"),
    name: str = Form("", max_length=80),
    about: str = Form("", max_length=300, description="what it is; else the asset agent describes it"),
    tags: str = Form("", max_length=300, description="comma list of words a script about it would use"),
    role: str = Form("", description="hero or logo: title and closing scenes; prop: wherever a scene leaves room"),
) -> dict:
    """Add one of the brand's own 3D models (a product, vehicle, mascot, the logo). It's checked (GLB only,
    embedded files, no decoder-only compression), read (parts, colors, size, animations) and described, then
    shown on the 3D stage (design.effects.depth) where the asset agent matches it to a scene."""
    from .brand3d import MAX_GLB_BYTES, AssetError, nice_name

    data = await file.read(MAX_GLB_BYTES + 1)
    try:
        return jobs().add_asset3d(
            brand_id,
            data,
            name=name or nice_name(Path(file.filename or "").stem),
            about=about,
            tags=[t for t in tags.split(",") if t.strip()] or None,
            role=role or None,
        )
    except KeyError as e:
        raise HTTPException(404, "brand not found") from e
    except AssetError as e:
        raise HTTPException(413 if len(data) > MAX_GLB_BYTES else 415, str(e)) from e
    except ValueError as e:
        _bad(e)


@app.get("/v1/brands/{brand_id}/assets3d", dependencies=[Depends(auth)])
def list_assets3d(brand_id: str) -> dict:
    try:
        return {"assets3d": jobs().assets3d(brand_id)}
    except (KeyError, ValueError) as e:
        raise HTTPException(404, "brand not found") from e


@app.delete("/v1/brands/{brand_id}/assets3d/{asset_id}", dependencies=[Depends(auth)])
def delete_asset3d(brand_id: str, asset_id: str) -> dict:
    try:
        if not jobs().remove_asset3d(brand_id, asset_id):
            raise HTTPException(404, "no such 3D model")
    except (KeyError, ValueError) as e:
        raise HTTPException(404, "brand not found") from e
    return {"removed": asset_id}


@app.put("/v1/brands/{brand_id}/mark", dependencies=[Depends(auth)])
async def put_mark(brand_id: str, file: UploadFile = File(..., description="The logo's symbol alone, as SVG")) -> dict:
    data = await file.read(300_001)
    try:
        return jobs().set_mark(brand_id, data)
    except KeyError as e:
        raise HTTPException(404, "brand not found") from e
    except ValueError as e:
        _bad(e)


@app.post("/v1/plans", dependencies=[Depends(auth)])
def create_plan(req: PlanRequest) -> dict:
    try:
        cfg = _cfg(req.llm)
        design = check_design(req.design.model_dump(exclude_defaults=True) if req.design else None)
        if req.brand_id:
            jobs().brand_dir(req.brand_id)
    except KeyError as e:
        raise HTTPException(404, "brand not found") from e
    except ValueError as e:
        _bad(e)
    try:
        return jobs().plan(req.source, brand_id=req.brand_id, design=design, llm=cfg).model_dump()
    except Exception as e:  # noqa: BLE001  (provider errors: bad key, unknown model, quota)
        raise HTTPException(502, redact(f"planning failed: {type(e).__name__}: {e}", cfg)[:500]) from e


@app.post("/v1/models", dependencies=[Depends(auth)])
def list_provider_models(req: ModelsRequest) -> dict:
    from .llm import list_models

    try:
        cfg = jobs().check_llm(req.llm.config(), require_model=False)
    except ValueError as e:
        _bad(e)
    try:
        return {"provider": cfg.provider, "models": list_models(cfg)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, redact(f"could not list models: {type(e).__name__}: {e}", cfg)[:500]) from e


@app.post("/v1/videos", status_code=202, dependencies=[Depends(auth)])
def create_video(req: VideoRequest) -> dict:
    try:
        vkey = req.voice_api_key.get_secret_value() if req.voice_api_key else None
        check_voice(req.voice, vkey)
        return jobs().start(
            source=req.source,
            plan=req.plan,
            brand_id=req.brand_id,
            brand_url=req.brand_url,
            voice=req.voice,
            use_logo=req.use_logo,
            metadata=req.metadata,
            llm=req.llm.config() if req.llm else None,
            voice_api_key=vkey,
            design=req.design.model_dump(exclude_defaults=True) if req.design else None,
            voices=req.voices,
            voice_check=req.voice_check,
            quality=req.quality,
            callback_url=req.callback_url,
            package=req.package,
            stt_api_key=req.stt_api_key.get_secret_value() if req.stt_api_key else None,
        )
    except KeyError as e:
        raise HTTPException(404, f"brand not found: {e}") from e
    except ValueError as e:
        _bad(e)


@app.get("/v1/videos/{job_id}", dependencies=[Depends(auth)])
def get_video(job_id: str) -> dict:
    try:
        j = jobs().get(job_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(404, "job not found") from e
    j.pop("video", None)  # never expose server paths
    if j["status"] == "done":
        j["video_url"] = f"/v1/videos/{job_id}/video"
        j["frame_urls"] = [f"/v1/videos/{job_id}/frames/{i}" for i in range(j.get("frames", 0))]
        if (j.get("package") or {}).get("file"):
            j["package_url"] = f"/v1/videos/{job_id}/package"
    if j.get("package"):
        j["package"].pop("file", None)  # never expose server paths
    return j


@app.get("/v1/videos/{job_id}/package", dependencies=[Depends(auth)])
def get_package_file(job_id: str):
    try:
        return FileResponse(jobs().package_path(job_id), media_type="application/zip", filename=f"{job_id}.zip")
    except (KeyError, ValueError, FileNotFoundError) as e:
        raise HTTPException(404, "package not ready") from e


@app.get("/v1/videos/{job_id}/video", dependencies=[Depends(auth)])
def get_video_file(job_id: str):
    try:
        return FileResponse(jobs().video_path(job_id), media_type="video/mp4", filename=f"{job_id}.mp4")
    except (KeyError, ValueError, FileNotFoundError) as e:
        raise HTTPException(404, "video not ready") from e


@app.get("/v1/videos/{job_id}/frames/{n}", dependencies=[Depends(auth)])
def get_frame(job_id: str, n: int):
    try:
        jobs().get(job_id)
        return FileResponse(jobs().frame_path(job_id, n), media_type="image/png")
    except (KeyError, ValueError, FileNotFoundError) as e:
        raise HTTPException(404, "frame not found") from e


# ---------------------------------------------------------------- voices (VoiceStudio)
class VoiceDesignRequest(BaseModel):
    name: str = Field(max_length=80)
    description: str = Field(max_length=400, description="e.g. 'female, middle-aged, low pitch, british accent'")


def _voicestudio():
    from .voice import VoiceStudioProvider

    vs = VoiceStudioProvider(settings=jobs().tf.settings)
    if not vs.health():
        raise HTTPException(503, "VoiceStudio isn't reachable; set KINETRY_VOICESTUDIO_URL")
    return vs


@app.post("/v1/voices/design", dependencies=[Depends(auth)])
def design_voice(req: VoiceDesignRequest) -> dict:
    created = _voicestudio().design_voice(req.name, req.description)
    pid = created["profile"]["id"]
    return {"voice": f"voicestudio:{pid}", "matched": created["matched"], "unmatched": created["unmatched"]}


MAX_AUDIO = 20 * 1024 * 1024


@app.post("/v1/voices/clone", dependencies=[Depends(auth)])
async def clone_voice(
    name: str = Form(..., max_length=80),
    consent_text: str = Form(..., min_length=20, max_length=1000),
    ref_text: str = Form("", max_length=2000),
    ref_audio: UploadFile = File(..., description="10-30 s of clean speech from the speaker"),
    consent_audio: UploadFile = File(..., description="the speaker reading consent_text aloud"),
) -> dict:
    """Clone a real person's voice. Off unless KINETRY_VOICE_CLONING=1. The speaker's recorded
    consent is stored with the profile in VoiceStudio; without it no profile is kept."""
    if os.environ.get("KINETRY_VOICE_CLONING") != "1":
        raise HTTPException(403, "voice cloning is disabled on this server (KINETRY_VOICE_CLONING=1 enables it)")

    vs = _voicestudio()
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for field, up in (("ref", ref_audio), ("consent", consent_audio)):
            data = await up.read(MAX_AUDIO + 1)
            if len(data) > MAX_AUDIO:
                raise HTTPException(413, f"{field} audio is larger than 20 MB")
            paths[field] = Path(tmp) / f"{field}.wav"
            paths[field].write_bytes(data)
        try:
            profile = vs.clone_voice(
                name,
                paths["ref"],
                consent_audio=paths["consent"],
                consent_text=consent_text,
                reference_text=ref_text,
            )
        except ValueError as e:
            _bad(e)
    return {"voice": f"voicestudio:{profile['id']}", "profile": profile}


# ---------------------------------------------------------------- sources from documents
MAX_DOCUMENT = 50 * 1024 * 1024


class SourceUrlRequest(BaseModel):
    url: str = Field(..., max_length=2000, description="A public web page")
    section: int | None = Field(None, ge=1, description="1-based section; omit for the whole page")


def _source_reply(src: Source, md: str) -> dict:
    from .sources import split_sections

    return {
        "source": src.model_dump(),
        "sections": [{"n": i, "title": t, "words": len(b.split())} for i, (t, b) in enumerate(split_sections(md), 1)],
    }


@app.post("/v1/sources", dependencies=[Depends(auth)])
async def source_from_document(
    file: UploadFile = File(..., description=".docx, .pptx or text-based .pdf, up to 50 MB"),
    section: int | None = Form(None, ge=1),
) -> dict:
    """Read a Word, PowerPoint or PDF file into a Source ready for /v1/plans or /v1/videos. Scanned PDFs, legacy
    .doc/.ppt and course export zips aren't supported; sources over 12,000 words must be sent a section at a time."""
    from pathlib import Path

    from .loaders import DOC_EXTS, UNSUPPORTED, LoaderError
    from .sources import read_markdown, source_from_markdown

    ext = Path(file.filename or "").suffix.lower()
    if ext in UNSUPPORTED:
        raise HTTPException(415, UNSUPPORTED[ext])
    if ext not in DOC_EXTS:
        raise HTTPException(415, "send a .docx, .pptx or .pdf file")
    data = await file.read(MAX_DOCUMENT + 1)
    if len(data) > MAX_DOCUMENT:
        raise HTTPException(413, "documents are limited to 50 MB")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{ext}"
        path.write_bytes(data)
        try:
            md, title, kind = read_markdown(path)
            src = source_from_markdown(md, title or Path(file.filename or "").stem, section, {"source_kind": kind})
        except LoaderError as e:
            raise HTTPException(422, str(e)) from e
        except ValueError as e:
            _bad(e)
    return _source_reply(src, md)


@app.post("/v1/sources/url", dependencies=[Depends(auth)])
def source_from_url(req: SourceUrlRequest) -> dict:
    """Read a public web page's main content into a Source (pages built by JavaScript may come back empty)."""
    from .loaders import LoaderError
    from .netguard import check_public_url
    from .sources import read_markdown, source_from_markdown

    public_only = not jobs().allow_private
    try:
        check_public_url(
            req.url, allow_private=not public_only, what="url"
        )  # http(s) only, even when private is allowed
        md, title, kind = read_markdown(req.url, public_only=public_only)
        src = source_from_markdown(md, title or req.url, req.section, {"source_kind": kind, "source_url": req.url})
    except LoaderError as e:
        raise HTTPException(422, str(e)) from e
    except ValueError as e:  # bad section, too long, non-public address
        _bad(e)
    except Exception as e:  # noqa: BLE001  (unreachable host, HTTP error)
        raise HTTPException(400, f"couldn't read the page: {str(e)[:300]}") from e
    return _source_reply(src, md)


# ---------------------------------------------------------------- images for image scenes
@app.post("/v1/images", dependencies=[Depends(auth)])
async def upload_image(
    file: UploadFile = File(..., description="PNG, JPEG, WebP or GIF up to 15 MB, or a Lottie JSON up to 3 MB"),
) -> dict:
    """Store an image for an image scene (list the ref in the source's context.images, with an 'about' note saying
    what it shows), or a Lottie animation for an illustration scene (context.animations; needs the illustration
    effects layer). The same file always gets the same ref."""
    from .images import MAX_IMAGE_BYTES, ImageError, save_upload

    data = await file.read(MAX_IMAGE_BYTES + 1)
    try:
        ref = save_upload(data, jobs().data / "images")
    except ImageError as e:
        raise HTTPException(413 if len(data) > MAX_IMAGE_BYTES else 415, str(e)) from e
    return {"ref": ref, "bytes": len(data)}
