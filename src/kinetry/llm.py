"""Choose the LLM: any provider, any model, your own key.

A model is a spec string "provider:model", e.g.

    anthropic:claude-sonnet-5-5
    openai:gpt-4.1
    bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0     (any Bedrock model or inference profile)
    bedrock:amazon.nova-pro-v1:0
    google:gemini-2.5-pro
    azure:my-gpt-deployment                                  (+ base_url, api_version)
    openai_compatible:llama-3.3-70b                          (+ base_url: OpenRouter, Groq, Together, vLLM, Ollama...)
    mistralai:mistral-large-latest | groq:... | ollama:... | xai:... | deepseek:...  (any LangChain provider)

Keys come from the caller (`LLMConfig(api_key=...)`) or the provider's usual environment
variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, the AWS credential chain...).
Keys are held as SecretStr and never written to logs, run reports or job records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlparse

from pydantic import SecretStr

# friendly name -> (LangChain init_chat_model provider, pip extra, key env var, default model)
PROVIDERS: dict[str, tuple[str, str, str | None, str]] = {
    "anthropic": ("anthropic", "anthropic", "ANTHROPIC_API_KEY", "claude-sonnet-5-5"),
    "openai": ("openai", "openai", "OPENAI_API_KEY", "gpt-4.1"),
    "azure": ("azure_openai", "openai", "AZURE_OPENAI_API_KEY", ""),
    "openai_compatible": ("openai", "openai", "OPENAI_API_KEY", ""),
    "bedrock": ("bedrock_converse", "bedrock", None, "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    "google": ("google_genai", "google", "GOOGLE_API_KEY", "gemini-2.5-pro"),
}
ALIASES = {
    "claude": "anthropic",
    "gemini": "google",
    "google_genai": "google",
    "azure_openai": "azure",
    "bedrock_converse": "bedrock",
    "aws": "bedrock",
}
KEY_KWARG = {"anthropic": "api_key", "openai": "api_key", "azure_openai": "api_key", "google_genai": "google_api_key"}

# OpenAI reasoning models only accept the default temperature.
_FIXED_TEMPERATURE = re.compile(r"^(o\d|gpt-5)", re.I)


def _canonical(provider: str) -> str:
    p = provider.strip().lower().replace("-", "_")
    return ALIASES.get(p, p)


@dataclass
class LLMConfig:
    provider: str = "bedrock"
    model: str = ""
    api_key: SecretStr | None = None
    base_url: str | None = None  # openai_compatible / azure endpoint / self-hosted gateway
    api_version: str | None = None  # azure
    region: str | None = None  # bedrock
    aws_profile: str | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None
    max_tokens: int = 8000
    extra: dict[str, Any] = field(default_factory=dict)  # passed through to the LangChain model
    # set by the service for a caller's endpoint: connect only to the public address that was checked
    public_only: bool = False

    def __post_init__(self):
        self.provider = _canonical(self.provider)
        for f in ("api_key", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
            v = getattr(self, f)
            if isinstance(v, str):
                setattr(self, f, SecretStr(v) if v else None)
        if not self.model and self.provider in PROVIDERS:
            self.model = PROVIDERS[self.provider][3]

    @classmethod
    def from_spec(cls, spec: str, **kw) -> LLMConfig:
        """'anthropic:claude-sonnet-5-5' -> LLMConfig. Bedrock ids may contain ':' (…-v1:0)."""
        provider, sep, model = spec.partition(":")
        if not sep:
            provider, model = spec, ""
        return cls(provider=provider, model=model, **kw)

    @property
    def spec(self) -> str:
        return f"{self.provider}:{self.model}"

    def public(self) -> dict:
        """Safe to log or store: no secrets."""
        base = None
        if self.base_url:  # no credentials or query strings in records
            u = urlparse(self.base_url)
            base = f"{u.scheme}://{u.hostname or ''}{f':{u.port}' if u.port else ''}{u.path}"
        return {"provider": self.provider, "model": self.model, "base_url": base, "region": self.region}

    def __repr__(self) -> str:  # never print keys
        return f"LLMConfig({self.spec!r})"


def make_llm(cfg: LLMConfig | str, *, temperature: float | None = 0.3):
    """Build a LangChain chat model for any supported provider."""
    if isinstance(cfg, str):
        cfg = LLMConfig.from_spec(cfg)
    if not cfg.model:
        raise ValueError(f"no model given for provider '{cfg.provider}' (use '{cfg.provider}:<model>')")
    from langchain.chat_models import init_chat_model

    provider = PROVIDERS[cfg.provider][0] if cfg.provider in PROVIDERS else cfg.provider
    kw: dict[str, Any] = {"max_tokens": cfg.max_tokens}
    if temperature is not None and not (provider in ("openai", "azure_openai") and _FIXED_TEMPERATURE.match(cfg.model)):
        kw["temperature"] = temperature
    key = cfg.api_key.get_secret_value() if cfg.api_key else None

    if provider == "bedrock_converse":
        kw["region_name"] = cfg.region or _aws_region()
        if key:  # Amazon Bedrock API key (bearer token) instead of IAM credentials
            kw["bedrock_api_key"] = key
        if cfg.aws_profile:
            kw["credentials_profile_name"] = cfg.aws_profile
        if cfg.aws_access_key_id and cfg.aws_secret_access_key:
            kw["aws_access_key_id"] = cfg.aws_access_key_id
            kw["aws_secret_access_key"] = cfg.aws_secret_access_key
            if cfg.aws_session_token:
                kw["aws_session_token"] = cfg.aws_session_token
    elif provider == "azure_openai":
        if not cfg.base_url:
            raise ValueError("azure needs base_url (your https://<resource>.openai.azure.com endpoint)")
        kw.update(azure_endpoint=cfg.base_url, azure_deployment=cfg.model, api_version=cfg.api_version or "2024-10-21")
        kw["http_client"] = _no_redirects(cfg.public_only)
        if key:
            kw["api_key"] = key
    else:
        if cfg.provider == "openai_compatible" and not cfg.base_url:
            raise ValueError("openai_compatible needs base_url (e.g. https://openrouter.ai/api/v1)")
        if cfg.base_url:
            kw["base_url"] = cfg.base_url
            if provider == "openai":  # a custom endpoint must not bounce requests (with the key) elsewhere
                kw["http_client"] = _no_redirects(cfg.public_only)
        if key:
            kw[KEY_KWARG.get(provider, "api_key")] = key
    kw.update(cfg.extra)
    try:
        return init_chat_model(cfg.model, model_provider=provider, **kw)
    except ImportError as e:
        extra = PROVIDERS.get(cfg.provider, (None, cfg.provider))[1]
        raise RuntimeError(f"provider '{cfg.provider}' needs: pip install 'kinetry[{extra}]' ({e})") from e


def _no_redirects(public_only: bool = False):
    import httpx

    from .netguard import client

    return client(public_only, follow_redirects=False, timeout=httpx.Timeout(600.0, connect=10.0))


def _aws_region() -> str:
    import os

    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def with_overrides(cfg: LLMConfig, **kw) -> LLMConfig:
    return replace(cfg, **{k: v for k, v in kw.items() if v is not None})


# ---------------------------------------------------------------- choosing a model per step
LLMLike = Any  # a LangChain chat model, an LLMConfig, a "provider:model" spec, or None (use settings)


@dataclass
class Models:
    """Different models per step. `main` writes plans and brand kits; `fast` (optional) does
    the small copy rewrites in the fit loop, where a cheaper model is plenty."""

    main: LLMLike = None
    fast: LLMLike = None

    def pick(self, role: str) -> LLMLike:
        return self.fast if role == "fast" and self.fast is not None else self.main


def describe(llm: LLMLike) -> str:
    """Human/audit label for any LLM argument; never includes secrets."""
    if isinstance(llm, Models):
        return describe(llm.main) + (f" (fast: {describe(llm.fast)})" if llm.fast is not None else "")
    if isinstance(llm, LLMConfig):
        return llm.spec
    if isinstance(llm, str):
        return llm
    if llm is None:
        return "default"
    name = getattr(llm, "model_id", None) or getattr(llm, "model_name", None) or getattr(llm, "model", None)
    return f"{type(llm).__name__}({name})" if name else type(llm).__name__


def resolve(llm: LLMLike, default_spec: str | LLMConfig, *, role: str = "main", temperature: float | None = 0.3):
    """Turn whatever the caller gave us into a chat model."""
    if isinstance(llm, Models):
        llm = llm.pick(role)
    if llm is None:
        llm = default_spec
    if isinstance(llm, (str, LLMConfig)):
        return make_llm(llm, temperature=temperature)
    return llm  # already a LangChain chat model


# ---------------------------------------------------------------- structured output on any model
_TOOLS_UNSUPPORTED = re.compile(
    r"(does ?n.t support|not support(ed)?|unsupported).{0,40}(tool|function)|toolConfig|tool_choice|"
    r"tool use is not|function calling is not",
    re.I | re.S,
)


def invoke_structured(llm, schema, messages: list, *, json_mode: bool = False):
    """`llm.with_structured_output(schema).invoke(messages)`, falling back to a JSON-schema prompt
    for models without tool calling (some Bedrock, Ollama and gateway models)."""
    if not json_mode:
        try:
            runnable = llm.with_structured_output(schema)
        except NotImplementedError:
            runnable = None
        if runnable is not None:
            try:
                out = runnable.invoke(messages)
                if out is not None:
                    return schema.model_validate(out) if isinstance(out, dict) else out
            except Exception as e:  # noqa: BLE001
                if not _TOOLS_UNSUPPORTED.search(str(e)):
                    raise
    return _json_fallback(llm, schema, messages)


def _json_fallback(llm, schema, messages: list):
    import json

    instr = (
        "Respond with a single JSON object, and nothing else, that validates against this JSON Schema:\n"
        + json.dumps(schema.model_json_schema())
    )
    msg = llm.invoke([*messages, {"role": "user", "content": instr}])
    text = getattr(msg, "text", msg)
    text = text() if callable(text) else text
    if not isinstance(text, str):
        text = str(getattr(msg, "content", msg))
    return schema.model_validate_json(_extract_json(text))


def _extract_json(text: str) -> str:
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"model returned no JSON object: {text[:200]!r}")
    return t[start : end + 1]


# ---------------------------------------------------------------- model discovery
def list_models(cfg: LLMConfig | str, timeout: float = 20.0) -> list[dict]:
    """Models the given credentials can use, for pickers in a UI or `kinetry models`."""
    import os

    import httpx

    if isinstance(cfg, str):
        cfg = LLMConfig(provider=cfg)
    p = cfg.provider
    key = cfg.api_key.get_secret_value() if cfg.api_key else None
    if p == "bedrock":
        return _bedrock_models(cfg)
    if p == "anthropic":
        key = key or os.environ.get("ANTHROPIC_API_KEY")
        r = httpx.get(
            "https://api.anthropic.com/v1/models",
            params={"limit": 100},
            timeout=timeout,
            headers={"x-api-key": key or "", "anthropic-version": "2023-06-01"},
        )
        r.raise_for_status()
        return [{"id": m["id"], "name": m.get("display_name", m["id"])} for m in r.json()["data"]]
    if p in ("openai", "openai_compatible"):
        key = key or (None if cfg.base_url else os.environ.get("OPENAI_API_KEY"))  # never send ours elsewhere
        base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        from .netguard import client

        with client(cfg.public_only and bool(cfg.base_url), timeout=timeout) as c:  # a caller's endpoint: pinned
            r = c.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"} if key else {})
        r.raise_for_status()
        ids = sorted(m["id"] for m in r.json()["data"])
        if p == "openai":
            ids = [
                i
                for i in ids
                if re.match(r"^(gpt-|o\d|chatgpt)", i)
                and not re.search(r"audio|realtime|tts|transcribe|image|search", i)
            ]
        return [{"id": i, "name": i} for i in ids]
    if p == "google":
        key = key or os.environ.get("GOOGLE_API_KEY")
        r = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"pageSize": 200},
            headers={"x-goog-api-key": key or ""},
            timeout=timeout,
        )
        r.raise_for_status()
        return [
            {"id": m["name"].removeprefix("models/"), "name": m.get("displayName", m["name"])}
            for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
    raise ValueError(f"model listing isn't available for '{p}'; pass the model name directly")


def _bedrock_models(cfg: LLMConfig) -> list[dict]:
    import boto3

    session = boto3.Session(
        profile_name=cfg.aws_profile,
        aws_access_key_id=cfg.aws_access_key_id.get_secret_value() if cfg.aws_access_key_id else None,
        aws_secret_access_key=cfg.aws_secret_access_key.get_secret_value() if cfg.aws_secret_access_key else None,
        aws_session_token=cfg.aws_session_token.get_secret_value() if cfg.aws_session_token else None,
        region_name=cfg.region or _aws_region(),
    )
    br = session.client("bedrock")
    out = []
    for m in br.list_foundation_models(byOutputModality="TEXT")["modelSummaries"]:
        if (
            "ON_DEMAND" in m.get("inferenceTypesSupported", [])
            and m.get("modelLifecycle", {}).get("status") != "LEGACY"
        ):
            out.append({"id": m["modelId"], "name": f"{m['providerName']} {m['modelName']}", "type": "on-demand"})
    # Newer models are only callable through (cross-region) inference profiles.
    for p in br.list_inference_profiles(maxResults=1000).get("inferenceProfileSummaries", []):
        out.append({"id": p["inferenceProfileId"], "name": p["inferenceProfileName"], "type": "inference-profile"})
    return out
