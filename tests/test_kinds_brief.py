"""Video kinds (they shape the plan) and the brief agent (a request in plain words -> a structured request)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinetry.brief import Brief, heuristic_brief, make_brief
from kinetry.design.plan import load_plan
from kinetry.kinds import KINDS, get_kind
from kinetry.sources import Source

PLAN = json.loads((Path(__file__).parent.parent / "examples" / "plans" / "feedback-that-lands.json").read_text())
TEXT = "Feedback lands when it names the moment, the effect, and asks a question. " * 3


def test_source_kind_is_checked_and_reaches_the_context():
    s = Source(text=TEXT, kind="Session Recap")
    assert s.kind == "session_recap" and s.context["kind"] == "session_recap"
    assert Source(text=TEXT, context={"kind": "how-to"}).kind == "how_to"
    assert Source(text=TEXT).kind is None and "kind" not in Source(text=TEXT).context
    with pytest.raises(ValidationError, match="unknown video kind"):
        Source(text=TEXT, kind="podcast")
    for k in KINDS.values():
        assert get_kind(k.id) is k and k.structure and k.length


class ScriptedLLM:
    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def invoke(self, messages):
        self.prompts.append(messages)
        a = self.answers.pop(0)
        return a if isinstance(a, str) else json.dumps(a)


def test_kind_shapes_the_planner_prompt_and_length():
    from kinetry.config import Settings
    from kinetry.design.planner import run_planner_v2

    answer = {k: v for k, v in PLAN.items() if k != "design"}
    llm = ScriptedLLM(answer)
    ctx = Source(text=TEXT, kind="announcement").context
    run_planner_v2(TEXT, ctx, load_plan(PLAN).design, Settings(), None, llm=llm)
    sys = llm.prompts[0][0]["content"]
    assert KINDS["announcement"].structure in sys
    assert "About 93-126 words" in sys  # 45 s, the announcement default
    assert "big_stat" in sys.split("Favor where they fit:")[1].splitlines()[0]
    llm = ScriptedLLM(answer)
    run_planner_v2(TEXT, {**ctx, "length": "40s"}, load_plan(PLAN).design, Settings(), None, llm=llm)
    assert "About 83-112 words" in llm.prompts[0][0]["content"]  # an explicit length wins


def test_kind_sets_pacing_unless_pinned():
    from kinetry.design.director import choose_design
    from kinetry.design.plan import Design

    d, _, _ = choose_design(TEXT, {"kind": "session_recap"}, use_model=False)
    assert d.pacing == "brisk"
    d, _, _ = choose_design(TEXT, {"kind": "session_recap"}, overrides=Design(pacing="calm"), use_model=False)
    assert d.pacing == "calm"
    d, _, _ = choose_design(TEXT, {"kind": "lesson"}, use_model=False)
    assert d.pacing != "brisk"


# ---------------------------------------------------------------- brief
def test_keyword_brief_reads_the_request():
    b = heuristic_brief(
        "Make a 60-second vertical how-to video for new nurses about hand hygiene, in Spanish, with captions."
    )
    assert (b.kind, b.length, b.format, b.lang, b.captions, b.audience) == (
        "how_to", "60s", "9:16", "es", True, "new nurses",
    )  # fmt: skip
    assert b.topic == "hand hygiene" and b.questions and "content" in b.questions[0]
    r = b.to_request()
    assert r["source"] is None and r["pending_source"]["kind"] == "how_to" and r["design"]["format"] == "9:16"


def test_keyword_brief_keeps_pasted_content_verbatim():
    notes = (
        "Today we covered three things. First, run one-on-ones from their agenda. Second, feedback names the "
        "moment and the effect, then asks. Third, we agreed to try weekly fifteen-minute check-ins for a month "
        "and compare notes at the next session on the 14th, which is a Thursday this time."
    )
    b = heuristic_brief(f"Recap of today's session for the sales team in Farsi, square:\n\n{notes}")
    assert b.kind == "session_recap" and b.lang == "fa" and b.format == "1:1" and b.source_text == notes
    assert b.topic == "" and b.questions == []
    r = b.to_request()
    assert r["source"]["text"] == notes and r["source"]["kind"] == "session_recap"
    assert Source(**{k: v for k, v in r["source"].items() if v is not None}).kind == "session_recap"


def test_link_becomes_the_pending_source():
    b = heuristic_brief(
        "Announce the new expense policy at https://intranet.example.com/expenses. for all staff, 45 seconds"
    )
    assert b.kind == "announcement" and b.source_url == "https://intranet.example.com/expenses" and b.length == "45s"
    assert b.topic == "" and b.audience == "all staff" and b.questions == []


def test_model_brief_is_checked_by_code():
    msg = "Necesito un video corto sobre higiene de manos para enfermeras nuevas, formato vertical, en español."
    invented = {
        "kind": "How-To",
        "title": "Higiene de manos",
        "audience": "enfermeras nuevas",
        "lang": "Spanish",
        "format": "vertical",
        "style": "neon",
        "length": "about a minute",
        "source_text": "Wash your hands for twenty seconds with soap.",  # not in the message: dropped
        "source_url": "https://made-up.example/doc",  # not in the message: dropped
    }
    b = make_brief(msg, llm=ScriptedLLM(invented))
    assert (b.kind, b.lang, b.format, b.style, b.length) == ("how_to", "es", "9:16", None, None)
    assert b.source_text == "" and b.source_url is None and "content" in b.questions[0]
    # a model that fails falls back to the keyword reader
    assert make_brief("a 30 second explainer about phishing", llm=ScriptedLLM("not json")).kind == "explainer"


def test_brief_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from kinetry import service
    from kinetry.jobs import JobManager

    monkeypatch.delenv("KINETRY_LLM", raising=False)
    jm = JobManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(jm, "brief", lambda message, llm=None: heuristic_brief(message))
    service.set_job_manager(jm)
    monkeypatch.setenv("KINETRY_API_KEY", "k")
    c = TestClient(service.app)
    h = {"Authorization": "Bearer k"}
    kinds = c.get("/v1/kinds", headers=h).json()["kinds"]
    assert {k["id"] for k in kinds} == set(KINDS)
    r = c.post("/v1/briefs", json={"message": "a square onboarding video for new hires, 90 seconds"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["brief"]["kind"] == "onboarding" and body["brief"]["format"] == "1:1"
    assert Brief(**body["brief"]).to_request() == body["request"]
    assert c.post("/v1/briefs", json={"message": "x"}, headers=h).status_code == 422


def test_agent_tools_offer_brief_and_kind():
    pytest.importorskip("langchain_core")
    from kinetry.integrations.langchain import make_tools

    tools = {t.name: t for t in make_tools()}
    assert "brief_video" in tools and "kind" in tools["plan_video"].args and "kind" in tools["start_video"].args
    out = json.loads(tools["brief_video"].invoke({"message": "a 45 second announcement about the new canteen"}))
    assert out["brief"]["kind"] == "announcement"
