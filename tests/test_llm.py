"""Model choice and bring-your-own keys. No network: clients are constructed, never called."""

import json
import time
from pathlib import Path

import pytest

from kinetry import LLMConfig, Models, Settings, VideoPlan, make_llm
from kinetry.agents import Recorder, get_llm
from kinetry.design.plan import Design
from kinetry.design.planner import run_planner_v2
from kinetry.jobs import JobManager, check_llm, redact
from kinetry.llm import describe, invoke_structured

EX = Path(__file__).parent.parent / "examples" / "replay"
PLAN = json.loads((Path(__file__).parent.parent / "examples" / "plans" / "spot-the-phish.json").read_text())
KEY = "sk-test-0123456789abcdef"


# ---------------------------------------------------------------- specs and configs
def test_spec_parsing_keeps_bedrock_colons():
    c = LLMConfig.from_spec("bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert c.provider == "bedrock" and c.model == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert LLMConfig.from_spec("claude:claude-haiku-4-5-20251001").provider == "anthropic"
    assert LLMConfig.from_spec("openai").model == "gpt-4.1"  # provider default
    assert LLMConfig.from_spec("mistralai:mistral-large-latest").provider == "mistralai"


def test_keys_never_printed():
    c = LLMConfig("anthropic", "claude-sonnet-5-5", api_key=KEY, aws_secret_access_key="AWSSECRET")
    assert KEY not in repr(c) and KEY not in str(c.public()) and "AWSSECRET" not in repr(c)
    assert c.api_key.get_secret_value() == KEY


# ---------------------------------------------------------------- one client per provider
def test_anthropic_client():
    from langchain_anthropic import ChatAnthropic

    m = make_llm(LLMConfig("anthropic", "claude-sonnet-5-5", api_key=KEY), temperature=0.2)
    assert isinstance(m, ChatAnthropic) and m.model == "claude-sonnet-5-5"
    assert m.anthropic_api_key.get_secret_value() == KEY and m.temperature == 0.2


def test_openai_client_and_reasoning_models():
    from langchain_openai import ChatOpenAI

    m = make_llm(LLMConfig("openai", "gpt-4.1", api_key=KEY), temperature=0.3)
    assert isinstance(m, ChatOpenAI) and m.temperature == 0.3 and m.openai_api_key.get_secret_value() == KEY
    r = make_llm(LLMConfig("openai", "gpt-5", api_key=KEY), temperature=0.3)
    assert r.temperature in (None, 1, 1.0)  # reasoning models reject custom temperature


def test_openai_compatible_needs_endpoint():
    with pytest.raises(ValueError, match="base_url"):
        make_llm(LLMConfig("openai_compatible", "llama-3.3-70b", api_key=KEY))
    m = make_llm(LLMConfig("openai_compatible", "llama-3.3-70b", api_key=KEY, base_url="https://openrouter.ai/api/v1"))
    assert m.openai_api_base == "https://openrouter.ai/api/v1"


def test_bedrock_any_model_with_iam_keys_or_api_key():
    from langchain_aws import ChatBedrockConverse

    m = make_llm(
        LLMConfig(
            "bedrock",
            "amazon.nova-pro-v1:0",
            region="us-west-2",
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
        )
    )
    assert isinstance(m, ChatBedrockConverse) and m.model_id == "amazon.nova-pro-v1:0" and m.region_name == "us-west-2"
    m2 = make_llm(LLMConfig("bedrock", "meta.llama3-3-70b-instruct-v1:0", region="us-east-1", api_key=KEY))
    assert m2.bedrock_api_key.get_secret_value() == KEY


def test_google_and_azure_clients():
    from langchain_google_genai import ChatGoogleGenerativeAI

    g = make_llm(LLMConfig("google", "gemini-2.5-pro", api_key=KEY))
    assert isinstance(g, ChatGoogleGenerativeAI) and g.google_api_key.get_secret_value() == KEY
    with pytest.raises(ValueError, match="base_url"):
        make_llm(LLMConfig("azure", "my-deployment", api_key=KEY))
    a = make_llm(LLMConfig("azure", "my-deployment", api_key=KEY, base_url="https://x.openai.azure.com"))
    assert a.deployment_name == "my-deployment"


def test_missing_integration_package_says_what_to_install():
    with pytest.raises(RuntimeError, match="pip install"):
        make_llm(LLMConfig("fireworks", "accounts/fireworks/models/x", api_key=KEY))


# ---------------------------------------------------------------- defaults and roles
def test_settings_spec(monkeypatch):
    monkeypatch.setenv("KINETRY_LLM", "anthropic:claude-opus-5-5")
    monkeypatch.setenv("KINETRY_LLM_FAST", "anthropic:claude-haiku-4-5-20251001")
    s = Settings()
    assert s.llm_spec().spec == "anthropic:claude-opus-5-5"
    assert s.llm_spec("fast").spec == "anthropic:claude-haiku-4-5-20251001"
    monkeypatch.setenv("KINETRY_LLM", "bedrock")
    assert Settings().llm_spec().spec.startswith("bedrock:us.anthropic.claude-sonnet-4-5")


def test_models_per_role():
    main, fast = FakeModel(PLAN), FakeModel({"items": []})
    s = Settings()
    assert get_llm(s, Models(main, fast), role="fast") is fast
    assert get_llm(s, Models(main), role="fast") is main
    assert get_llm(s, main) is main
    assert "anthropic:claude-sonnet-5-5" in describe(Models("anthropic:claude-sonnet-5-5", "openai:gpt-4.1-mini"))


# ---------------------------------------------------------------- structured output without tool calling
class FakeModel:
    """Minimal chat model: optional tool support, answers with fixed JSON."""

    def __init__(self, payload, tools=True):
        self.payload, self.tools, self.calls = payload, tools, []

    def with_structured_output(self, schema):
        outer = self

        class R:
            def invoke(self, messages):
                if not outer.tools:
                    raise RuntimeError("ValidationException: This model doesn't support tool use.")
                outer.calls.append("tools")
                return outer.payload

        return R()

    def invoke(self, messages):
        self.calls.append("json")

        class Msg:
            text = "Here you go:\n```json\n" + json.dumps(self.payload) + "\n```"

        return Msg()


def test_structured_output_uses_tools_when_available():
    m = FakeModel(PLAN)
    assert isinstance(invoke_structured(m, VideoPlan, []), VideoPlan) and m.calls == ["tools"]


def test_structured_output_falls_back_to_json():
    m = FakeModel(PLAN, tools=False)
    assert isinstance(invoke_structured(m, VideoPlan, []), VideoPlan) and m.calls == ["json"]


def test_other_errors_are_not_swallowed():
    class Broken(FakeModel):
        def with_structured_output(self, schema):
            class R:
                def invoke(self, messages):
                    raise RuntimeError("AccessDeniedException: no access to model")

            return R()

    with pytest.raises(RuntimeError, match="AccessDenied"):
        invoke_structured(Broken(PLAN), VideoPlan, [])


def test_planner_runs_on_a_model_without_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("KINETRY_LLM", "bedrock")
    s = Settings()
    design = Design(style="minimal", format="9:16")
    plan = run_planner_v2(
        "some lesson text " * 5, {"length": "50s"}, design, s, Recorder(tmp_path, s), llm=FakeModel(PLAN, tools=False)
    )
    assert plan.scenes[0].type == "title" and (tmp_path / "llm" / "plan.json").exists()
    # the director's design wins over whatever the model wrote, and layouts fit the format
    assert plan.design.style == "minimal" and plan.scenes[1].layout == "stack"


def test_planner_sends_catalog_errors_back(tmp_path, monkeypatch):
    monkeypatch.setenv("KINETRY_LLM", "bedrock")
    s = Settings()
    bad = json.loads(json.dumps(PLAN))
    bad["scenes"][1]["data"]["callouts"][0]["target"] = "nowhere"

    class Seq(FakeModel):
        def invoke(self, messages):
            self.payload = bad if not self.calls else PLAN
            self.seen = json.dumps(messages, default=str)
            return super().invoke(messages)

    m = Seq(PLAN, tools=False)
    plan = run_planner_v2("text " * 20, {"length": "50s"}, Design(style="technical"), s, None, llm=m)
    assert m.calls == ["json", "json"] and "target" in m.seen and plan.scenes[1].type == "annotated_mock"


# ---------------------------------------------------------------- service policy
def test_policy_byok_default():
    with pytest.raises(ValueError, match="own api_key"):
        check_llm({"provider": "openai", "model": "gpt-4.1"}, mode="byok")
    cfg = check_llm({"provider": "openai", "model": "gpt-4.1", "api_key": KEY}, mode="byok")
    assert cfg.api_key.get_secret_value() == KEY
    assert check_llm({"provider": "bedrock", "model": "amazon.nova-pro-v1:0"}, mode="any").provider == "bedrock"


def test_policy_limits():
    ok = {"provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": KEY}
    with pytest.raises(ValueError, match="off"):
        check_llm(ok, mode="off")
    with pytest.raises(ValueError, match="isn't enabled"):
        check_llm(ok, mode="byok", providers="openai,bedrock")
    with pytest.raises(ValueError, match="non-public"):
        check_llm(
            {"provider": "openai_compatible", "model": "x", "api_key": KEY, "base_url": "http://127.0.0.1:11434/v1"}
        )
    with pytest.raises(ValueError, match="aws_profile"):
        check_llm({"provider": "bedrock", "model": "x", "aws_profile": "prod"}, mode="any")


def test_redact():
    cfg = LLMConfig("openai", "gpt-4.1", api_key=KEY)
    assert redact(f"401: Incorrect API key provided: {KEY}", cfg) == "401: Incorrect API key provided: ***"


def test_keys_reach_the_job_but_never_disk(tmp_path, monkeypatch):
    from test_integration import FakeKinetry

    monkeypatch.setenv("KINETRY_CLIENT_LLM", "byok")
    jm = JobManager(FakeKinetry(tmp_path), data_dir=tmp_path / "data", allow_private_urls=True)
    from fastapi.testclient import TestClient

    from kinetry import service

    service.set_job_manager(jm)
    monkeypatch.delenv("KINETRY_API_KEY", raising=False)
    c = TestClient(service.app)
    llm = {"provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": KEY}
    r = c.post("/v1/videos", json={"plan": PLAN, "llm": llm})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    for _ in range(100):
        st = c.get(f"/v1/videos/{jid}").json()
        if st["status"] == "done":
            break
        time.sleep(0.05)
    used = jm.tf.calls[-1]["llm"]
    assert used.api_key.get_secret_value() == KEY  # the run got the caller's key ...
    assert st["llm"] == {"provider": "anthropic", "model": "claude-sonnet-5-5", "base_url": None, "region": None}
    stored = "".join(p.read_text(errors="ignore") for p in (tmp_path / "data").rglob("*.json"))
    assert KEY not in stored and KEY not in r.text and KEY not in json.dumps(st)  # ... and nothing kept it
    bad = c.post("/v1/videos", json={"plan": PLAN, "llm": {"provider": "openai", "model": "gpt-4.1"}})
    assert bad.status_code == 400 and "api_key" in bad.json()["detail"]


# ---------------------------------------------------------------- cloud voices with your own key
def _wav(seconds: float, rate: int = 24000, streamed: bool = False) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))
    data = bytearray(buf.getvalue())
    if streamed:  # what chunked TTS responses look like: placeholder sizes
        data[4:8] = b"\xff\xff\xff\xff"
        i = data.find(b"data")
        data[i + 4 : i + 8] = b"\xff\xff\xff\xff"
    return bytes(data)


