"""One course, many languages: translate a reviewed plan and render it once per language.

Only words change. The scenes, layouts, reveal order, brand and design stay exactly as reviewed, so every
language version has the same structure, and its timing comes from its own narration. What gets
translated is read from the catalog: every on-screen text field of every scene (code, web addresses and
stat values are left alone), the narration and captions of every beat, the title and the chrome labels.

Each language gets its own voice: a Kokoro voice for the languages Kokoro reads (en, es, fr, hi, it, pt,
zh), otherwise the cloud voice you name for it. A language with no usable voice is reported before any
model call or render, never half-way through a batch. Right-to-left scripts are laid out right to left.

    kinetry localize plan.json --to es,fr,ar --voice ar=inworld:inworld-tts-1:<arabic-voice> --out-dir out/i18n
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import Settings
from .design.catalog import TOLERANCE, Catalog, FieldSpec, load_catalog
from .design.plan import VideoPlan2, load_plan
from .textwidth import text_width
from .voice import KOKORO_BY_LANG, KOKORO_CANT_READ, kokoro_lang, lang_code

# on-screen fields that are not prose: left exactly as they are
KEEP = {("code_snippet", "code"), ("annotated_mock", "address"), ("big_stat", "value")}
# fields that must be an exact phrase of another field in the same scene
MARKS = {"statement": ("emphasis", "text"), "pull_quote": ("highlight", "quote")}
# plan-level text and its width limits (see design/plan.py)
TOP = {"title": 90, "chrome_left": 40, "chrome_right": 30}
NAV, SAY = 20, 400

LANG_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "ar": "Arabic",
    "fa": "Persian",
    "he": "Hebrew",
    "ur": "Urdu",
    "hi": "Hindi",
    "bn": "Bengali",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "th": "Thai",
    "sv": "Swedish",
}
REGIONS = {"pt-br": "Brazilian Portuguese", "pt-pt": "European Portuguese", "zh-tw": "Chinese (Traditional)"}


def language_name(lang: str) -> str:
    low = lang.lower().replace("_", "-")
    return REGIONS.get(low) or LANG_NAMES.get(lang_code(lang), lang)


# ------------------------------------------------------------------ what to translate
@dataclass
class Item:
    id: str  # where it goes, e.g. "s2.d.steps.1.title" or "s2.b0.say"
    text: str
    max: int  # visual width (CJK characters count 2)
    kind: str  # screen | spoken | caption

    def brief(self) -> dict:
        return {"id": self.id, "text": self.text, "max": self.max, "kind": self.kind}


def _walk(spec: FieldSpec, value: Any, path: str, out: list[tuple[str, str, int]]) -> None:
    if spec.type == "text" and isinstance(value, str) and value.strip():
        out.append((path, value, spec.max or 200))
    elif spec.type == "list" and isinstance(value, list) and spec.of is not None:
        for i, v in enumerate(value):
            _walk(spec.of, v, f"{path}.{i}", out)
    elif spec.type == "object" and isinstance(value, dict):
        for k, sub in spec.fields.items():
            if k in value:
                _walk(sub, value[k], f"{path}.{k}" if path else k, out)
        if not spec.fields:  # a free-form map, like dialogue speakers: {"a": {...}, "b": {...}}
            for k, v in value.items():
                if spec.of is not None:
                    _walk(spec.of, v, f"{path}.{k}", out)


def extract(plan: VideoPlan2, cat: Catalog | None = None) -> list[Item]:
    """Every piece of text a viewer sees or hears, with its width limit."""
    cat = cat or load_catalog()
    items = [Item(k, getattr(plan, k), m, "screen") for k, m in TOP.items() if getattr(plan, k)]
    for si, sc in enumerate(plan.scenes):
        if sc.nav:
            items.append(Item(f"s{si}.nav", sc.nav, NAV, "screen"))
        comp = cat.components.get(sc.type)
        if comp is not None:
            found: list[tuple[str, str, int]] = []
            for name, spec in comp.fields.items():
                if (sc.type, name) in KEEP or name not in sc.data:
                    continue
                _walk(spec, sc.data[name], name, found)
            items += [Item(f"s{si}.d.{p}", t, m, "screen") for p, t, m in found]
        for bi, b in enumerate(sc.beats):
            items.append(Item(f"s{si}.b{bi}.say", b.say, SAY, "spoken"))
            if b.caption:
                items.append(Item(f"s{si}.b{bi}.caption", b.caption, SAY, "caption"))
    return items


def _set(obj: Any, parts: list[str], text: str) -> None:
    for p in parts[:-1]:
        obj = obj[int(p)] if isinstance(obj, list) else obj[p]
    last = parts[-1]
    if isinstance(obj, list):
        obj[int(last)] = text
    else:
        obj[last] = text


def apply(plan: VideoPlan2, lang: str, texts: dict[str, str]) -> tuple[VideoPlan2, list[str]]:
    """A copy of the plan with the translated texts in place and design.lang set. Returns notes for anything
    adjusted (an emphasis phrase that no longer appears in its sentence is dropped, not left pointing at
    nothing)."""
    d = plan.model_dump(mode="json")
    notes: list[str] = []
    for key, text in texts.items():
        if key in TOP:
            d[key] = text
            continue
        m = re.fullmatch(r"s(\d+)\.(nav|d\.(.+)|b(\d+)\.(say|caption))", key)
        if not m:
            continue
        sc = d["scenes"][int(m.group(1))]
        if m.group(2) == "nav":
            sc["nav"] = text
        elif m.group(3):
            _set(sc["data"], m.group(3).split("."), text)
        else:
            sc["beats"][int(m.group(4))][m.group(5)] = text
    for si, sc in enumerate(d["scenes"]):
        if sc["type"] in MARKS:
            mark, whole = MARKS[sc["type"]]
            phrase, full = sc["data"].get(mark), sc["data"].get(whole) or ""
            if phrase and phrase.casefold() not in full.casefold():
                sc["data"].pop(mark)
                notes.append(f"scene {si + 1}: '{mark}' isn't a phrase of the translated {whole}, so it was left out")
    d["design"]["lang"] = lang
    # the plan's own Kokoro voices speak its original language: let each language pick its own
    d["voices"] = {r: v for r, v in (d.get("voices") or {}).items() if kokoro_lang(v) in (None, lang_code(lang))}
    return VideoPlan2.model_validate(d), notes


# ------------------------------------------------------------------ the model call
class Translated(BaseModel):
    id: str
    text: str = Field(..., description="The translation")


class Translation(BaseModel):
    items: list[Translated] = Field(default_factory=list)


SYSTEM = """You translate the script and on-screen text of a short narrated training video.

