"""LangChain tools, for agent platforms built on LangChain/LangGraph.

    from kinetry.integrations.langchain import make_tools
    tools = make_tools()                      # or make_tools(JobManager(Kinetry(llm=my_llm)))
    agent = create_agent(model, tools)

Video rendering takes minutes, so the agent starts a job and checks on it;
`generate_video_blocking` is there for simple scripts and batch pipelines.
"""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from ..design.catalog import load_catalog
from ..jobs import JobManager, check_design
from ..kinds import kinds_guide
from ..sources import Source


def make_tools(jobs: JobManager | None = None, *, include_blocking: bool = False) -> list[StructuredTool]:
    jm = jobs or JobManager()

    def create_brand(url: str) -> str:
        """Capture a company's brand (colors, fonts, logo) from its public website; returns a brand_id to reuse."""
        info = jm.create_brand(url)
        return json.dumps({"brand_id": info["brand_id"], "accent": info["kit"]["accent"], "logo": info["logo"]})

    def list_design_options() -> str:
        """Styles, formats, transitions and scene types available; use them to pin a look in plan/start."""
        d = load_catalog().to_dict()
        return json.dumps(
            {
                "styles": {k: v["description"] for k, v in d["styles"].items()},
                "formats": d["formats"],
                "scene_types": {k: v["purpose"] for k, v in d["components"].items()},
                "video_kinds": kinds_guide(),
            }
        )

    def brief_video(message: str) -> str:
        """Turn a video request in plain words into a structured brief (kind, audience, length, language, format,
        pasted source text) plus questions for anything missing, before planning or starting a video."""
        b = jm.brief(message)
        return json.dumps({"brief": b.model_dump(), "request": b.to_request()}, ensure_ascii=False)

    def plan_video(
        text: str,
        title: str = "",
        style: str = "",
        format: str = "",
        brand_id: str = "",
        effects: str = "",
        kind: str = "",
    ) -> str:
        """Draft a narrated video plan (look, scenes, narration, on-screen text) from learning content.
        style/format are optional pins; empty = chosen automatically. brand_id: plan within that brand's
        colors and standing preferences. effects: optional motion layers, "subtle" or "rich".
        kind: lesson, course_summary, session_recap, explainer, how_to, announcement or onboarding (optional)."""
        design = check_design(_design(style, format, effects))
        src = Source(text=text, title=title, kind=kind or None)
        return jm.plan(src, brand_id=brand_id or None, design=design).model_dump_json()

    def start_video(
        text: str,
        title: str = "",
        brand_id: str = "",
        voice: str = "",
        style: str = "",
        format: str = "",
        effects: str = "",
        quality: str = "",
        kind: str = "",
    ) -> str:
        """Start rendering a narrated, on-brand video from learning content. Returns a job_id to check later.
        style/format optionally pin the look (see list_design_options); quality: draft | standard | high.
        kind: what the video is for, e.g. lesson, session_recap, how_to (see list_design_options)."""
        design = _design(style, format, effects) or None
        job = jm.start(
            source=Source(text=text, title=title, kind=kind or None),
            brand_id=brand_id or None,
            voice=voice or None,
            design=design,
            quality=quality or None,
        )
        return json.dumps({"job_id": job["job_id"], "status": job["status"]})

    def video_status(job_id: str) -> str:
        """Check a video job: queued, running, done (with video path), needs_review or error."""
        j = jm.get(job_id)
        return json.dumps({k: j.get(k) for k in ("job_id", "status", "step", "video", "duration", "error")})

    def generate_video_blocking(text: str, title: str = "", brand_id: str = "") -> str:
        """Render a video and wait for it (several minutes). Returns the final job record."""
        job = jm.start(source=Source(text=text, title=title), brand_id=brand_id or None)
        return json.dumps(jm.wait(job["job_id"]), default=str)

    fns = [create_brand, list_design_options, brief_video, plan_video, start_video, video_status] + (
        [generate_video_blocking] if include_blocking else []
    )
    return [StructuredTool.from_function(f) for f in fns]


def _design(style: str = "", format: str = "", effects: str = "") -> dict:
    d = {k: v for k, v in (("style", style), ("format", format)) if v}
    if effects:
        d["effects"] = {"level": effects}
    return d
