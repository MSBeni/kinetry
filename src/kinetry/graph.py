"""The pipeline as a LangGraph state machine.

    brand -> design -> plan -> voice -> compose -> fit_check --ok--> hf_check -> render -> music -> qa
                                           ^            |
                                           |--shrink----|
                                           |            +--rewrite--> repair --+
                                           +-----------------------------------+

`brand` and `plan` are skipped when the caller supplies them (a cached BrandPack, a reviewed plan).
`design` is the creative director: it picks the style pack, format, transition and pacing, within
the brand profile and any explicit choices in the request. The planner then builds the video from
catalog scenes, and code picks each scene's layout. The fit loop measures the real layout, shrinks
type where there is room, and only asks the LLM to rewrite copy that still doesn't fit. After
`max_fit_rounds` the job stops as 'needs_review' instead of shipping a broken video.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import hf
from .agents import Recorder, run_repair
from .branding import BrandPack, resolve_brand
from .config import Settings
from .design.build import compose_project
from .design.catalog import load_catalog
from .design.director import choose_design
from .design.icons import Icons
from .design.layout import pick_layouts
from .design.music import mix_music
from .design.plan import SIZES, Design, VideoPlan2
from .design.planner import run_planner_v2
from .design.profile import BrandProfile
from .design.render import settled_times
from .fitcheck import find_problems, get_path, measure, plan_repairs, set_path
from .fonts import FontResolver
from .stt import check_voice_clips
from .timing import build_timeline, voice_plan
from .transcript import write_timing
from .voice import KOKORO_BY_LANG, KOKORO_CANT_READ, kokoro_lang, lang_code, make_voice, parse_inworld

log = logging.getLogger("kinetry")


class Job(TypedDict, total=False):
    source_text: str
    context: dict
    brand_source: str | None  # URL, saved HTML page, probe .json, BrandPack dir, or None (default kit)
    use_logo: bool
    voice: Any  # narrator: a voice spec or a VoiceProvider
    voices: dict  # role -> voice spec (dialogue speakers 'a', 'b', ...)
    design: dict  # explicit design choices (style, format, transition, ...): these always win
    profile: dict  # brand profile overrides for this job
    music: str | None
    music_volume: float | None
    run_dir: str
    out_file: str
    qa_frames: bool
    llm: str


class State(TypedDict, total=False):
    job: Job
    pack: BrandPack
    profile: BrandProfile
    design: Design
    prefer: list
    avoid: list
    plan: VideoPlan2
    timeline: Any
    voice_check: list
    fit: dict
    fit_round: int
    problems: list
    project: str
    status: str
    video: str
    log: list


def role_voices(plan: VideoPlan2, job: dict, profile: BrandProfile) -> dict:
    """Voice spec (or provider object) per speaker role.

    Precedence for every role: the request (`voice` for the narrator, `voices`), then the plan's `voices`,
    then the brand profile, then a default. Dialogue speakers default to voices distinct from the narrator.
    """
    req = job.get("voices") or {}
    lang = lang_code(plan.design.lang)
    chosen = job.get("voice") or req.get("narrator") or plan.voices.get("narrator") or profile.voices.get("narrator")
    narrator = chosen or job.get("default_voice") or "kokoro:af_heart"
    if not chosen and lang in KOKORO_BY_LANG and kokoro_lang(narrator) not in (None, lang):
        narrator = f"kokoro:{KOKORO_BY_LANG[lang][0]}"  # the default voice speaks another language: switch
    spec = narrator if isinstance(narrator, str) else ""
    if spec.startswith("kokoro:") and kokoro_lang(spec) != "en" and kokoro_lang(spec) in KOKORO_BY_LANG:
        _, a, b = KOKORO_BY_LANG[kokoro_lang(spec)]
        defaults = {"a": f"kokoro:{a}", "b": f"kokoro:{b}"}
    elif spec.startswith("kokoro:"):
        defaults = {"a": "kokoro:am_michael", "b": "kokoro:af_nova"}
        if spec in defaults.values():
            defaults = {"a": "kokoro:am_adam", "b": "kokoro:bf_emma"}
    elif spec.startswith("openai:"):
        defaults = {"a": "openai:onyx", "b": "openai:nova"}
    elif spec.startswith("inworld:"):  # same model as the narrator, two other voices
        model = parse_inworld(spec.split(":", 1)[1])[0]
        pair = [v for v in ("Dennis", "Ashley", "Alex", "Sarah") if v != parse_inworld(spec.split(":", 1)[1])[1]]
        defaults = {"a": f"inworld:{model}:{pair[0]}", "b": f"inworld:{model}:{pair[1]}"}
    else:
        defaults = {}
    out = {"narrator": narrator}
    for role in plan.roles() - {"narrator"}:
        out[role] = req.get(role) or plan.voices.get(role) or profile.voices.get(role) or defaults.get(role, narrator)
    if lang in KOKORO_CANT_READ and any(isinstance(v, str) and v.startswith("kokoro:") for v in out.values()):
        raise ValueError(
            f"{KOKORO_CANT_READ[lang]} narration can't use the local Kokoro voice (it can't read the script); "
            "choose a cloud voice: inworld:, openai: or elevenlabs:"
        )
    return out


def build_graph(
    settings: Settings,
    *,
    llm=None,
    replay_dir: Path | None = None,
    on_event: Callable[[dict], None] | None = None,
    voice_api_key: str | None = None,
    transcriber=None,
):
    """`voice_api_key` stays in this closure: it builds cloud voices and is never written to state or disk."""
    font_resolver = FontResolver(settings.cache_dir / "fonts")
    catalog = load_catalog()
    icons = Icons(settings.tool_dir)

    def rec_for(state: State) -> Recorder:
        return Recorder(Path(state["job"]["run_dir"]), settings, replay_dir)

    def emit(state: State, step: str, **kw) -> list:
        entry = {"step": step, "t": round(time.time(), 1), **kw}
        log.info("%s: %s", step, ", ".join(f"{k}={v}" for k, v in kw.items() if k != "detail"))
        if on_event:
            on_event(entry)
        return (state.get("log") or []) + [entry]

    # ---------------------------------------------------------------- nodes
    def brand(state: State) -> State:
        job = state["job"]
        pack = state.get("pack") or resolve_brand(
            job.get("brand_source"),
            settings,
            Path(job["run_dir"]),
            llm=llm,
            replay_dir=replay_dir,
            use_logo=job.get("use_logo", True),
            fonts=font_resolver,
        )
        base = pack.profile.model_dump() if getattr(pack, "profile", None) else {}
        profile = BrandProfile.model_validate({**base, **(job.get("profile") or {})})
        kit = pack.kit
        return {
            "pack": pack,
            "profile": profile,
            "fit": {},
            "fit_round": 0,
            "log": emit(
                state,
                "brand",
                name=kit.name,
                accent=kit.accent,
                fill=kit.accent_fill,
                fonts=f"{kit.display_font}/{kit.body_font}",
                logo=bool(pack.logo),
                detail=pack.notes,
            ),
        }

    def design(state: State) -> State:
        job = state["job"]
        given = state.get("plan")
        base = given.design.model_dump(exclude_defaults=True) if given is not None else {}
        overrides = Design.model_validate({**base, **(job.get("design") or {})})
        text = job.get("source_text") or (" ".join(b.say for s in given.scenes for b in s.beats) if given else "")
        d, prefer, avoid = choose_design(
            text,
            job.get("context", {}),
            kit=state["pack"].kit,
            profile=state["profile"],
            overrides=overrides,
            llm=llm,
            settings=settings,
            rec=rec_for(state),
            catalog=catalog,
            use_model=given is None,  # a reviewed plan doesn't need a model to pick a look
        )
        return {
            "design": d,
            "prefer": prefer,
            "avoid": avoid,
            "log": emit(
                state,
                "design",
                style=d.style,
                format=d.resolved_format(),
                transition=d.transition or "style",
                pacing=d.pacing or "normal",
                captions=d.resolved_captions(),
                detail=d.rationale,
            ),
        }

    def plan(state: State) -> State:
        job = state["job"]
        if state.get("plan") is not None:
            p = state["plan"]
            p.design = state["design"]
            pick_layouts(p, catalog)
            src = "provided"
        else:
            p = run_planner_v2(
                job["source_text"],
                job.get("context", {}),
                state["design"],
                settings,
                rec_for(state),
                llm=llm,
                prefer=state.get("prefer"),
                avoid=state.get("avoid"),
                catalog=catalog,
            )
            if replay_dir:  # recorded plans carry their own look; explicit choices still win
                merged = {**p.design.model_dump(exclude_defaults=True), **(job.get("design") or {})}
                p.design = Design.model_validate(merged) if merged else state["design"]
                pick_layouts(p, catalog)
            src = "planner"
        errs = catalog.validate_plan(p)
        if errs:
            raise ValueError("plan doesn't match the catalog:\n" + "\n".join(errs[:20]))
        return {
            "plan": p,
            "design": p.design,
            "log": emit(
                state,
                "plan",
                source=src,
                scenes=len(p.scenes),
                words=p.word_count(),
                types=[f"{s.type}/{s.layout}" for s in p.scenes],
            ),
        }

    def voice(state: State) -> State:
        run_dir = Path(state["job"]["run_dir"])
        p = state["plan"]
        specs = role_voices(p, state["job"], state["profile"])
        voices = {
            r: make_voice(v, settings, settings.cache_dir / "voice", api_key=voice_api_key) for r, v in specs.items()
        }
        clips = voice_plan(p, voices, run_dir / "audio")
        tl = build_timeline(p, clips, p.design.pacing or "normal")
        lang = lang_code(p.design.lang)
        warn = []
        for role, sp in specs.items():
            kl = kokoro_lang(sp) if isinstance(sp, str) else None
            if kl and kl != lang:
                warn.append(
                    f"{role}: {sp} speaks {kl}, the script is {lang}"
                    + ("" if lang in KOKORO_BY_LANG else "; Kokoro has no voice for it, use a cloud voice")
                )
        log_ = emit(
            state,
            "voice",
            provider=voices["narrator"].name,
            roles=sorted(voices),
            voices={r: v for r, v in specs.items() if isinstance(v, str)},
            seconds=tl.duration,
            beats=sum(len(r) for r in clips),
            **({"warnings": warn} if warn else {}),
        )
        out = {"timeline": tl, "log": log_}
        if transcriber is not None:  # listen back: does the audio say what the script says?
            if hasattr(transcriber, "language"):  # transcribe in the script's language, not the default English
                transcriber.language = lang_code(p.design.lang)
            rows = check_voice_clips(tl, transcriber)
            flagged = [r["beat"] for r in rows if not r["ok"]]
            out["voice_check"] = rows
            out["log"] = emit(
                {**state, "log": log_},
                "voice_check",
                beats=len(rows),
                flagged=flagged,
                lowest=min((r["score"] for r in rows), default=None),
                detail=[r for r in rows if not r["ok"]],
            )
        return out

    def compose(state: State) -> State:
        project = Path(state["job"]["run_dir"]) / "project"
        compose_project(
            state["plan"],
            state["pack"],
            state["timeline"],
            project,
            settings,
            fit=state.get("fit", {}),
            catalog=catalog,
            icons=icons,
            fonts=font_resolver,
        )
        return {"project": str(project)}

    def fit_check(state: State) -> State:
        project = Path(state["project"])
        size = SIZES[state["plan"].design.resolved_format()]
        report = measure(
            project / "index.html", settings, project.parent / f"fit-{state.get('fit_round', 0)}.json", size
        )
        probs = find_problems(report)
        return {
            "problems": probs,
            "log": emit(
                state,
                "fit_check",
                round=state.get("fit_round", 0),
                problems=len(probs),
                detail=[p.__dict__ for p in probs],
            ),
        }

    def route_fit(state: State) -> str:
        if not state["problems"]:
            return "ok"
        if state.get("fit_round", 0) >= settings.max_fit_rounds:
            return "give_up"
        _, rewrite = plan_repairs(state["problems"], state.get("fit", {}))
        return "rewrite" if rewrite else "shrink"

    def shrink(state: State) -> State:
        new_fit, _ = plan_repairs(state["problems"], state.get("fit", {}))
        return {
            "fit": new_fit,
            "fit_round": state.get("fit_round", 0) + 1,
            "log": emit(state, "shrink", fields=[p.field for p in state["problems"]]),
        }

    def repair(state: State) -> State:
        new_fit, rewrite = plan_repairs(state["problems"], state.get("fit", {}))
        try:
            rw = run_repair(rewrite, settings, rec_for(state), state.get("fit_round", 0), llm=llm)
        except Exception as e:  # noqa: BLE001  (no model reachable): stop as needs_review, not as a crash
            return {
                "fit_round": settings.max_fit_rounds,
                "log": emit(
                    state, "repair", rewritten=[], detail=f"copy rewrite unavailable: {type(e).__name__}: {e}"[:300]
                ),
            }
        p = state["plan"]
        asked = {pr.field for pr in rewrite}
        changes = []
        for item in rw.items:
            if item.field not in asked:  # only the fields we asked about; nothing else in the plan
                continue
            try:
                old = get_path(p, item.field)
            except (KeyError, IndexError, AttributeError, TypeError):
                continue
            if not isinstance(old, str):
                continue
            set_path(p, item.field, item.text)
            new_fit[item.field] = 0  # new copy starts at full size again
            changes.append({"field": item.field, "from": old, "to": item.text})
        return {
            "plan": p,
            "fit": new_fit,
            "fit_round": state.get("fit_round", 0) + 1,
            "log": emit(state, "repair", rewritten=[c["field"] for c in changes], detail=changes),
        }

    def give_up(state: State) -> State:
        return {
            "status": "needs_review",
            "log": emit(state, "give_up", unresolved=[p.field for p in state["problems"]]),
        }

    def hf_check(state: State) -> State:
        res = hf.check(Path(state["project"]), settings)
        status = "checked" if res["ok"] else "check_failed"
        return {
            "status": status,
            "log": emit(state, "hf_check", ok=res["ok"], errors=len(res["errors"]), detail=res["errors"][:10]),
        }

    def render(state: State) -> State:
        q = state["job"].get("quality") or settings.quality
        out = hf.render(Path(state["project"]), Path(state["job"]["out_file"]), settings, quality=q)
        mb = round(out.stat().st_size / 1e6, 2)
        # what was said, when: captions, transcripts, chapters and LMS packages are built from this
        write_timing(
            Path(state["job"]["run_dir"]), state["plan"], state["timeline"], state["job"].get("source_text", "")
        )
        return {"video": str(out), "status": "rendered", "log": emit(state, "render", file=out.name, quality=q, mb=mb)}

    def music(state: State) -> State:
        job, prof = state["job"], state["profile"]
        track = job.get("music") or prof.music
        if not track:
            return {}
        vol = job.get("music_volume") if job.get("music_volume") is not None else prof.music_volume
        mix_music(Path(state["video"]), Path(track), volume=vol)
        return {"log": emit(state, "music", track=Path(track).name, volume=vol)}

    def qa(state: State) -> State:
        tl = state["timeline"]
        frames = []
        if state["job"].get("qa_frames", True):
            times = settled_times(state["plan"], tl)
            frames = hf.snapshot(Path(state["project"]), times, Path(state["job"]["run_dir"]) / "qa", settings)
        return {"status": "done", "log": emit(state, "qa", frames=len(frames))}

    g = StateGraph(State)
    for name, fn in [
        ("brand", brand),
        ("design", design),
        ("plan", plan),
        ("voice", voice),
        ("compose", compose),
        ("fit_check", fit_check),
        ("shrink", shrink),
        ("repair", repair),
        ("give_up", give_up),
        ("hf_check", hf_check),
        ("render", render),
        ("music", music),
        ("qa", qa),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "brand")
    g.add_edge("brand", "design")
    g.add_edge("design", "plan")
    g.add_edge("plan", "voice")
    g.add_edge("voice", "compose")
    g.add_edge("compose", "fit_check")
    g.add_conditional_edges(
        "fit_check", route_fit, {"ok": "hf_check", "shrink": "shrink", "rewrite": "repair", "give_up": "give_up"}
    )
    g.add_edge("shrink", "compose")
    g.add_edge("repair", "compose")
    g.add_edge("give_up", END)
    g.add_conditional_edges(
        "hf_check", lambda s: "render" if s["status"] == "checked" else END, {"render": "render", END: END}
    )
    g.add_edge("render", "music")
    g.add_edge("music", "qa")
    g.add_edge("qa", END)
    return g.compile()


def write_report(state: State, extra: dict | None = None) -> dict:
    tl = state.get("timeline")
    pack = state.get("pack")
    plan = state.get("plan")
    report = {
        "status": state.get("status"),
        "video": state.get("video"),
        "duration": tl.duration if tl else None,
        "llm": state["job"].get("llm"),
        "design": plan.design.model_dump() if plan is not None else None,
        "brand": pack.kit.model_dump() if pack else None,
        "plan": plan.model_dump() if plan is not None else None,
        "voice_check": state.get("voice_check"),
        "log": state.get("log"),
        **(extra or {}),
    }
    Path(state["job"]["run_dir"], "report.json").write_text(json.dumps(report, indent=2, default=str))
    return report
