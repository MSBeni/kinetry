"""Localization: what gets translated, how it goes back in, voices per language. No model, no render."""

import json
from pathlib import Path

import pytest

from kinetry.agents import Recorder
from kinetry.config import Settings
from kinetry.design.plan import load_plan
from kinetry.localize import apply, extract, parse_langs, parse_voice_args, plan_voices, source_plan, translate

ROOT = Path(__file__).resolve().parents[1]
WELCOME = ROOT / "src" / "kinetry" / "demos" / "plans" / "welcome.json"
REPLAY = ROOT / "examples" / "replay" / "localize-welcome"


def welcome():
    return load_plan(json.loads(WELCOME.read_text()))


def replay_rec(tmp_path, replay_dir=REPLAY):
    s = Settings()
    s.llm_provider = "replay"
    return Recorder(tmp_path, s, replay_dir), s


def test_extract_reads_the_catalog_and_leaves_code_alone():
    items = {i.id: i for i in extract(welcome())}
    assert items["title"].max == 90 and items["s0.nav"].max == 20
    assert items["s1.d.steps.2.title"].text == "The frames were rendered"
    assert items["s1.b3.say"].kind == "spoken"
    assert not any(k.startswith("s2.d.code") for k in items)  # commands stay commands
    assert "s2.d.highlight" not in items  # numbers aren't text


def test_apply_puts_text_back_and_sets_the_language():
    p = welcome()
    p.voices = {"narrator": "kokoro:af_heart", "co": "inworld:inworld-tts-1:Ashley"}
    texts = {"title": "Tu primer video", "s1.d.steps.0.title": "Cada frase", "s3.b0.say": "Hola."}
    out, notes = apply(p, "es", texts)
    assert out.title == "Tu primer video" and out.design.lang == "es"
    assert out.scenes[1].data["steps"][0]["title"] == "Cada frase"
    assert out.scenes[3].beats[0].say == "Hola."
    assert out.scenes[2].data["code"] == p.scenes[2].data["code"]
    assert out.voices == {"co": "inworld:inworld-tts-1:Ashley"}  # the English Kokoro narrator is dropped
    assert p.title == "Your first Kinetry video" and not notes  # the original is untouched


def test_an_emphasis_that_no_longer_matches_is_dropped():
    p = load_plan(
        {
            "version": 2,
            "title": "T",
            "scenes": [
                {
                    "type": "statement",
                    "data": {"text": "Listen first, then decide", "emphasis": "Listen first"},
                    "beats": [{"say": "Listen first, then decide.", "show": ["text"]}],
                },
                {"type": "closer", "data": {"headline": "Done"}, "beats": [{"say": "Done.", "show": ["headline"]}]},
            ],
        }
    )
    ok, notes = apply(p, "es", {"s0.d.text": "Primero escucha, luego decide", "s0.d.emphasis": "Primero escucha"})
    assert ok.scenes[0].data["emphasis"] == "Primero escucha" and not notes
    bad, notes = apply(p, "es", {"s0.d.text": "Escucha y decide", "s0.d.emphasis": "Primero escucha"})
    assert "emphasis" not in bad.scenes[0].data and "emphasis" in notes[0]


@pytest.mark.parametrize("lang", ["es", "fr", "zh"])
def test_recorded_translations_make_valid_plans(tmp_path, lang):
    rec, s = replay_rec(tmp_path)
    out, notes = translate(welcome(), lang, settings=s, rec=rec)
    assert out.design.lang == lang and out.title != welcome().title
    assert [sc.type for sc in out.scenes] == [sc.type for sc in welcome().scenes]  # same structure
    assert [len(sc.beats) for sc in out.scenes] == [len(sc.beats) for sc in welcome().scenes]
    assert (tmp_path / "llm" / f"translate-{lang}.json").exists()


def test_missing_or_long_items_get_one_more_try(tmp_path):
    full = json.loads((REPLAY / "translate-es.json").read_text())
    first = {"items": [i for i in full["items"] if i["id"] not in ("s1.nav", "title")]}
    first["items"].append({"id": "s0.nav", "text": "Hola " * 10})  # too long for a nav label
    fix = {"items": [i for i in full["items"] if i["id"] in ("s1.nav", "title", "s0.nav")]}
    (tmp_path / "rp").mkdir()
    (tmp_path / "rp" / "translate-es.json").write_text(json.dumps(first))
    (tmp_path / "rp" / "translate-es-fix.json").write_text(json.dumps(fix))
    rec, s = replay_rec(tmp_path, tmp_path / "rp")
    out, _ = translate(welcome(), "es", settings=s, rec=rec)
    assert out.scenes[0].nav == "Hola" and out.title == "Tu primer video con Kinetry"


