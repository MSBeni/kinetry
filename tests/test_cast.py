"""Casts: named characters with voices for role-play and dialogue videos."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinetry.cast import Cast, load_cast, parse_assign
from kinetry.cli import main

CAST = Path(__file__).parent.parent / "examples" / "casts" / "customer-conversations.json"


def test_example_cast_loads_and_maps_roles():
    cast = load_cast(CAST)
    assert cast.spec("skeptic_female") == "inworld:inworld-tts-2:Ashley"  # the cast's model fills in
    assert cast.spec("newcomer_male") == "inworld:inworld-tts-2-flash:Alex"  # an explicit model wins
    assert cast.spec("newcomer_female") == "kokoro:af_nova"  # casts can mix providers
    assert cast.voices({"narrator": "coach", "a": "skeptic_male"}) == {
        "narrator": "inworld:inworld-tts-2:Sarah",
        "a": "inworld:inworld-tts-2:Dennis",
    }
    assert cast.inworld_ids()["coach"] == "Sarah" and "newcomer_female" not in cast.inworld_ids()
    with pytest.raises(KeyError):
        cast.spec("nobody")


def test_verify_against_account_voices():
    cast = load_cast(CAST)
    found = cast.verify_inworld([{"voiceId": v} for v in ("Sarah", "Dennis", "Ashley")])
    assert found == {"coach": True, "skeptic_male": True, "skeptic_female": True, "newcomer_male": False}


@pytest.mark.parametrize(
    "bad",
    [
        {"characters": [{"id": "Bad Id", "voice": "inworld:Reed"}]},
        {"characters": [{"id": "x", "voice": "inworld:../../etc"}]},
        {"characters": [{"id": "x", "voice": "somewhere:Reed"}]},
        {"characters": [{"id": "x", "voice": "inworld:Reed"}, {"id": "x", "voice": "inworld:Mia"}]},
        {"model": "inworld-tts-9", "characters": [{"id": "x", "voice": "inworld:Reed"}]},
    ],
)
def test_bad_casts_are_rejected(bad):
    with pytest.raises(ValidationError):
        Cast.model_validate(bad)


def test_parse_assign():
    assert parse_assign(["a=gatekeeper_female", " b = rookie_male "]) == {"a": "gatekeeper_female", "b": "rookie_male"}
    with pytest.raises(ValueError):
        parse_assign(["a"])


def test_cli_cast_listing(capsys):
    assert main(["cast", str(CAST)]) == 0
    out = capsys.readouterr().out
    assert "skeptic_female" in out and "inworld:inworld-tts-2:Ashley" in out
    assert json.loads(CAST.read_text())["characters"][4]["appearance"] in out
