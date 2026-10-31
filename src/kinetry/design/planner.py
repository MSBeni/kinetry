"""The planner: source content -> a v2 plan of catalog scenes.

The model sees the catalog guide (generated from the component manifests), the design the
creative director chose, and the content. It answers with JSON; the catalog validates every
scene (types, fields, limits, reveal keys, dialogue voices) and errors go back for another try.
Layouts are then picked by code, not by the model.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .catalog import Catalog, load_catalog
from .layout import pick_layouts
from .plan import Design, VideoPlan2, load_plan

PLANNER_SYSTEM = """You turn source content into a short narrated video, built from a catalog of animated scene types.

{guide}

Content rules:
- Use only facts present in the source. Never invent numbers, names, quotes, products or resources.
  big_stat and bar_chart only with numbers that appear in the source.
- Narration speaks to the viewer ("you"), warm and plain. About {words_lo}-{words_hi} words in total.
- On-screen text is a compressed echo of the narration, not a transcript. Respect every character limit.
- Each beat is 1-2 sentences. `show` lists the element keys revealed when that beat starts; reveal each key
  at most once, on the beat that first talks about it. Keys never shown appear as the scene opens.
- {n_lo}-{n_hi} scenes. Start with 'title' and end with 'closer'.
- Choose each scene's type for the shape of what it says: an order -> numbered_steps, agenda_timeline or steps_path;
  right vs wrong -> do_dont or instead_try; options -> comparison; one insight -> pull_quote; a key term -> definition;
  a conversation -> dialogue; parallel ideas -> card_grid or icon_grid; a screen or message -> annotated_mock;
  written chat messages -> chat_thread; code or commands -> code_snippet (copied exactly); values over time -> line_chart;
  an if/then rule -> decision.
- Vary the picture: never the same type twice in a row; use at least {variety} different types.
- Favor where they fit: {prefer}. Never use: {avoid}.
- dialogue: one beat per line, with "voice" set to that line's speaker id ("a" or "b").
- {images_rule}
- icon fields take a Lucide icon name ("calendar", "shield-check", "coffee", "users") or a plain noun.
- Write everything in {lang}. If that isn't English, also fill the optional label fields that otherwise show
  English defaults (do_label, dont_label, instead_label, try_label, sticky_tip label, here_label).
  Length limits (text<=N) are widths: Chinese, Japanese and Korean characters count 2, accents and vowel signs 0.
- The look is already decided ({design}). {format_note}
{kind_rule}
Answer with ONE JSON object and nothing else:
{{"title": str, "chrome_left": str, "chrome_right": str,
  "scenes": [{{"type": str, "nav": str, "data": {{...}}, "beats": [{{"say": str, "show": [str], "voice": str?}}]}}]}}