You get a list of items. Return every item, with the same id, translated into {language}.
- Keep the meaning, tone and level of formality of the original; write as a native speaker would say it.
  Address the viewer the way good training material in {language} does.
- kind "spoken" is narration read aloud by a voice: write it to be heard. Spell out symbols that read
  badly aloud, and keep sentences short.
- kind "screen" is text on a slide. It must stay within "max" (visual width: Chinese, Japanese and Korean
  characters count 2). Shorter is better than a cramped literal translation.
- Narration and the on-screen text it reveals must use the same words for the same things.
- Leave unchanged: people's names, product and brand names, code, commands, file names, web addresses,
  email addresses and numbers.
- If an item is a short phrase taken from another item (an emphasis or highlight), translate it so it is
  still an exact phrase of that item's translation."""


def _ask(payload: list[dict], lang: str, settings: Settings, llm, rec, name: str, lead: str = "") -> dict[str, str]:
    from .agents import get_llm
    from .llm import invoke_structured

    def _run() -> Translation:
        model = get_llm(settings, llm, 0.2)
        msgs = [
            {"role": "system", "content": SYSTEM.format(language=language_name(lang))},
            {"role": "user", "content": lead + json.dumps(payload, ensure_ascii=False, indent=1)},
        ]
        return invoke_structured(model, Translation, msgs)

    out = rec.call(name, Translation, _run)
    return {t.id: t.text.strip() for t in out.items if t.text.strip()}