def test_still_incomplete_is_a_clear_error(tmp_path):
    (tmp_path / "rp").mkdir()
    (tmp_path / "rp" / "translate-es.json").write_text(json.dumps({"items": [{"id": "title", "text": "Hola"}]}))
    (tmp_path / "rp" / "translate-es-fix.json").write_text(json.dumps({"items": []}))
    rec, s = replay_rec(tmp_path, tmp_path / "rp")
    with pytest.raises(ValueError, match="Spanish: the translation is incomplete; missing"):
        translate(welcome(), "es", settings=s, rec=rec)


def test_voices_per_language():
    p = welcome()
    es, _ = apply(p, "es", {})
    v, why = plan_voices("es", es, {}, {}, "kokoro:af_heart")
    assert why is None and v == {"narrator": "kokoro:ef_dora", "co": "kokoro:em_alex"}  # two distinct voices
    v, why = plan_voices("es", es, {}, {"narrator": "kokoro:am_adam"}, None)
    assert v["narrator"] == "kokoro:ef_dora"  # the brand's English Kokoro voice can't read Spanish
    v, why = plan_voices("es", es, {}, {"narrator": "inworld:inworld-tts-1:Diego"}, None)
    assert "narrator" not in v and why is None  # a brand's cloud voice is kept
    de, _ = apply(p, "de", {})
    assert "German needs a cloud voice" in plan_voices("de", de, {}, {}, "kokoro:af_heart")[1]
    assert plan_voices("de", de, {"narrator": "inworld:inworld-tts-1:<german-voice>"}, {}, None)[1] is None
    assert "speaks English" in plan_voices("es", es, {"narrator": "kokoro:af_heart"}, {}, None)[1]
    ja, _ = apply(p, "ja", {})
    assert "Japanese needs a cloud voice" in plan_voices("ja", ja, {}, {}, None)[1]


def test_argument_parsing():
    assert parse_langs("es, fr,pt-BR,es") == ["es", "fr", "pt-BR"]
    with pytest.raises(ValueError):
        parse_langs("spanish!")
    assert parse_voice_args(["ar=inworld:inworld-tts-1:<arabic-voice>", "es.a=kokoro:em_alex"]) == {
        "ar": {"narrator": "inworld:inworld-tts-1:<arabic-voice>"},
        "es": {"a": "kokoro:em_alex"},
    }
    with pytest.raises(ValueError):
        parse_voice_args(["kokoro:ef_dora"])


def test_source_plan_from_a_run_dir(tmp_path):
    (tmp_path / "report.json").write_text(json.dumps({"plan": json.loads(WELCOME.read_text())}))
    assert source_plan(tmp_path).title == "Your first Kinetry video"
    with pytest.raises(FileNotFoundError):
        source_plan(tmp_path / "nope")


def test_batch_checks_every_voice_before_spending_anything(tmp_path):
    from kinetry import Kinetry

    tf = Kinetry(replay_dir=tmp_path / "empty")  # no recordings: any model call would fail loudly
    with pytest.raises(ValueError, match="German needs a cloud voice.*Arabic needs a cloud voice"):
        tf.localize(WELCOME, to="es,de,ar", out_dir=tmp_path / "out")
    assert not (tmp_path / "out" / "llm").exists() or not any((tmp_path / "out" / "llm").iterdir())


def test_translate_only_batch(tmp_path):
    from kinetry import Kinetry

    tf = Kinetry(replay_dir=REPLAY)
    items = tf.localize(WELCOME, to="es,zh,en,de", out_dir=tmp_path, render=False)
    by = {i.lang: i for i in items}
    assert by["es"].ok and by["zh"].ok and by["en"].notes == ["same language as the plan: not translated"]
    assert not by["de"].ok and "translate-de" in by["de"].error  # one failure doesn't stop the batch
    plan = json.loads((tmp_path / "your-first-kinetry-video.zh.plan.json").read_text())
    assert plan["design"]["lang"] == "zh" and plan["title"] == "你的第一个 Kinetry 视频"
    summary = json.loads((tmp_path / "localize.json").read_text())
    assert [x["status"] for x in summary["languages"]] == ["translated", "translated", "translated", "error"]