def test_openai_voice(tmp_path):
    import httpx

    from kinetry.voice import OpenAITTSProvider

    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=_wav(1.5, streamed=True))

    client = httpx.Client(
        base_url="https://api.openai.com/v1",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": f"Bearer {KEY}"},
    )
    clip = OpenAITTSProvider("coral", client=client).synthesize("Hello there.", tmp_path / "o.wav")
    assert clip.duration == pytest.approx(1.5, abs=0.01)  # streamed header repaired
    assert seen["body"]["voice"] == "coral" and seen["body"]["response_format"] == "wav"
    assert seen["auth"] == f"Bearer {KEY}"


def test_elevenlabs_voice_pcm_to_wav(tmp_path):
    import httpx

    from kinetry.voice import ElevenLabsProvider

    def handler(req: httpx.Request):
        assert req.url.path == "/v1/text-to-speech/v123" and req.url.params["output_format"] == "pcm_24000"
        return httpx.Response(200, content=b"\0\0" * 24000 * 2)  # 2 s of raw PCM

    client = httpx.Client(base_url="https://api.elevenlabs.io", transport=httpx.MockTransport(handler))
    clip = ElevenLabsProvider("v123", client=client).synthesize("Hi.", tmp_path / "e.wav")
    assert clip.duration == pytest.approx(2.0, abs=0.01)


