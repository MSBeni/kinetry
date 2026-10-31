"""Public Python API.

from kinetry import Kinetry, Source

tf = Kinetry()                                          # KINETRY_LLM, Bedrock by default
tf = Kinetry(llm="anthropic:claude-sonnet-5-5")         # any provider:model, key from env
tf = Kinetry(llm=LLMConfig("openai", "gpt-4.1", api_key=user_key))   # bring your own key
tf = Kinetry(llm=ChatOpenAI(model="gpt-4.1"))           # or any LangChain chat model

# one call: the creative director picks the look, the planner builds it from catalog scenes
result = tf.generate(Source(text=lesson_md, title="Week 1"), brand="https://acme.com", out="w1.mp4")

# or step by step, with control over the look
pack = tf.brand("https://acme.com"); pack.save("brands/acme")
plan = tf.plan(Source(text=lesson_md), brand=pack, design={"style": "warm", "format": "9:16"})
frames = tf.preview(plan, brand=pack, out_dir="storyboard")     # seconds, no audio: check the look
result = tf.render(plan, brand=pack, out="w1.mp4", music="brand-bed.mp3")
"""

from __future__ import annotations

import json
import re
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import hf
from .agents import Recorder
from .branding import BrandPack, resolve_brand
from .config import Settings
from .design.build import compose_project
from .design.catalog import Catalog, load_catalog
from .design.director import choose_design
from .design.layout import pick_layouts
from .design.plan import Design, VideoPlan2, load_plan
from .design.planner import run_planner_v2
from .design.profile import BrandProfile
from .design.render import settled_times
from .graph import State, build_graph, write_report
from .llm import LLMLike, Models, describe
from .localize import Localized
from .sources import Source
from .stt import make_transcriber
from .timing import build_timeline, silent_clips

BrandArg = str | Path | BrandPack | None
DesignArg = Design | dict | None


@dataclass
class Result:
    status: str  # done | needs_review | check_failed | error
    video: Path | None
    run_dir: Path
    duration: float | None = None
    plan: VideoPlan2 | None = None
    brand: BrandPack | None = None
    log: list = field(default_factory=list)
    error: str | None = None
    voice_check: list | None = None  # per-beat listen-back scores when voice_check was on

    @property
    def ok(self) -> bool:
        return self.status == "done"

    @property
    def qa_frames(self) -> list[Path]:
        return sorted((self.run_dir / "qa").glob("frame-*.png"))


def _design(d: DesignArg) -> dict:
    if d is None:
        return {}
    return d.model_dump(exclude_defaults=True) if isinstance(d, Design) else dict(d)


