"""Integration surfaces (API, jobs, HTTP service, MCP, LangChain) with the render pipeline faked out,
so these run without Node/Chrome. The real pipeline is exercised by the render-smoke workflow."""

import asyncio
import json
import time
from pathlib import Path

import pytest

from kinetry import BrandPack, Kinetry, Source, load_plan
from kinetry.api import Result
from kinetry.branding import DEFAULT_KIT
from kinetry.jobs import JobManager, check_public_url, check_voice

EX = Path(__file__).parent.parent / "examples" / "replay"
PLAN = json.loads((EX / "run-the-room-fernhill" / "plan.json").read_text())


class FakeKinetry(Kinetry):
    """Real API surface, fake render."""

    def __init__(self, tmp: Path):
        super().__init__(workdir=tmp / "runs", replay_dir=EX / "run-the-room-fernhill")
        self.calls = []

    def _run(self, *, source, plan, brand, out, voice, run_dir, use_logo, qa_frames, on_event, llm=None, **kw):
        self.calls.append({"source": source, "plan": plan, "brand": brand, "voice": voice, "llm": llm, **kw})
        rd = self._run_dir(run_dir)
        if on_event:
            on_event({"step": "render"})
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"fake-mp4")
        (rd / "qa").mkdir(exist_ok=True)
        (rd / "qa" / "frame-00-at-1s.png").write_bytes(b"png")
        return Result("done", Path(out), rd, 12.5, plan or load_plan(PLAN), None, [])

    def brand(self, source, *, use_logo=True, run_dir=None, llm=None):
        return BrandPack(DEFAULT_KIT.model_copy(update={"name": "Fake"}), ("logo.svg", b"<svg/>"), ["fake"])


@pytest.fixture
def jm(tmp_path):
    return JobManager(FakeKinetry(tmp_path), data_dir=tmp_path / "data", allow_private_urls=True)


# ---------------------------------------------------------------- API
def test_plan_from_replay(tmp_path):
    tf = Kinetry(workdir=tmp_path, replay_dir=EX / "run-the-room-fernhill")
    plan = tf.plan(Source(text="Open by saying why you called the meeting. " * 3, title="Run the room"))
    assert plan.scenes[0].type == "title" and plan.word_count() > 100
    # a recorded v1 plan comes back as v2 in the classic look, with every layout picked
    assert plan.version == 2 and plan.design.style == "classic" and all(s.layout for s in plan.scenes)


def test_brand_from_replay_and_pack_roundtrip(tmp_path):
    tf = Kinetry(workdir=tmp_path, replay_dir=EX / "run-the-room-fernhill")
    pack = tf.brand(Path(__file__).parent / "fixtures" / "fernhill-probe.json")
    assert pack.kit.name == "Fernhill Academy" and pack.logo and pack.logo[0] == "logo.svg"
    pack.save(tmp_path / "pack")
    again = BrandPack.load(tmp_path / "pack")
    assert again.kit == pack.kit and again.logo == pack.logo


def test_default_brand_is_contrast_safe(tmp_path):
    tf = Kinetry(workdir=tmp_path)
    pack = tf.brand(None)
    assert pack.kit.name == "Kinetry default" and pack.notes == []


# ---------------------------------------------------------------- jobs
def test_job_lifecycle(jm):
    job = jm.start(source=Source(text="x" * 40), voice="kokoro:am_michael", metadata={"course": "c1"})
    done = jm.wait(job["job_id"], timeout=10, poll=0.05)
    assert done["status"] == "done" and done["metadata"] == {"course": "c1"}
    assert jm.video_path(job["job_id"]).read_bytes() == b"fake-mp4"
    assert jm.frame_path(job["job_id"], 0).name.startswith("frame-")


def test_job_with_plan_and_brand(jm):
    b = jm.create_brand("https://fernhill.example")
    job = jm.start(plan=PLAN, brand_id=b["brand_id"])
    jm.wait(job["job_id"], timeout=10, poll=0.05)
    call = jm.tf.calls[-1]
    assert call["plan"] is not None and call["brand"].endswith(b["brand_id"])


def test_job_validation(jm):
    with pytest.raises(ValueError):
        jm.start(source=Source(text="x" * 40), plan=PLAN)
    with pytest.raises(ValueError):
        jm.start(source=Source(text="x" * 40), voice="file:/etc/passwd")
    with pytest.raises(KeyError):
        jm.start(source=Source(text="x" * 40), brand_id="doesnotexist")
    with pytest.raises(ValueError):
        jm.get("../../etc")