def test_cloud_voice_needs_a_key(monkeypatch):
    from kinetry.jobs import check_voice
    from kinetry.voice import build_voice

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        build_voice("openai:coral", Settings())
    with pytest.raises(ValueError, match="voice_api_key"):
        check_voice("elevenlabs:v123", mode="byok")
    assert check_voice("elevenlabs:v123", "k", mode="byok") and check_voice("openai:coral", mode="any")
    monkeypatch.setenv("KINETRY_VOICE_PROVIDERS", "kokoro")
    with pytest.raises(ValueError, match="must start"):
        check_voice("voicestudio:p1")


def test_clone_endpoint_is_off_by_default(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from kinetry import service
    from test_integration import FakeKinetry

    service.set_job_manager(JobManager(FakeKinetry(tmp_path), data_dir=tmp_path / "d", allow_private_urls=True))
    monkeypatch.delenv("KINETRY_API_KEY", raising=False)
    monkeypatch.delenv("KINETRY_VOICE_CLONING", raising=False)
    c = TestClient(service.app)
    files = {"ref_audio": ("r.wav", _wav(3)), "consent_audio": ("c.wav", _wav(2))}
    form = {"name": "Dana", "consent_text": "I, Dana Lee, agree to my voice being used for training videos."}
    assert c.post("/v1/voices/clone", data=form, files=files).status_code == 403