class Kinetry:
    def __init__(
        self,
        *,
        llm: LLMLike = None,
        llm_fast: LLMLike = None,
        settings: Settings | None = None,
        voice="kokoro:af_heart",
        workdir: str | Path | None = None,
        replay_dir: str | Path | None = None,
    ):
        """
        llm:        the model for planning, branding and design: a "provider:model" spec, an LLMConfig (your
                    own API key, endpoint or AWS credentials) or any LangChain chat model.
                    Default: KINETRY_LLM (Bedrock, Claude Sonnet 4.5).
        llm_fast:   optional cheaper model for copy rewrites in the fit loop (default: same as llm).
        voice:      narrator voice: a spec ("kokoro:af_heart", "openai:coral", "voicestudio:<id>") or a
                    VoiceProvider object (bring your own TTS); overridable per call.
        workdir:    where run directories go (default: a temp dir per run).
        replay_dir: recorded LLM outputs to reuse instead of calling a model (tests, CI, regression).
        """
        self.settings = settings or Settings()
        self.llm = Models(llm, llm_fast) if llm_fast is not None else llm
        self.voice = voice
        self.workdir = Path(workdir) if workdir else None
        self.replay_dir = Path(replay_dir) if replay_dir else None
        if self.replay_dir:
            self.settings.llm_provider = "replay"

    # ------------------------------------------------------------ helpers
    def _llm(self, override: LLMLike) -> LLMLike:
        return self.llm if override is None else override

    def _run_dir(self, run_dir: str | Path | None) -> Path:
        if run_dir:
            p = Path(run_dir)
        elif self.workdir:
            p = self.workdir / uuid.uuid4().hex[:12]
        else:
            p = Path(tempfile.mkdtemp(prefix="kinetry-"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _pack(self, brand: BrandArg, rd: Path, use_logo: bool = True) -> BrandPack:
        if isinstance(brand, BrandPack):
            return brand
        return self.brand(brand, use_logo=use_logo, run_dir=rd)

    @staticmethod
    def catalog() -> Catalog:
        """Everything the engine can render: scene types, layouts, styles, motion, transitions."""
        return load_catalog()

    # ------------------------------------------------------------ steps
    def brand(
        self,
        source: str | Path | None,
        *,
        use_logo: bool = True,
        run_dir: str | Path | None = None,
        llm: LLMLike = None,
    ) -> BrandPack:
        """Website URL / saved page / probe JSON / BrandPack dir -> BrandPack."""
        return resolve_brand(
            str(source) if source else None,
            self.settings,
            self._run_dir(run_dir),
            llm=self._llm(llm),
            replay_dir=self.replay_dir,
            use_logo=use_logo,
        )

    def design(
        self,
        source: Source,
        *,
        brand: BrandArg = None,
        design: DesignArg = None,
        profile: BrandProfile | dict | None = None,
        run_dir: str | Path | None = None,
        llm: LLMLike = None,
    ) -> Design:
        """Ask the creative director for a look (style, format, transition, pacing, captions)."""
        rd = self._run_dir(run_dir)
        pack = self._pack(brand, rd)
        prof = BrandProfile.model_validate({**pack.profile.model_dump(), **(_profile(profile))})
        d, _, _ = choose_design(
            source.text,
            {"title": source.title, **source.context},
            kit=pack.kit,
            profile=prof,
            overrides=Design.model_validate(_design(design)),
            llm=self._llm(llm),
            settings=self.settings,
            rec=Recorder(rd, self.settings, self.replay_dir),
        )
        return d

    def plan(
        self,
        source: Source,
        *,
        brand: BrandArg = None,
        design: DesignArg = None,
        profile: BrandProfile | dict | None = None,
        run_dir: str | Path | None = None,
        llm: LLMLike = None,
    ) -> VideoPlan2:
        """Source -> VideoPlan2 with its design and layouts filled in. Review or edit it before rendering."""
        rd = self._run_dir(run_dir)
        pack = self._pack(brand, rd)
        prof = BrandProfile.model_validate({**pack.profile.model_dump(), **(_profile(profile))})
        rec = Recorder(rd, self.settings, self.replay_dir)
        ctx = {"title": source.title, **source.context}
        d, prefer, avoid = choose_design(
            source.text,
            ctx,
            kit=pack.kit,
            profile=prof,
            overrides=Design.model_validate(_design(design)),
            llm=self._llm(llm),
            settings=self.settings,
            rec=rec,
        )
        plan = run_planner_v2(source.text, ctx, d, self.settings, rec, llm=self._llm(llm), prefer=prefer, avoid=avoid)
        if design:
            plan.design = Design.model_validate({**plan.design.model_dump(exclude_defaults=True), **_design(design)})
        return pick_layouts(plan)

    def preview(
        self,
        plan: VideoPlan2 | dict,
        *,
        brand: BrandArg = None,
        out_dir: str | Path,
        design: DesignArg = None,
    ) -> list[Path]:
        """A storyboard in seconds: compose with estimated timing (no voice), one frame per scene."""
        out = Path(out_dir)
        p = load_plan(plan if isinstance(plan, dict) else plan.model_copy(deep=True))
        if design:
            p.design = Design.model_validate({**p.design.model_dump(exclude_defaults=True), **_design(design)})
        pick_layouts(p)
        errs = load_catalog().validate_plan(p)
        if errs:
            raise ValueError("plan doesn't match the catalog: " + "; ".join(errs[:8]))
        pack = self._pack(brand, out / "brand")
        tl = build_timeline(p, silent_clips(p), p.design.pacing or "normal")
        compose_project(p, pack, tl, out / "project", self.settings)
        return hf.snapshot(out / "project", settled_times(p, tl), out / "frames", self.settings)

    def gallery(
        self, out_dir: str | Path, *, brand: BrandArg = None, styles=None, formats=None, components=None
    ) -> dict:
        """Render every scene type and layout in every style and format (see design/gallery.py)."""
        from .design.gallery import build_gallery

        out = Path(out_dir)
        pack = self._pack(brand, out / "brand") if brand else None
        return build_gallery(out, self.settings, pack=pack, styles=styles, formats=formats, components=components)

    def render(
        self,
        plan: VideoPlan2 | dict,
        *,
        brand: BrandArg = None,
        out: str | Path,
        voice=None,
        voices: dict | None = None,
        design: DesignArg = None,
        music: str | Path | None = None,
        music_volume: float | None = None,
        run_dir: str | Path | None = None,
        use_logo: bool = True,
        qa_frames: bool = True,
        on_event: Callable[[dict], None] | None = None,
        llm: LLMLike = None,
        voice_api_key: str | None = None,
        voice_check=None,
        stt_api_key: str | None = None,
        quality: str | int | None = None,
    ) -> Result:
        """Render a reviewed plan (v2, or a v1 plan from an older version). Copy rewrites from the fit loop
        are applied to a copy of the plan."""
        p = load_plan(plan) if isinstance(plan, dict) else load_plan(plan.model_copy(deep=True))
        return self._run(
            source=None,
            plan=p,
            brand=brand,
            out=out,
            voice=voice,
            voices=voices,
            design=design,
            profile=None,
            music=music,
            music_volume=music_volume,
            run_dir=run_dir,
            use_logo=use_logo,
            qa_frames=qa_frames,
            on_event=on_event,
            llm=llm,
            voice_api_key=voice_api_key,
            voice_check=voice_check,
            stt_api_key=stt_api_key,
            quality=quality,
        )

    def generate(
        self,
        source: Source,
        *,
        brand: BrandArg = None,
        out: str | Path,
        voice=None,
        voices: dict | None = None,
        design: DesignArg = None,
        profile: BrandProfile | dict | None = None,
        music: str | Path | None = None,
        music_volume: float | None = None,
        run_dir: str | Path | None = None,
        use_logo: bool = True,
        qa_frames: bool = True,
        on_event: Callable[[dict], None] | None = None,
        llm: LLMLike = None,
        voice_api_key: str | None = None,
        voice_check=None,
        stt_api_key: str | None = None,
        quality: str | int | None = None,
    ) -> Result:
        """Source -> finished video in one call. `voice_api_key`: key for cloud voices (openai:, elevenlabs:, inworld:),
        used for the narrator and every dialogue role; held in memory only. `voice_check`: True (Inworld
        inworld-stt-1) or a transcriber spec/object: listen back to every beat and flag ones that don't match the
        script (report.json "voice_check"). `quality`: draft | standard (default) | high, or a CRF number."""
        return self._run(
            source=source,
            plan=None,
            brand=brand,
            out=out,
            voice=voice,
            voices=voices,
            design=design,
            profile=profile,
            music=music,
            music_volume=music_volume,
            run_dir=run_dir,
            use_logo=use_logo,
            qa_frames=qa_frames,
            on_event=on_event,
            llm=llm,
            voice_api_key=voice_api_key,
            voice_check=voice_check,
            stt_api_key=stt_api_key,
            quality=quality,
        )

    def package(
        self,
        run: Result | str | Path,
        *,
        out: str | Path,
        standard: str = "scorm12",
        quiz=True,
        questions: int = 3,
        mastery: int = 80,
        title: str | None = None,
        video: str | Path | None = None,
        llm: LLMLike = None,
    ):
        """A finished video as a lesson an LMS can import: SCORM 1.2 (default), SCORM 2004, or `web` (a plain
        zip). Captions, chapters, a transcript and, unless quiz=False, a knowledge check grounded in the source.
        Returns a package.Package (path, questions kept, notes)."""
        from .package import build_package

        rd = run.run_dir if isinstance(run, Result) else Path(run)
        vid = video or (run.video if isinstance(run, Result) else None)
        return build_package(
            rd,
            out,
            standard=standard,
            quiz=quiz,
            questions=questions,
            mastery=mastery,
            title=title,
            video=vid,
            settings=self.settings,
            llm=self._llm(llm),
            replay_dir=self.replay_dir,
        )

    def localize(
        self,
        plan: VideoPlan2 | dict | str | Path,
        *,
        to: str | list[str],
        out_dir: str | Path,
        brand: BrandArg = None,
        voices: dict[str, dict[str, str] | str] | None = None,
        render: bool = True,
        package: str | None = None,
        quiz: int = 3,
        mastery: int = 80,
        name: str | None = None,
        quality: str | int | None = None,
        qa_frames: bool = False,
        llm: LLMLike = None,
        voice_api_key: str | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> list[Localized]:
        """One reviewed plan -> the same video in other languages, as one batch.

        `plan`: a plan (or its file), or a finished run directory. `to`: "es,fr,ar" or a list. `voices`:
        per language, a narrator spec or {role: spec}, e.g. {"ar": "inworld:inworld-tts-1:<arabic-voice>",
        "es": {"narrator": "kokoro:ef_dora", "a": "kokoro:em_alex"}}; languages Kokoro speaks need none.
        Every language is checked for a usable voice before anything runs. `render=False` only translates
        (plans to review first). `package`: scorm12 | scorm2004 | web, to also write an LMS package per
        language. Writes <name>.<lang>.plan.json, .mp4 (and .zip) plus localize.json in `out_dir`."""
        from .localize import language_name, parse_langs, plan_voices, source_plan, translate
        from .voice import lang_code

        p = source_plan(plan) if isinstance(plan, (str, Path)) else load_plan(plan)
        langs = parse_langs(to)
        if package and package not in ("scorm12", "scorm2004", "web"):
            raise ValueError("package must be scorm12, scorm2004 or web")
        given = {k.lower(): ({"narrator": v} if isinstance(v, str) else dict(v)) for k, v in (voices or {}).items()}
        od = Path(out_dir)
        od.mkdir(parents=True, exist_ok=True)
        stem = name or re.sub(r"[^a-z0-9]+", "-", p.title.lower()).strip("-")[:48] or "lesson"
        pack = self._pack(brand, od / "brand")
        brand_voices = dict(pack.profile.voices) if getattr(pack, "profile", None) else {}
        src_lang = lang_code(p.design.lang)
        default = self.voice if isinstance(self.voice, str) else None

        if render:  # every language needs a voice before anything is spent
            from .localize import apply

            problems = []
            for lang in langs:
                shell, _ = apply(p, lang, {})
                _, why = plan_voices(
                    lang, shell, given.get(lang.lower()) or given.get(lang_code(lang)), brand_voices, default
                )
                if why:
                    problems.append(why)
            if problems:
                raise ValueError("; ".join(problems))

        emit = on_event or (lambda e: None)
        rec = Recorder(od, self.settings, self.replay_dir)
        out: list[Localized] = []
        for lang in langs:
            item = Localized(lang)
            out.append(item)
            try:
                if lang.lower() in (src_lang, (p.design.lang or "en").lower()):
                    lp, notes = p.model_copy(deep=True), ["same language as the plan: not translated"]
                else:
                    emit({"step": "translate", "lang": lang, "language": language_name(lang)})
                    lp, notes = translate(p, lang, settings=self.settings, llm=self._llm(llm), rec=rec)
                item.plan, item.notes = lp, notes
                item.plan_file = od / f"{stem}.{lang}.plan.json"
                item.plan_file.write_text(lp.model_dump_json(indent=1, exclude_defaults=False), encoding="utf-8")
                item.status = "translated"
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                item.status, item.error = "error", str(e)
                continue
            if not render:
                continue
            lv, _ = plan_voices(lang, lp, given.get(lang.lower()) or given.get(lang_code(lang)), brand_voices, default)
            emit({"step": "render", "lang": lang, "voices": lv})
            sub = self.replay_dir / lang if self.replay_dir and (self.replay_dir / lang).is_dir() else self.replay_dir
            prev, self.replay_dir = self.replay_dir, sub
            try:  # a language's own recordings (a subfolder named after it) win, for replay
                res = self.render(
                    lp,
                    brand=pack,
                    out=od / f"{stem}.{lang}.mp4",
                    voice=lv.get("narrator"),
                    voices={r: v for r, v in lv.items() if r != "narrator"},
                    run_dir=od / "runs" / lang,
                    qa_frames=qa_frames,
                    llm=llm,
                    voice_api_key=voice_api_key,
                    quality=quality,
                    on_event=(lambda e, lang=lang: emit({**e, "lang": lang})) if on_event else None,
                )
                item.run_dir, item.duration = res.run_dir, res.duration
                if not res.ok:
                    item.status, item.error = "error", f"render {res.status}: {res.error or 'see report.json'}"
                    continue
                item.video, item.status = res.video, "done"
                if package:
                    try:
                        pkg = self.package(
                            res,
                            out=od / f"{stem}.{lang}.zip",
                            standard=package,
                            quiz=quiz > 0,
                            questions=max(1, quiz),
                            mastery=mastery,
                            llm=llm,
                        )
                        item.package = pkg.path
                        item.notes += pkg.notes
                    except (ValueError, FileNotFoundError, RuntimeError) as e:
                        item.notes.append(f"no package: {e}")
            finally:
                self.replay_dir = prev
        summary = {"title": p.title, "from": p.design.lang or "en", "languages": [i.to_dict() for i in out]}
        (od / "localize.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    # ------------------------------------------------------------ internals
    def _run(
        self,
        *,
        source,
        plan,
        brand,
        out,
        voice,
        voices,
        design,
        profile,
        music,
        music_volume,
        run_dir,
        use_logo,
        qa_frames,
        on_event,
        llm,
        voice_api_key=None,
        voice_check=None,
        stt_api_key=None,
        quality=None,
    ) -> Result:
        if quality is not None:
            hf.quality_args(quality)  # fail fast on a bad value
        rd = self._run_dir(run_dir)
        llm = self._llm(llm)
        job = {
            "source_text": source.text if source else "",
            "context": ({"title": source.title, **source.context} if source else {}),
            "brand_source": None if isinstance(brand, BrandPack) or brand is None else str(brand),
            "use_logo": use_logo,
            "voice": voice,  # explicit request; None lets plan/profile voices apply before the default
            "default_voice": self.voice,
            "voices": voices or {},
            "design": _design(design),
            "profile": _profile(profile),
            "music": str(music) if music else None,
            "music_volume": music_volume,
            "run_dir": str(rd),
            "out_file": str(Path(out).resolve()),
            "qa_frames": qa_frames,
            "quality": quality,
            "llm": "replay" if self.settings.llm_provider == "replay" else describe(llm or self.settings.llm_spec()),
        }
        init: State = {"job": job, "log": []}
        if isinstance(brand, BrandPack):
            init["pack"] = brand
        if plan is not None:
            init["plan"] = plan
        transcriber = None
        if voice_check:  # True = Inworld inworld-stt-1; or a spec / transcriber object
            transcriber = make_transcriber(None if voice_check is True else voice_check, api_key=stt_api_key)
        graph = build_graph(
            self.settings,
            llm=llm,
            replay_dir=self.replay_dir,
            on_event=on_event,
            voice_api_key=voice_api_key,
            transcriber=transcriber,
        )
        try:
            state = graph.invoke(init, {"recursion_limit": 80})
        except Exception as e:  # noqa: BLE001
            write_report({**init, "status": "error"}, {"error": f"{type(e).__name__}: {e}"})
            return Result("error", None, rd, error=f"{type(e).__name__}: {e}", plan=plan)
        report = write_report(state)
        video = Path(state["video"]) if state.get("video") else None
        return Result(
            state.get("status", "error"),
            video,
            rd,
            report.get("duration"),
            state.get("plan"),
            state.get("pack"),
            state.get("log", []),
            voice_check=state.get("voice_check"),
        )


def _profile(p: BrandProfile | dict | None) -> dict:
    if p is None:
        return {}
    return p.model_dump(exclude_defaults=True) if isinstance(p, BrandProfile) else dict(p)