def test_url_guard():
    with pytest.raises(ValueError):
        check_public_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        check_public_url("http://127.0.0.1:8080/admin")
    with pytest.raises(ValueError):
        check_public_url("http://169.254.169.254/latest/meta-data")
    assert check_public_url("http://localhost:3000", allow_private=True)
    assert check_voice(None) is None


def test_restart_marks_running_jobs_interrupted(tmp_path):
    d = tmp_path / "data" / "jobs" / "abc123"
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"job_id": "abc123", "status": "running"}))
    jm2 = JobManager(FakeKinetry(tmp_path), data_dir=tmp_path / "data")
    assert jm2.get("abc123")["status"] == "interrupted"


# ---------------------------------------------------------------- HTTP service
def test_http_service(jm, monkeypatch):
    from fastapi.testclient import TestClient

    from kinetry import service

    service.set_job_manager(jm)
    monkeypatch.setenv("KINETRY_API_KEY", "s3cret")
    c = TestClient(service.app)
    assert c.get("/health").json()["ok"]
    assert c.post("/v1/videos", json={"source": {"text": "x" * 40}}).status_code == 401
    h = {"Authorization": "Bearer s3cret"}
    b = c.post("/v1/brands", json={"url": "https://fernhill.example"}, headers=h).json()
    r = c.post("/v1/videos", json={"plan": PLAN, "brand_id": b["brand_id"], "metadata": {"session": 2}}, headers=h)
    assert r.status_code == 202
    jid = r.json()["job_id"]
    for _ in range(100):
        st = c.get(f"/v1/videos/{jid}", headers=h).json()
        if st["status"] == "done":
            break
        time.sleep(0.05)
    assert st["status"] == "done" and "video" not in st and st["video_url"].endswith("/video")
    assert c.get(st["video_url"], headers=h).content == b"fake-mp4"
    assert c.get(st["frame_urls"][0], headers=h).status_code == 200
    assert c.get("/v1/videos/nope", headers=h).status_code == 404
    assert c.post("/v1/videos", json={"source": {"text": "x" * 40}, "voice": "evil:x"}, headers=h).status_code == 400


# ---------------------------------------------------------------- MCP + LangChain
def test_mcp_server_tools(jm):
    from kinetry.integrations.mcp_server import build_server

    server = build_server(jm)
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in (tools.tools if hasattr(tools, "tools") else tools)}
    assert names == {"create_brand", "brief_video", "plan_video", "start_video", "video_status", "list_design_options"}


def test_langchain_tools(jm):
    from kinetry.integrations.langchain import make_tools

    tools = {t.name: t for t in make_tools(jm, include_blocking=True)}
    assert set(tools) == {
        "create_brand",
        "brief_video",
        "plan_video",
        "start_video",
        "video_status",
        "generate_video_blocking",
        "list_design_options",
    }
    opts = json.loads(tools["list_design_options"].invoke({}))
    assert "editorial" in json.dumps(opts) and "dialogue" in json.dumps(opts)
    started = json.loads(
        tools["start_video"].invoke({"text": "x" * 40, "title": "t", "style": "warm", "format": "9:16"})
    )
    jm.wait(started["job_id"], timeout=10, poll=0.05)
    assert jm.tf.calls[-1]["design"] == {"style": "warm", "format": "9:16"}
    status = json.loads(tools["video_status"].invoke({"job_id": started["job_id"]}))
    assert status["status"] == "done"


def test_http_catalog_and_profile(jm, monkeypatch):
    from fastapi.testclient import TestClient

    from kinetry import service

    service.set_job_manager(jm)
    monkeypatch.delenv("KINETRY_API_KEY", raising=False)
    c = TestClient(service.app)
    cat = c.get("/v1/catalog").json()
    assert "dialogue" in json.dumps(cat) and "editorial" in json.dumps(cat)
    b = c.post("/v1/brands", json={"url": "https://fernhill.example"}).json()
    r = c.put(f"/v1/brands/{b['brand_id']}/profile", json={"styles": ["warm"], "format": "9:16"})
    assert r.status_code == 200 and r.json()["profile"]["format"] == "9:16"
    assert c.put(f"/v1/brands/{b['brand_id']}/profile", json={"music": "/etc/passwd"}).status_code == 400
    bad = c.post("/v1/videos", json={"source": {"text": "x" * 40}, "design": {"style": "nope"}})
    assert bad.status_code == 400
    ok = c.post(
        "/v1/videos", json={"source": {"text": "x" * 40}, "brand_id": b["brand_id"], "design": {"style": "bold"}}
    )
    assert ok.status_code == 202


def test_cli_catalog(capsys):
    from kinetry.cli import main

    assert main(["catalog", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["combinations"]["scene_renderings"] >= 800
