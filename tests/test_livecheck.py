"""check-llm and check-voices logic with stand-in models and voices (the live runs need real keys)."""

import json
import wave
from pathlib import Path

from kinetry.livecheck import SENTENCE, check_llm, check_voices
from kinetry.voice import Clip

PLAN = json.loads((Path(__file__).parent.parent / "examples" / "plans" / "spot-the-phish.json").read_text())
CHOICE = {"style": "editorial", "format": "16:9", "pacing": "normal", "rationale": "Coaching content."}


class Model:
    """Answers the director with a DesignChoice and the planner with a plan, through tool calling."""

    def __init__(self, broken=False):
        self.broken, self.asked = broken, []

    def with_structured_output(self, schema):
        outer = self

        class R:
            def invoke(self, messages):
                outer.asked.append(schema.__name__)
                if outer.broken:
                    raise RuntimeError("AccessDeniedException: no access to model")
                return CHOICE if schema.__name__ == "DesignChoice" else PLAN

        return R()

    def invoke(self, messages):  # the planner asks for JSON text
        self.asked.append("json")
        if self.broken:
            raise RuntimeError("AccessDeniedException: no access to model")

        class Msg:
            text = "```json\n" + json.dumps(PLAN) + "\n```"

        return Msg()


def test_check_llm_runs_director_then_planner(tmp_path, monkeypatch):
    monkeypatch.setenv("KINETRY_LLM", "bedrock")
    m = Model()
    rows = check_llm(m, tmp_path)
    assert [(r["step"], r["ok"]) for r in rows] == [("director", True), ("planner", True)], rows
    assert "style editorial" in rows[0]["detail"] and "scenes" in rows[1]["detail"]
    assert (tmp_path / "plan.json").exists() and m.asked[0] == "DesignChoice"


def test_check_llm_fails_loudly_instead_of_falling_back(tmp_path, monkeypatch):
    monkeypatch.setenv("KINETRY_LLM", "bedrock")
    rows = check_llm(Model(broken=True), tmp_path)
    assert len(rows) == 1 and not rows[0]["ok"] and "AccessDenied" in rows[0]["detail"]


def test_check_voices_reports_each_voice(tmp_path, monkeypatch):
    class V:
        def synthesize(self, text, out):
            assert text == SENTENCE
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"\0\0" * 24000 * 3)
            return Clip(Path(out), 3.0)

    def build(spec, settings, api_key=None):
        if spec.startswith("elevenlabs:"):
            raise ValueError("elevenlabs voice needs an API key")
        return V()

    monkeypatch.setattr("kinetry.voice.build_voice", build)
    rows = check_voices(["openai:coral", "elevenlabs:abc"], tmp_path)
    assert [(r["step"], r["ok"]) for r in rows] == [("tts openai:coral", True), ("tts elevenlabs:abc", False)]
    assert "API key" in rows[1]["detail"]
