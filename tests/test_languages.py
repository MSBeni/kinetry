"""Scripts other than English: voices by language, Chinese/Japanese text splitting, width-based limits."""

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinetry.design.plan import Scene, load_plan
from kinetry.design.profile import BrandProfile
from kinetry.design.render import _words, caption_chunks, is_cjk, text_weight, tokens
from kinetry.graph import role_voices
from kinetry.textwidth import text_width
from kinetry.voice import kokoro_lang, lang_code

FEEDBACK = json.loads((Path(__file__).parent.parent / "examples" / "plans" / "feedback-that-lands.json").read_text())


def plan_in(lang: str):
    p = load_plan(json.loads(json.dumps(FEEDBACK)))
    p.design.lang = lang
    return p


def job(**kw):
    return {"voice": None, "voices": {}, "default_voice": "kokoro:af_heart", **kw}


@pytest.mark.parametrize(
    "lang,narrator,a",
    [
        ("es", "ef_dora", "em_alex"),
        ("pt-BR", "pf_dora", "pm_alex"),
        ("hi", "hf_alpha", "hm_omega"),
        ("zh-CN", "zf_xiaoxiao", "zm_yunxi"),
    ],
)
def test_default_voice_follows_the_script_language(lang, narrator, a):
    v = role_voices(plan_in(lang), job(), BrandProfile())
    assert v["narrator"] == f"kokoro:{narrator}" and v["a"] == f"kokoro:{a}"


def test_chosen_voices_are_kept():
    assert role_voices(plan_in("es"), job(voice="kokoro:af_bella"), BrandProfile())["narrator"] == "kokoro:af_bella"
    assert role_voices(plan_in("es"), job(default_voice="openai:coral"), BrandProfile())["narrator"] == "openai:coral"
    assert role_voices(plan_in("en"), job(), BrandProfile())["narrator"] == "kokoro:af_heart"
    assert role_voices(plan_in("de"), job(), BrandProfile())["narrator"] == "kokoro:af_heart"  # no German Kokoro


def test_japanese_refuses_kokoro_but_takes_cloud_voices():
    with pytest.raises(ValueError, match="Japanese"):
        role_voices(plan_in("ja"), job(), BrandProfile())
    v = role_voices(plan_in("ja"), job(voice="openai:coral"), BrandProfile())
    assert v["narrator"] == "openai:coral" and v["a"] == "openai:onyx"


def test_language_codes():
    assert lang_code("pt-BR") == "pt" and lang_code("zh_Hans") == "zh" and lang_code(None) == "en"
    assert kokoro_lang("kokoro:ef_dora") == "es" and kokoro_lang("kokoro:bf_emma") == "en"
    assert kokoro_lang("openai:coral") is None


def test_cjk_tokens_keep_punctuation_with_characters():
    assert [t for _, t, _ in tokens("「安全」が最優先です。")] == ["「安", "全」", "が", "最", "優", "先", "で", "す。"]
    assert [t for _, t, _ in tokens("Ask what they need.")] == ["Ask", "what", "they", "need."]
    assert is_cjk("先确认发件人，再点击链接。") and not is_cjk("Usa la API v2.0 hoy.")
    assert text_weight("先确认发件人。") == 6 and text_weight("one two three") == 3


def test_words_markup_is_unchanged_for_spaced_scripts():
    assert _words("Ask what they need", "what they") == (
        '<span class="w"><span>Ask</span></span> <span class="w hlw"><span>what</span></span> '
        '<span class="w hlw"><span>they</span></span> <span class="w"><span>need</span></span>'
    )
    cjk = _words("最優先です", "優先")
    assert "</span> <span" not in cjk and cjk.count('class="w hlw"') == 2


def test_cjk_captions_break_at_sentences_and_commas():
    text = "「安全」が最優先です。リンクをクリックする前に、送信者を確認しましょう！"
    assert caption_chunks(text, 14) == ["「安全」が最優先です。", "リンクをクリックする前に、送信者を確認しましょう！"]
    assert caption_chunks(text, 8) == [
        "「安全」が最優先です。",
        "リンクをクリックする前に、",
        "送信者を確認しましょう！",
    ]
    for c in caption_chunks("あ" * 60, 8):  # no punctuation at all: hard breaks within the limit
        assert 0 < len(c) <= 18


def test_limits_count_visual_width():
    assert text_width("Checks") == 6 and text_width("確認") == 4 and text_width("इससे क्या साबित होता है") == 15
    Scene(type="title", nav="इससे क्या साबित होता है", beats=[{"say": "hi there"}])  # 23 code points, 15 wide
    with pytest.raises(ValidationError):
        Scene(type="title", nav="確認できること確認できること", beats=[{"say": "hi there"}])  # 14 chars, 28 wide


# ---------------------------------------------------------------- right-to-left scripts
def test_rtl_languages():
    from kinetry.voice import is_rtl

    assert all(is_rtl(x) for x in ("fa", "ar-EG", "he", "ur")) and not is_rtl("en") and not is_rtl("hi")


def test_latin_runs_stay_together_in_rtl_headlines():
    import re

    def boxes(html):
        return [re.sub("<[^>]+>", "", m) for m in re.findall(r'<span class="w[^"]*"><span>(.*?)</span></span>', html)]

    fa = "قبل از کلیک در Microsoft Outlook v2.0 مکث کنید."
    assert boxes(_words(fa, rtl=True)) == ["قبل", "از", "کلیک", "در", "Microsoft Outlook v2.0", "مکث", "کنید."]
    assert len(boxes(_words(fa))) == 9  # left-to-right pages keep one box per word
    assert 'class="w hlw"><span>Microsoft Outlook v2.0<' in _words(fa, "Outlook", rtl=True)


def _page(tmp_path, plan, name):
    """HTML only, offline: no fonts download and no rendering toolchain."""
    from kinetry.branding import DEFAULT_KIT
    from kinetry.design.catalog import load_catalog
    from kinetry.design.icons import Icons
    from kinetry.design.render import RenderInput, write_project
    from kinetry.timing import build_timeline, silent_clips

    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("/* gsap */")
    tl = build_timeline(plan, silent_clips(plan), plan.design.pacing)
    ri = RenderInput(plan=plan, brand=DEFAULT_KIT, fonts={}, timeline=tl, catalog=load_catalog(), icons=Icons(None))
    out = write_project(ri, tmp_path / name, gsap)
    return (out / "index.html").read_text() if out.is_dir() else out.read_text()


def test_rtl_page_direction_is_on_the_root_not_html(tmp_path):
    """HyperFrames renders a blank video when <html dir="rtl">; the direction lives on #root."""
    html = _page(tmp_path, plan_in("fa"), "fa")
    assert '<html lang="fa">' in html and 'dir="rtl"' not in html
    assert re.search(r'id="root" class="[^"]*\brtl\b[^"]*\bcursive\b', html)
    root = re.search(r'id="root" class="([^"]*)"', _page(tmp_path, plan_in("he"), "he")).group(1)
    assert "rtl" in root.split() and "cursive" not in root.split()  # Hebrew isn't joined: letter-spacing is fine