Leave out "layout" and "design"; they are filled in automatically.
"""

FORMAT_NOTES = {
    "16:9": "",
    "9:16": "Vertical phone video: keep on-screen text short and lists to 3 items.",
    "1:1": "Square video: keep on-screen text short and lists to 2-3 items.",
}


def context_images(context: dict, key: str = "images") -> list[dict]:
    """context["images"] (or ["animations"]) -> [{"ref": ..., "about": ...}].
    Accepts plain refs or {"ref"/"url", "about"/"description"}."""
    out = []
    for it in (context or {}).get(key) or []:
        if isinstance(it, str):
            it = {"ref": it}
        if not isinstance(it, dict):
            continue
        ref = str(it.get("ref") or it.get("url") or "").strip()
        if ref:
            out.append({"ref": ref, "about": str(it.get("about") or it.get("description") or "")[:300]})
    return out[:20]


def image_components(cat: Catalog) -> set[str]:
    return {c for c, comp in cat.components.items() if any(f.type == "image" for f in comp.fields.values())}


def image_refs_used(plan: VideoPlan2, cat: Catalog, ftype: str = "image") -> list[tuple[int, str, str]]:
    """(scene index, field, ref) for every image (or animation) field in the plan."""
    out = []
    for i, sc in enumerate(plan.scenes):
        comp = cat.components.get(sc.type)
        for k, f in (comp.fields if comp else {}).items():
            if f.type == ftype and isinstance(sc.data.get(k), str):
                out.append((i, k, sc.data[k]))
    return out


def target_seconds(context: dict) -> int:
    raw = str(context.get("length") or context.get("duration") or "")
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(s|sec|seconds?|m|min|minutes?)?\s*$", raw.lower())
    if not m:
        return 75
    v = float(m.group(1))
    return int(v * 60 if (m.group(2) or "s").startswith("m") else v)


def run_planner_v2(
    source_text: str,
    context: dict,
    design: Design,
    settings,
    rec,
    *,
    llm=None,
    prefer: list[str] | None = None,
    avoid: list[str] | None = None,
    name: str = "plan",
    catalog: Catalog | None = None,
) -> VideoPlan2:
    cat = catalog or load_catalog()
    if rec is not None and rec.replay:
        src = rec.replay_dir / f"{name}.json"
        if not src.exists():
            raise FileNotFoundError(f"replay mode: no recorded output {src}")
        plan = load_plan(json.loads(src.read_text()))
        (rec.dir / f"{name}.json").write_text(plan.model_dump_json(indent=2))
        return plan

    from ..kinds import get_kind

    kind = get_kind(context.get("kind"))
    if kind and not (context.get("length") or context.get("duration")):
        context = {**context, "length": kind.length}
    if kind:  # the kind's scene types come after the director's picks
        prefer = list(dict.fromkeys([*(prefer or []), *kind.prefer]))
    secs = target_seconds(context)
    words = secs * 2.45
    n_lo, n_hi = max(4, round(secs / 16)), max(6, round(secs / 10) + 1)
    fx = design.effects.resolved()
    # scene types that depend on a motion layer (e.g. kinetic statements) are offered only when it's on
    gated = {c for c, comp in cat.components.items() if comp.requires and fx.get(comp.requires, "off") == "off"}
    images = context_images(context)
    if not images:  # image scenes only when the request supplies images; the model never invents one
        gated |= image_components(cat)
    refs = {im["ref"] for im in images}
    anims = context_images(context, "animations")
    arefs = {a["ref"] for a in anims}
    allowed = [c for c in cat.components if c not in (avoid or []) and c not in gated]
    prefer = [c for c in (prefer or []) if c in allowed]
    sys = PLANNER_SYSTEM.format(
        guide=cat.planner_guide(allowed),
        words_lo=int(words * 0.85),
        words_hi=int(words * 1.15),
        n_lo=n_lo,
        n_hi=n_hi,
        variety=min(5, n_lo),
        prefer=", ".join(prefer or []) or "any",
        avoid=", ".join(avoid or []) or "none",
        lang=design.lang or "en",
        design=f"style {design.style}, format {design.resolved_format()}",
        format_note=FORMAT_NOTES.get(design.resolved_format(), ""),
        kind_rule=(f"- This is a {kind.name.lower()}: {kind.purpose} Structure: {kind.structure}\n" if kind else ""),
        images_rule=(
            "image fields take a ref exactly as listed in context.images; use an image only where it shows what "
            "the narration is about, describe it in alt from its 'about' note, and never write a ref of your own."
            if images
            else "No images were provided, so there are no image scenes."
        )
        + (
            " animation fields take a ref exactly as listed in context.animations (the caller's Lottie files), only "
            "where its 'about' note fits the scene."
            if anims
            else ""
        ),
    )

    def _run() -> VideoPlan2:
        from ..agents import get_llm
        from ..llm import invoke_structured

        model = get_llm(settings, llm)
        user = (
            f"Context:\n{json.dumps(context, indent=2, default=str)}\n\nSource content:\n<<<\n{source_text}\n>>>\n"
            "Return the plan JSON."
        )
        messages = [{"role": "system", "content": sys}, {"role": "user", "content": user}]
        last = ""
        for _ in range(settings.max_plan_attempts):
            if last:
                messages.append(
                    {"role": "user", "content": f"That plan has problems:\n{last}\nFix them and return the full JSON."}
                )
            try:
                plan = invoke_structured(model, VideoPlan2, messages, json_mode=True)
            except (ValidationError, ValueError) as e:
                last = str(e)[:3000]
                continue
            plan.design = design
            errs = cat.validate_plan(plan)
            used = {s.type for s in plan.scenes}
            errs += [f"scene type '{t}' is not allowed here" for t in used & (set(avoid or []) | gated)]
            errs += [
                f"scenes[{i}].data.{k}: '{r[:80]}' isn't in context.images; use one of: {', '.join(sorted(refs))}"
                for i, k, r in image_refs_used(plan, cat)
                if r not in refs
            ]
            errs += [
                f"scenes[{i}].data.{k}: '{r[:80]}' isn't in context.animations"
                + (f"; use one of: {', '.join(sorted(arefs))}" if arefs else "; leave it out")
                for i, k, r in image_refs_used(plan, cat, "animation")
                if r not in arefs
            ]
            w = plan.word_count()
            if not words * 0.65 <= w <= words * 1.4:
                errs.append(f"narration is {w} words; aim for {int(words * 0.85)}-{int(words * 1.15)}")
            if errs:
                last = "\n".join(errs[:25])
                continue
            return plan
        raise RuntimeError(f"planner failed after {settings.max_plan_attempts} attempts: {last}")

    plan = rec.call(name, VideoPlan2, _run) if rec is not None else _run()
    plan.design = design
    plan.voices = {}  # voices come from the request, brand profile or defaults, never from model output
    return pick_layouts(plan, cat)
