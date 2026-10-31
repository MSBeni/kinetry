"""Live checks against real provider accounts: `kinetry check-inworld`, `check-llm`, `check-voices`.

Runs on your machine with your key in the environment (never pass keys on the command line). Each step
reports pass/fail and keeps going, so one run shows everything that works and everything that doesn't:

1. auth       list the voices your key can use
2. cast       every Inworld voice in a cast file exists on your account (optional)
3. tts:<m>    synthesize a sentence with each model (inworld-tts-2, -2-flash, -1)
4. stt:<m>    transcribe that audio with inworld-stt-1 and compare with the sentence (round trip)
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from .stt import InworldSTT, similarity
from .voice import INWORLD_MODELS, InworldProvider

SENTENCE = "Please confirm the meeting for Thursday at three, and bring the signed agreement."


def _row(step: str, ok: bool, detail: str, seconds: float) -> dict:
    return {"step": step, "ok": ok, "detail": detail, "seconds": round(seconds, 1)}


def check_inworld(
    out_dir: Path,
    *,
    api_key: str | None = None,
    voice: str = "Ashley",
    cast_file: str | Path | None = None,
    models: tuple[str, ...] = INWORLD_MODELS,
    client: httpx.Client | None = None,
    on_row=None,
) -> list[dict]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    def add(r: dict) -> None:
        rows.append(r)
        if on_row:
            on_row(r)

    def run(step: str, fn):
        t = time.monotonic()
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001  report and continue
            ok, detail = False, f"{type(e).__name__}: {str(e)[:240]}"
        add(_row(step, ok, detail, time.monotonic() - t))
        return ok

    voices: list[dict] = []

    def auth():
        voices.extend(InworldProvider(voice, api_key=api_key, client=client).list_voices(None))
        english = [v for v in voices if "en" in (v.get("languages") or [])]
        return bool(voices), f"{len(voices)} voices ({len(english)} English)"

    if not run("auth", auth):
        return rows  # nothing else can work without auth

    if cast_file:

        def cast():
            from .cast import load_cast

            found = load_cast(cast_file).verify_inworld(voices)
            missing = [c for c, ok in found.items() if not ok]
            return not missing, f"{len(found) - len(missing)}/{len(found)} found" + (
                f"; missing: {', '.join(missing)}" if missing else ""
            )

        run("cast", cast)

    stt = None
    for model in models:
        wav = out_dir / f"{model}.wav"

        def tts(model=model, wav=wav):
            clip = InworldProvider(voice, model=model, api_key=api_key, client=client).synthesize(SENTENCE, wav)
            return clip.duration > 1.0, f"{clip.duration:.1f}s of audio -> {wav.name}"

        if not run(f"tts:{model}", tts):
            continue

        def round_trip(wav=wav):
            nonlocal stt
            stt = stt or InworldSTT(api_key=api_key, client=client)
            heard = stt.transcribe(wav)
            score = similarity(SENTENCE, heard.text)
            return score >= 0.8, f"score {score:.2f}, {len(heard.words)} word timings, heard: {heard.text[:120]!r}"

        run(f"stt:{model}", round_trip)
    return rows


# ------------------------------------------------------------------ models
SAMPLE_SOURCE = """# Giving feedback that lands

New team leads often save feedback for the quarterly review. By then the moment is gone and the
person can't connect the comment to what they did.

Give feedback within a day or two. Describe the specific behavior you saw, not the person's character:
"In Tuesday's demo you skipped the pricing slide" instead of "you're careless". Say what it caused,
for example that the client asked about pricing twice. Then ask a question and listen before you suggest
anything: "What happened there?" often reveals a reason you didn't know.

Positive feedback follows the same pattern. "Nice job" is forgettable; "your summary email meant nobody
had to ask what was decided" tells the person what to repeat.

