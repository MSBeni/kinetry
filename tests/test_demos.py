"""The bundled demos: valid plans, loadable brands, and a CLI that never needs a key."""

import json
import subprocess
import sys

import pytest

from kinetry.branding import BrandPack
from kinetry.config import Settings
from kinetry.demos import DEMOS, missing_tools, render_demo
from kinetry.design.catalog import load_catalog
from kinetry.design.plan import load_plan
from kinetry.voice import kokoro_lang


@pytest.mark.parametrize("name", sorted(DEMOS))
def test_demo_plan_matches_catalog(name):
    plan = load_plan(DEMOS[name].plan_data())
    assert load_catalog().validate_plan(plan) == []


@pytest.mark.parametrize("name", sorted(DEMOS))
def test_demo_brand_loads(name):
    pack = BrandPack.load(DEMOS[name].brand_dir())
    assert pack.kit.name
    assert pack.logo is not None


@pytest.mark.parametrize("name", sorted(DEMOS))
def test_demo_voices_are_local_and_speak_the_plan_language(name):
    d = DEMOS[name]
    plan = load_plan(d.plan_data())
    lang = (plan.design.lang or "en").split("-")[0]
    for role, spec in d.voices.items():
        assert spec.startswith("kokoro:"), f"{name}/{role}: a demo must not need a cloud key"
        assert kokoro_lang(spec) == lang
    # every role the plan uses has a voice
    assert plan.roles() <= set(d.voices) | {"narrator"}


def test_unknown_demo_is_refused():
    with pytest.raises(KeyError):
        render_demo("nope")


def test_render_demo_never_reaches_a_model(monkeypatch, tmp_path):
    seen = {}

    class Fake:
        def __init__(self, settings=None, workdir=None, **kw):
            seen["provider"] = settings.llm_provider

        def render(self, plan, **kw):
            seen["voice"] = kw["voice"]
            seen["voices"] = kw["voices"]
            return "ok"

    monkeypatch.setattr("kinetry.api.Kinetry", Fake)
    assert render_demo("spanish", out=tmp_path / "x.mp4", settings=Settings()) == "ok"
    assert seen["provider"] == "replay"
    assert seen["voice"] == "kokoro:ef_dora" and "narrator" not in seen["voices"]


def test_missing_tools_is_a_list_of_fixes():
    assert isinstance(missing_tools(Settings()), list)


def test_cli_lists_demos():
    out = subprocess.run(
        [sys.executable, "-m", "kinetry", "demo", "--list"], capture_output=True, text=True, check=True
    )
    for name in DEMOS:
        assert name in out.stdout


def test_cli_rejects_unknown_demo():
    res = subprocess.run([sys.executable, "-m", "kinetry", "demo", "nope"], capture_output=True, text=True)
    assert res.returncode == 2 and "choose one of" in res.stderr


def test_demo_files_ship_in_the_package():
    from importlib import resources

    root = resources.files("kinetry.demos")
    for d in DEMOS.values():
        assert (root / "plans" / d.plan).is_file()
        assert json.loads((root / "brands" / d.brand / "brand.json").read_text())["name"]