def translate(
    plan: VideoPlan2,
    lang: str,
    *,
    settings: Settings | None = None,
    llm=None,
    rec=None,
    cat: Catalog | None = None,
) -> tuple[VideoPlan2, list[str]]:
    """The plan in another language. One model call for the whole plan (so terms stay consistent), plus one
    follow-up for anything missing or too long. Raises ValueError if the result still isn't usable."""
    settings = settings or Settings()
    cat = cat or load_catalog()
    items = extract(plan, cat)
    tag = lang_code(lang) if lang_code(lang) == lang.lower() else lang.lower().replace("_", "-")
    got = _ask([i.brief() for i in items], lang, settings, llm, rec, f"translate-{tag}")
    by_id = {i.id: i for i in items}
    got = {k: v for k, v in got.items() if k in by_id}

    def problems() -> list[Item]:
        limit = lambda it: it.max * (TOLERANCE if it.kind == "screen" else 1)  # noqa: E731
        return [it for it in items if it.id not in got or text_width(got[it.id]) > limit(it)]

    bad = problems()
    if bad:  # one more try for just those, showing the attempt that was too long
        lead = "These items were missing or too long last time ('too_long' is that attempt). Translate each again:\n"
        payload = [{**it.brief(), **({"too_long": got[it.id]} if it.id in got else {})} for it in bad]
        fixed = _ask(payload, lang, settings, llm, rec, f"translate-{tag}-fix", lead)
        got.update({k: v for k, v in fixed.items() if k in by_id})
        bad = problems()
    if bad:
        miss = [i.id for i in bad if i.id not in got]
        long_ = [f"{i.id} ({text_width(got[i.id])}>{i.max})" for i in bad if i.id in got]
        raise ValueError(
            f"{language_name(lang)}: the translation is incomplete"
            + (f"; missing {', '.join(miss[:6])}" if miss else "")
            + (f"; too long: {', '.join(long_[:6])}" if long_ else "")
        )
    out, notes = apply(plan, lang, got)
    errs = cat.validate_plan(out)
    if errs:
        raise ValueError(f"{language_name(lang)}: the translated plan doesn't validate: {'; '.join(errs[:4])}")
    return out, notes


# ------------------------------------------------------------------ voices
def plan_voices(
    lang: str,
    plan: VideoPlan2,
    given: dict[str, str] | None = None,
    brand_voices: dict[str, str] | None = None,
    default_voice: str | None = None,
) -> tuple[dict[str, str], str | None]:
    """The voices to render one language with, and why it can't be voiced (or None).

    `plan` is the translated plan (its Kokoro voices for other languages already dropped), `given` the voices
    asked for this language ({role: spec}), `brand_voices` the brand profile's. A brand's Kokoro voice for
    another language is replaced by this language's Kokoro voice; cloud voices are kept as they are."""
    code = lang_code(lang)
    given = dict(given or {})
    for role, spec in given.items():
        kl = kokoro_lang(spec)
        if kl is not None and kl != code:
            return given, f"{language_name(lang)}: the {role} voice {spec} speaks {language_name(kl)}"
    out = dict(given)
    bv = brand_voices or {}
    local = KOKORO_BY_LANG.get(code)
    usable = lambda v: bool(v) and kokoro_lang(v) in (None, code)  # noqa: E731  (a cloud voice, or Kokoro in this language)
    narrator = (
        out.get("narrator") or plan.voices.get("narrator") or (bv["narrator"] if usable(bv.get("narrator")) else None)
    )
    if narrator is None:
        narrator = default_voice if usable(default_voice) else None
    if narrator is None and local:
        narrator = out["narrator"] = f"kokoro:{local[0]}"
    narrator = narrator or default_voice or "kokoro:af_heart"
    # other speakers: asked for, the plan's, the brand's (if usable); with a local narrator, this language's
    # other Kokoro voices, so a second speaker never sounds like the first
    rest = sorted(plan.roles() - {"narrator"}, key=lambda r: (r not in ("a", "b"), r))
    for i, role in enumerate(rest):
        if role in out or role in plan.voices:
            continue
        if usable(bv.get(role)):
            out[role] = bv[role]
        elif local and narrator.startswith("kokoro:"):
            pick = {"a": 1, "b": 2}.get(role, 1 + i % 2)
            out[role] = f"kokoro:{local[pick]}"
    others = [out.get(r) or plan.voices.get(r) for r in rest]
    uses_local = any(isinstance(v, str) and v.startswith("kokoro:") for v in [narrator, *others])
    if uses_local and (code in KOKORO_CANT_READ or not local):
        return out, (
            f"{language_name(lang)} needs a cloud voice (the local Kokoro voices don't speak it): "
            f"pass --voice {code}=inworld:<model>:<voice> (or openai:/elevenlabs:)"
        )
    return out, None


