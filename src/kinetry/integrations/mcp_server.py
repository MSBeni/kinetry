"""MCP server: lets any MCP client (Claude, Cursor, internal agent platforms) make videos.

    kinetry mcp                       # stdio
    kinetry-mcp --http --port 8765    # streamable HTTP (python -m kinetry.integrations.mcp_server --http)

Rendering takes minutes, so video tools are start + poll.
"""

from __future__ import annotations

import argparse
import json

from .. import __version__
from ..design.catalog import load_catalog
from ..jobs import JobManager, check_design
from ..kinds import kinds_guide
from ..sources import Source

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server


def build_server(jobs: JobManager | None = None):
    jm = jobs or JobManager()
    instructions = (
        "Create short narrated, on-brand videos from learning content. "
        "Typical flow: create_brand(url) once per client -> start_video(text, brand_id) -> poll video_status(job_id). "
        "For a request in plain words, brief_video(message) turns it into kind, audience, length and look first. "
        "The look is chosen automatically; list_design_options shows the styles, formats and scene types you can pin."
    )
    try:
        server = _Server("kinetry", instructions=instructions, version=__version__)
    except TypeError:  # mcp 1.x FastMCP has no version argument
        server = _Server("kinetry", instructions=instructions)

    @server.tool()
    def create_brand(url: str, use_logo: bool = True) -> dict:
        """Capture a company's brand (colors, fonts, logo) from its public website. Takes ~30-90 s.
        Returns a brand_id to reuse for every video for that company."""
        return jm.create_brand(url, use_logo)

    @server.tool()
    def list_design_options() -> dict:
        """Styles, formats, transitions and scene types the engine can render, with what each is for."""
        cat = load_catalog()
        d = cat.to_dict()
        return {
            "styles": d["styles"],
            "formats": d["formats"],
            "transitions": d["transitions"],
            "scene_types": {k: v["purpose"] for k, v in d["components"].items()},
            "video_kinds": kinds_guide(),
            "combinations": cat.combinations(),
        }

    @server.tool()
    def brief_video(message: str) -> dict:
        """Turn a video request in plain words ("a 60-second vertical recap of today's session for the sales
        team, in Spanish: <notes>") into a structured brief: kind, audience, length, language, format, the source
        text if it was pasted, and questions for anything missing. `request` is ready for plan_video/start_video
        once it has source text."""
        b = jm.brief(message)
        return {"brief": b.model_dump(), "request": b.to_request()}

    @server.tool()
    def plan_video(
        text: str,
        title: str = "",
        context_json: str = "{}",
        style: str = "",
        format: str = "",
        brand_id: str = "",
        effects: str = "",
        kind: str = "",
    ) -> dict:
        """Draft the video plan (look, scenes, narration, on-screen text) from source text, for review before
        rendering. context_json: extra facts, e.g. {"audience": "new managers", "length": "60s"}.
        style / format: optional pins (see list_design_options); empty = chosen automatically.
        brand_id: plan within that brand's colors and standing preferences (recommended).
        effects: optional motion layers, "subtle" or "rich" (camera moves, kinetic type, ambient light).
        kind: what the video is for (lesson, course_summary, session_recap, explainer, how_to, announcement,
        onboarding); shapes its structure and default length."""
        design = check_design(_design(style, format, effects))
        src = Source(text=text, title=title, kind=kind or None, context=json.loads(context_json or "{}"))
        return jm.plan(src, brand_id=brand_id or None, design=design).model_dump()

    @server.tool()
    def start_video(
        text: str = "",
        title: str = "",
        plan_json: str = "",
        brand_id: str = "",
        brand_url: str = "",
        voice: str = "",
        context_json: str = "{}",
        style: str = "",
        format: str = "",
        effects: str = "",
        quality: str = "",
        kind: str = "",
    ) -> dict:
        """Start rendering a video from source text OR a reviewed plan (plan_json). Brand by brand_id (preferred)
        or brand_url. style / format optionally pin the look. quality: draft | standard (default) | high.
        kind: lesson, course_summary, session_recap, explainer, how_to, announcement or onboarding (optional).
        Returns job_id; rendering takes a few minutes - poll video_status."""
        plan = json.loads(plan_json) if plan_json else None
        source = (
            None
            if plan
            else Source(text=text, title=title, kind=kind or None, context=json.loads(context_json or "{}"))
        )
        design = _design(style, format, effects) or None
        return jm.start(
            source=source,
            plan=plan,
            brand_id=brand_id or None,
            brand_url=brand_url or None,
            voice=voice or None,
            design=design,
            quality=quality or None,
        )

    @server.tool()
    def video_status(job_id: str) -> dict:
        """Status of a video job: queued | running (with current step) | done | needs_review | check_failed | error.
        When done, includes the local video path and the final plan."""
        return jm.get(job_id)

    return server


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="kinetry-mcp")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    server = build_server()
    if a.http:
        server.run("streamable-http", port=a.port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])


def _design(style: str = "", format: str = "", effects: str = "") -> dict:
    d = {k: v for k, v in (("style", style), ("format", format)) if v}
    if effects:
        d["effects"] = {"level": effects}
    return d