Try it this week: pick one recent moment, write two sentences about the behavior and its effect, and
have the conversation within 48 hours."""


def check_llm(
    llm,
    out_dir: Path,
    *,
    source_text: str = SAMPLE_SOURCE,
    render: bool = False,
    voice: str | None = None,
    settings=None,
    on_row=None,
) -> list[dict]:
    """A real model through the parts of the pipeline that need one: the creative director, the script writer
    (planner, validated against the catalog) and, with `render`, the copy-rewrite loop and a finished video.
    Unlike a normal run, the director is called directly so a broken model fails here instead of quietly
    falling back to keyword rules."""
    import json

    from .agents import get_llm
    from .api import Kinetry
    from .config import Settings
    from .design.catalog import load_catalog
    from .design.director import DIRECTOR_SYSTEM, DesignChoice
    from .llm import describe, invoke_structured
    from .sources import Source

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = settings or Settings()
    rows: list[dict] = []

    def add(r):
        rows.append(r)
        if on_row:
            on_row(r)

    def run(step, fn):
        t = time.monotonic()
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {str(e)[:300]}"
        add(_row(step, ok, detail, time.monotonic() - t))
        return ok

    cat = load_catalog()

    def director():
        model = get_llm(settings, llm, 0.4)
        sys_ = DIRECTOR_SYSTEM.format(styles=cat.styles_guide(), transitions=", ".join(cat.transitions))
        user = json.dumps({"content": source_text[:6000], "context": {"audience": "new team leads"}})
        ch = invoke_structured(
            model, DesignChoice, [{"role": "system", "content": sys_}, {"role": "user", "content": user}]
        )
        known = ch.style in cat.styles
        return known, f"{describe(llm) if llm else 'default model'}: style {ch.style}, {ch.format}, {ch.pacing}" + (
            "" if known else " (unknown style!)"
        )

    if not run("director", director):
        return rows  # same model for the planner: no point going on

    plan_holder: dict = {}
    src = Source(text=source_text, title="Giving feedback that lands", context={"audience": "new team leads"})

    def planner():
        tf = Kinetry(llm=llm, settings=settings, workdir=out_dir / "runs")
        plan = tf.plan(src, run_dir=out_dir / "plan-run")
        errs = cat.validate_plan(plan)
        plan_holder["plan"] = plan
        (out_dir / "plan.json").write_text(plan.model_dump_json(indent=2))
        types = [s.type for s in plan.scenes]
        return not errs, f"{len(types)} scenes ({', '.join(types)}), {plan.word_count()} words" + (
            f"; catalog errors: {'; '.join(errs[:3])}" if errs else ""
        )

    if not run("planner", planner) or not render:
        return rows

    def video():
        tf = Kinetry(llm=llm, settings=settings, workdir=out_dir / "runs", voice=voice or "kokoro:af_heart")
        res = tf.render(plan_holder["plan"], out=out_dir / "video.mp4", run_dir=out_dir / "render-run")
        fits = [e for e in res.log if e["step"] == "fit_check"]
        return res.status == "done", f"{res.status}, {res.duration or 0:.0f}s video, {len(fits)} fit round(s)" + (
            f", {res.error}" if res.error else ""
        )

    run("render", video)
    return rows


# ------------------------------------------------------------------ voices
def check_voices(
    specs: list[str], out_dir: Path, *, stt_key: str | None = None, settings=None, on_row=None
) -> list[dict]:
    """Synthesize one sentence with each voice spec (openai:, elevenlabs:, inworld:, kokoro:, voicestudio:),
    and transcribe it back with Inworld inworld-stt-1 when a key is available."""
    from .config import Settings
    from .voice import build_voice

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = settings or Settings()
    rows: list[dict] = []
    stt = InworldSTT(api_key=stt_key) if stt_key else None
    for spec in specs:
        wav = out_dir / (spec.replace(":", "_").replace("/", "_") + ".wav")
        t = time.monotonic()
        try:
            clip = build_voice(spec, settings).synthesize(SENTENCE, wav)
            ok, detail = clip.duration > 1.0, f"{clip.duration:.1f}s -> {wav.name}"
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {str(e)[:240]}"
        r = _row(f"tts {spec}", ok, detail, time.monotonic() - t)
        rows.append(r)
        if on_row:
            on_row(r)
        if ok and stt:
            t = time.monotonic()
            try:
                heard = stt.transcribe(wav).text
                score = similarity(SENTENCE, heard)
                r = _row(f"listen {spec}", score >= 0.8, f"score {score:.2f}: {heard[:100]!r}", time.monotonic() - t)
            except Exception as e:  # noqa: BLE001
                r = _row(f"listen {spec}", False, f"{type(e).__name__}: {str(e)[:240]}", time.monotonic() - t)
            rows.append(r)
            if on_row:
                on_row(r)
    return rows