def parse_voice_args(args: list[str] | None) -> dict[str, dict[str, str]]:
    """['es=kokoro:ef_dora', 'es.a=kokoro:em_alex', 'ar=inworld:...'] -> {'es': {'narrator': ..., 'a': ...}, ...}"""
    out: dict[str, dict[str, str]] = {}
    for a in args or []:
        if "=" not in a:
            raise ValueError(f"--voice takes LANG=SPEC or LANG.ROLE=SPEC, not {a!r}")
        k, spec = a.split("=", 1)
        lang, _, role = k.partition(".")
        if not lang or not spec:
            raise ValueError(f"--voice takes LANG=SPEC or LANG.ROLE=SPEC, not {a!r}")
        out.setdefault(lang.lower(), {})[role or "narrator"] = spec
    return out


def parse_langs(s: str | list[str]) -> list[str]:
    raw = s if isinstance(s, list) else re.split(r"[,\s]+", s)
    seen, out = set(), []
    for x in raw:
        x = x.strip()
        if not x:
            continue
        if not re.fullmatch(r"[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?", x):
            raise ValueError(f"not a language code: {x!r} (use codes like es, fr, pt-BR, zh)")
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    if not out:
        raise ValueError("no languages given (e.g. --to es,fr,de)")
    return out


# ------------------------------------------------------------------ results
@dataclass
class Localized:
    lang: str
    plan: VideoPlan2 | None = None
    plan_file: Path | None = None
    video: Path | None = None
    run_dir: Path | None = None
    duration: float | None = None
    package: Path | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    status: str = "pending"  # translated | done | error

    @property
    def ok(self) -> bool:
        return self.error is None and self.status in ("translated", "done")

    def to_dict(self) -> dict:
        return {
            "lang": self.lang,
            "language": language_name(self.lang),
            "status": self.status,
            "plan": str(self.plan_file) if self.plan_file else None,
            "video": str(self.video) if self.video else None,
            "run_dir": str(self.run_dir) if self.run_dir else None,
            "duration": self.duration,
            "package": str(self.package) if self.package else None,
            "notes": self.notes,
            "error": self.error,
        }


def source_plan(path: str | Path) -> VideoPlan2:
    """A plan file, or a run directory (the plan as it was rendered, after any fit-loop rewrites)."""
    p = Path(path)
    if p.is_dir():
        rep = p / "report.json"
        if not rep.exists():
            raise FileNotFoundError(f"{p} has no report.json: pass a plan file or a finished run directory")
        data = json.loads(rep.read_text(encoding="utf-8")).get("plan")
        if not data:
            raise ValueError(f"{rep} has no plan in it")
        return load_plan(data)
    return load_plan(json.loads(p.read_text(encoding="utf-8")))
