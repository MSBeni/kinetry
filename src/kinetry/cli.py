"""Command line: `kinetry <command>`.

kinetry setup                                   install HyperFrames, GSAP and Chrome (once)
kinetry doctor                                  check the toolchain
kinetry sections lesson.md                      list the `##` sections of a Markdown source
kinetry brand https://acme.com --save brands/acme
kinetry plan  lesson.md --section 2 --out plan.json
kinetry run   lesson.md --section 2 --brand brands/acme --out week2.mp4
kinetry run   --plan plan.json --brand https://acme.com --out week2.mp4
kinetry run   lesson.md --llm openai:gpt-4.1 --llm-fast openai:gpt-4.1-mini --out w2.mp4
kinetry models bedrock                          list the models your credentials can use
kinetry run   lesson.md --style warm --format 9:16 --music bed.mp3 --out w2.mp4
kinetry catalog                                 scene types, layouts, styles, transitions (--markdown, --json)
kinetry gallery --out gallery/                  render every scene type in every style and format
kinetry preview plan.json --out storyboard/     one frame per scene in seconds, no voice
kinetry profile brands/acme --styles editorial,minimal --avoid sticky_tip
kinetry probe https://acme.com --out probe.json
kinetry voice-design --name Coach --description "female, middle-aged, low pitch, american accent"
kinetry voice-clone  --name Dana --ref dana.wav --consent-audio consent.wav --consent-text "I, Dana Lee, agree..."
kinetry serve --port 8080                       HTTP API (pip install 'kinetry[service]')
kinetry mcp                                     MCP server over stdio (pip install 'kinetry[mcp]')
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import Settings


def _context(args) -> dict:
    ctx = {}
    for kv in args.context or []:
        k, _, v = kv.partition("=")
        ctx[k.strip()] = v.strip()
    images = []
    for spec in getattr(args, "image", None) or []:
        ref, _, about = spec.partition("::")
        images.append({"ref": ref.strip(), "about": about.strip()})
    if images:
        ctx["images"] = images
    if getattr(args, "kind", None):
        ctx["kind"] = args.kind
    return ctx


def main(argv: list[str] | None = None) -> int:
    """`kinetry ...`: expected failures (a missing file or package, a refused URL, an unreachable site) print
    one clear line instead of a traceback; KINETRY_DEBUG=1 shows the traceback."""
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001
        import os

        if os.environ.get("KINETRY_DEBUG") == "1" or not _expected(e):
            raise
        print(f"kinetry: {_message(e)}", file=sys.stderr)
        print("(set KINETRY_DEBUG=1 to see the full traceback)", file=sys.stderr)
        return 2


def _expected(e: Exception) -> bool:
    try:
        import httpx

        net = (httpx.HTTPError,)
    except ImportError:  # pragma: no cover
        net = ()
    return isinstance(e, (FileNotFoundError, PermissionError, IsADirectoryError, RuntimeError, ValueError, *net))


def _message(e: Exception) -> str:
    if isinstance(e, FileNotFoundError) and e.filename:
        return f"no such file: {e.filename}"
    try:
        import httpx

        if isinstance(e, httpx.HTTPStatusError):
            return f"{e.request.url} answered {e.response.status_code}"
        if isinstance(e, httpx.HTTPError):
            return f"couldn't reach {getattr(e.request, 'url', 'the site')}: {e}"
    except (ImportError, RuntimeError):
        pass
    return str(e) or type(e).__name__


def _main(argv: list[str] | None = None) -> int:
    from . import __version__

    ap = argparse.ArgumentParser(prog="kinetry", description="Narrated, on-brand videos from learning content.")
    ap.add_argument("--version", action="version", version=f"kinetry {__version__}")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="install the rendering toolchain into KINETRY_HOME")
    s.add_argument("--no-browser", action="store_true", help="skip Chrome download (use KINETRY_BROWSER_PATH)")
    sub.add_parser("doctor", help="check the toolchain")
    dm = sub.add_parser("demo", help="render a ready-made video with no keys: the quickest check that everything works")
    dm.add_argument("name", nargs="?", default="welcome", help="which demo (see --list); default: welcome")
    dm.add_argument("--out", help="where to write the MP4 (default: kinetry-<name>.mp4)")
    dm.add_argument("--list", action="store_true", help="list the demos")
    dm.add_argument("--setup", action="store_true", help="install the renderer first if it's missing")
    dm.add_argument("--quality", help="draft (fastest) | standard (default) | high")
    ci = sub.add_parser("check-inworld", help="live test of your Inworld key: voices, TTS models, STT round trip")
    ci.add_argument("--cast", help="also check every Inworld voice in this cast file exists on your account")
    ci.add_argument("--voice", default="Ashley", help="voice for the TTS test (default Ashley)")
    ci.add_argument("--out", default="inworld-check", help="where to keep the test audio")

    br = sub.add_parser("brief", help="turn a request in plain words into a structured video request (JSON)")
    br.add_argument("message", help='the request, e.g. "a 60-second vertical how-to for new nurses, in Spanish"')
    br.add_argument("--file", help="read the message from a file instead (e.g. a request with pasted notes)")
    br.add_argument("--llm", help="provider:model to read the request; default: KINETRY_LLM, else keyword rules")

    sec = sub.add_parser("sections", help="list the sections of a source (Markdown, Word, PowerPoint, PDF, web page)")
    sec.add_argument("source")

    def add_source_args(p):
        p.add_argument(
            "source",
            nargs="?",
            help=".md/.txt/.html/.json, .docx/.pptx/.pdf, a web page URL, or an audio/video recording (transcribed)",
        )
        p.add_argument("--stt", help="speech-to-text for recordings (default inworld:inworld-stt-1; INWORLD_API_KEY)")
        p.add_argument("--stt-lang", default="en", help="language of the recording (default en)")
        p.add_argument(
            "--section", type=int, help="1-based section: a ## heading, Word Heading 1, slide, or PDF chapter/pages"
        )
        p.add_argument(
            "--context",
            action="append",
            metavar="KEY=VALUE",
            help="extra facts for the planner, e.g. --context audience='new managers'",
        )
        p.add_argument(
            "--kind",
            help="what the video is for: lesson, course_summary, session_recap, explainer, how_to, announcement, "
            "onboarding (shapes structure and default length)",
        )
        p.add_argument(
            "--image",
            action="append",
            metavar="REF[::ABOUT]",
            help="an image the planner may show in an image scene: a file, https URL, upload:<id> or brand:<n>, "
            "with an optional note on what it shows, e.g. --image 'studio.jpg::the third-floor studio'",
        )

    def add_llm_args(p):
        p.add_argument("--replay", help="directory of recorded LLM outputs (no model calls)")
        p.add_argument(
            "--llm",
            help="provider:model, e.g. anthropic:claude-sonnet-5-5, openai:gpt-4.1, google:gemini-2.5-pro, "
            "bedrock:<model id or inference profile>. Keys come from the provider's usual env var.",
        )
        p.add_argument("--llm-fast", help="cheaper provider:model for copy rewrites (default: same as --llm)")
        p.add_argument("--llm-base-url", help="endpoint for openai_compatible / azure / a gateway")
        p.add_argument("--region", help="AWS region for Bedrock")

    def add_design_args(p):
        g = p.add_argument_group("design (empty = chosen by the creative director)")
        g.add_argument("--style", help="style pack, e.g. editorial, technical, warm, bold, minimal, corporate, classic")
        g.add_argument("--format", choices=["16:9", "9:16", "1:1"])
        g.add_argument("--motion", help="motion pack override")
        g.add_argument("--transition", help="transition override, e.g. fade, push, wipe, scribble")
        g.add_argument("--pacing", choices=["calm", "normal", "brisk"])
        g.add_argument("--captions", action=argparse.BooleanOptionalAction, default=None)
        g.add_argument("--seed", type=int, help="reshuffle automatic layout choices")
        g.add_argument("--lang", help="language of narration and on-screen text")
        lv = ["off", "subtle", "rich"]
        g.add_argument(
            "--effects", choices=lv, help="motion layers: camera moves, kinetic type, ambient light (default off)"
        )
        g.add_argument("--camera", choices=lv, help="override the camera layer")
        g.add_argument("--kinetic", choices=lv, help="override kinetic type")
        g.add_argument("--ambient", choices=lv, help="override ambient light")
        g.add_argument("--illustration", choices=lv, help="animated illustration scenes (not set by --effects)")
        g.add_argument("--depth", choices=lv, help="a 3D stage behind the scenes, Three.js (not set by --effects)")
        g.add_argument(
            "--characters",
            choices=lv,
            help="animated character scenes: blink, expressions, lip-sync (not set by --effects)",
        )
        g.add_argument(
            "--depth-models",
            choices=["auto", "off"],
            help="the brand's own 3D models on the 3D stage (default auto: the asset agent picks per scene)",
        )

    b = sub.add_parser("brand", help="build a brand pack from a website")
    b.add_argument("url", help="https URL, saved .html, or probe .json")
    b.add_argument("--save", required=True, help="directory to write the brand pack to")
    b.add_argument("--no-logo", action="store_true")
    add_llm_args(b)

    pl = sub.add_parser("plan", help="write a reviewable video plan (JSON)")
    add_source_args(pl)
    pl.add_argument("--out", required=True)
    pl.add_argument("--brand", help="brand pack directory, URL, saved .html or probe .json (informs the look)")
    add_llm_args(pl)
    add_design_args(pl)

    r = sub.add_parser("run", help="generate a video")
    add_source_args(r)
    r.add_argument("--plan", help="render a reviewed plan.json instead of planning from a source")
    r.add_argument("--brand", help="URL, saved .html, probe .json, or brand pack directory; omit for default")
    r.add_argument("--no-logo", action="store_true")
    r.add_argument(
        "--voice", help="narrator voice (default kokoro:af_heart, or a Kokoro voice in the script's language)"
    )
    r.add_argument("--out", required=True)
    r.add_argument("--run-dir")
    r.add_argument("--no-qa", action="store_true", help="skip QA frame snapshots")
    r.add_argument(
        "--quality",
        help="draft (fast preview) | standard (default, small files) | high (near-lossless) | a CRF number 0-51",
    )
    r.add_argument("--voice-a", help="voice for dialogue speaker a")
    r.add_argument("--voice-b", help="voice for dialogue speaker b")
    r.add_argument("--cast", help="cast file: named characters with voices (see examples/casts)")
    r.add_argument(
        "--speaker", action="append", metavar="ROLE=CHARACTER", help="who plays a role, e.g. a=gatekeeper_female"
    )
    r.add_argument("--music", help="music bed (mp3/wav), mixed under the narration with ducking")
    r.add_argument("--music-volume", type=float)
    r.add_argument(
        "--voice-check",
        nargs="?",
        const="inworld:inworld-stt-1",
        metavar="STT",
        help="listen back to every narrated line and flag ones that don't match the script (INWORLD_API_KEY)",
    )
    r.add_argument(
        "--package",
        choices=["scorm12", "scorm2004", "web"],
        help="also write an LMS package next to the video (<out>.zip): captions, chapters, transcript, quiz",
    )
    r.add_argument("--quiz", default="3", help="knowledge check questions in the package: a number, or off")
    add_llm_args(r)
    add_design_args(r)

    pk = sub.add_parser("package", help="turn a finished run into an LMS package (SCORM 1.2 / 2004) or a web zip")
    pk.add_argument("run_dir", help="the run directory `kinetry run` printed")
    pk.add_argument("--out", required=True, help="the .zip to write")
    pk.add_argument("--standard", choices=["scorm12", "scorm2004", "web"], default="scorm12")
    pk.add_argument("--quiz", default="3", help="knowledge check questions: a number (default 3), or off")
    pk.add_argument("--quiz-file", help="use your own questions (JSON: {questions: [...]}) instead of writing them")
    pk.add_argument("--mastery", type=int, default=80, help="passing score in percent (default 80)")
    pk.add_argument("--title", help="the lesson title shown in the LMS (default: the video's title)")
    pk.add_argument("--video", help="package this video file instead of the run's own (e.g. a re-encode)")
    pk.add_argument("--replay", help="use recorded model outputs from this directory")
    pk.add_argument("--llm", help="model for the knowledge check, as provider:model (default KINETRY_LLM)")

    lo = sub.add_parser("localize", help="the same video in other languages, as one batch")
    lo.add_argument("plan", help="a reviewed plan.json, or a finished run directory")
    lo.add_argument("--to", required=True, help="languages, e.g. es,fr,de,pt-BR,zh,ar")
    lo.add_argument("--out-dir", required=True)
    lo.add_argument("--brand", help="brand pack directory, URL, saved .html or probe .json; omit for default")
    lo.add_argument(
        "--voice",
        action="append",
        metavar="LANG[.ROLE]=SPEC",
        help="a voice for one language, e.g. ar=inworld:inworld-tts-1:<arabic-voice> or es.a=kokoro:em_alex (repeatable); "
        "languages Kokoro speaks (en, es, fr, hi, it, pt, zh) need none",
    )
    lo.add_argument("--translate-only", action="store_true", help="write the translated plans to review, no render")
    lo.add_argument("--package", choices=["scorm12", "scorm2004", "web"], help="also write an LMS package per language")
    lo.add_argument("--quiz", default="3", help="knowledge-check questions in each package (1-6), or off")
    lo.add_argument("--mastery", type=int, default=80)
    lo.add_argument("--name", help="file name stem (default: from the plan title)")
    lo.add_argument("--quality", help="draft | standard (default) | high | a CRF number")
    add_llm_args(lo)

    cat = sub.add_parser("catalog", help="what the engine can render")
    cat.add_argument("--json", action="store_true")
    cat.add_argument("--markdown", action="store_true", help="the docs/CATALOG.md text")

    gal = sub.add_parser("gallery", help="render every scene type and layout in every style and format")
    gal.add_argument("--out", required=True)
    gal.add_argument("--brand", help="brand pack directory (default: Kinetry's own)")
    gal.add_argument("--styles", help="comma list")
    gal.add_argument("--formats", help="comma list, e.g. 16:9,9:16")
    gal.add_argument("--components", help="comma list of scene types")
    gal.add_argument("--no-check", action="store_true")
    gal.add_argument("--effects", choices=["off", "subtle", "rich"], default="off", help="render with motion layers")
    gal.add_argument("--lang", default="en", help="page language, e.g. fa to audit right-to-left layouts")
    gal.add_argument("--depth", choices=["off", "subtle", "rich"], default="off", help="render on the 3D stage")

    pv = sub.add_parser("preview", help="storyboard frames for a plan in seconds (no voice)")
    pv.add_argument("plan")
    pv.add_argument("--out", required=True)
    pv.add_argument("--brand")
    add_design_args(pv)

    pr = sub.add_parser("profile", help="show or set a brand's standing design preferences")
    pr.add_argument("brand_dir")
    pr.add_argument("--styles", help="comma list of allowed styles")
    pr.add_argument("--style", help="pin one style")
    pr.add_argument("--format", choices=["16:9", "9:16", "1:1"])
    pr.add_argument("--transition")
    pr.add_argument("--avoid", help="comma list of scene types never to use")
    pr.add_argument("--prefer", help="comma list of scene types to favor")
    pr.add_argument("--voice", action="append", metavar="ROLE=SPEC", help="e.g. narrator=kokoro:bf_emma, a=...")
    pr.add_argument("--music", help="music bed for every video of this brand")
    pr.add_argument("--notes")
    pr.add_argument("--effects", choices=["off", "subtle", "rich"], help="default motion layers for this brand")
    pr.add_argument("--mark", help="the logo's symbol alone, as an SVG file; shown in 3D on the depth stage")

    a3 = sub.add_parser("assets3d", help="a brand's own 3D models (.glb) and logo symbol for the 3D stage")
    a3.add_argument("brand_dir")
    a3.add_argument("action", choices=["list", "add", "remove", "describe", "mark"])
    a3.add_argument(
        "target",
        nargs="?",
        help="add: a .glb file or https URL; remove/describe: a model id; mark: a logo image (default: the pack's)",
    )
    a3.add_argument("--name", help="add/describe: what the model is called")
    a3.add_argument("--about", help="add/describe: what it is, in a sentence (else the asset agent describes it)")
    a3.add_argument("--tags", help="add/describe: comma list of words a script about it would use")
    a3.add_argument("--role", choices=["hero", "prop", "logo"], help="hero/logo: title and closing scenes")
    a3.add_argument("--llm", help="provider:model for describing models (default: KINETRY_LLM, else the names inside)")

    p = sub.add_parser("probe", help="capture brand evidence + logo from a live site (headless Chrome)")
    p.add_argument("url")
    p.add_argument("--out", required=True)

    d = sub.add_parser("voice-design", help="create a designed voice in VoiceStudio")
    d.add_argument("--name", required=True)
    d.add_argument("--description", required=True)

    c = sub.add_parser("voice-clone", help="clone a consenting speaker's voice in VoiceStudio")
    c.add_argument("--name", required=True)
    c.add_argument("--ref", required=True)
    c.add_argument("--ref-text", default="")
    c.add_argument("--consent-audio", required=True)
    c.add_argument("--consent-text", required=True)

    sv = sub.add_parser("serve", help="run the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8080)

    sub.add_parser("mcp", help="run the MCP server over stdio")

    m = sub.add_parser("models", help="list the models your credentials can use for a provider")
    m.add_argument("provider", help="bedrock | anthropic | openai | google | openai_compatible")
    m.add_argument("--base-url", help="for openai_compatible")
    m.add_argument("--region", help="AWS region for Bedrock")

    tr = sub.add_parser("transcribe", help="speech to text for an audio/video file (Inworld inworld-stt-1)")
    tr.add_argument("file")
    tr.add_argument("--stt", help="transcriber spec (default inworld:inworld-stt-1)")
    tr.add_argument("--lang", default="en")
    tr.add_argument("--json", action="store_true", help="text plus word timings")

    ca = sub.add_parser("cast", help="show a cast file; --verify checks its Inworld voices exist on your account")
    ca.add_argument("file")
    ca.add_argument("--verify", action="store_true", help="look the voice ids up on Inworld (INWORLD_API_KEY)")

    cl = sub.add_parser("check-llm", help="live test of a model: creative director, script writer, optional render")
    add_llm_args(cl)
    cl.add_argument("--source", help="a .md/.txt source instead of the built-in sample lesson")
    cl.add_argument("--render", action="store_true", help="also render the video (fit loop and copy rewrites)")
    cl.add_argument("--voice", help="voice for --render (default kokoro:af_heart)")
    cl.add_argument("--out", default="llm-check")
    cv = sub.add_parser("check-voices", help="live test of voices: synthesize, then listen back with Inworld STT")
    cv.add_argument("voice", nargs="+", help="voice specs, e.g. openai:coral elevenlabs:<voice_id> inworld:Ashley")
    cv.add_argument("--out", default="voice-check")

    vl = sub.add_parser("voices", help="list voices a provider offers (kokoro, inworld)")
    vl.add_argument("provider", choices=["kokoro", "inworld"])
    vl.add_argument("--lang", help="ISO 639-1 language filter, e.g. en (inworld)")

    a = ap.parse_args(argv)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO if a.verbose or a.cmd in ("run", "brand", "plan") else logging.WARNING,
        format="[kinetry] %(message)s",
    )
    settings = Settings()

    if a.cmd == "setup":
        from .tooling import setup

        for line in setup(settings, browser=not a.no_browser):
            print(line)
        return 0
    if a.cmd == "demo":
        return _demo(a, settings)
    if a.cmd == "package":
        return _package(a, ap, settings)
    if a.cmd == "doctor":
        from .tooling import doctor

        res = doctor(settings)
        for k, v in res.items():
            print(f"{k:12} {v}")
        return 1 if any("MISSING" in v for v in res.values()) else 0
    if a.cmd == "check-inworld":
        import os

        from .livecheck import check_inworld

        if not os.environ.get("INWORLD_API_KEY"):
            print("set INWORLD_API_KEY first (the Base64 key from Inworld Portal > API Keys)", file=sys.stderr)
            return 1

        def show(r):
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['step']:24} {r['seconds']:5.1f}s  {r['detail']}", flush=True)

        rows = check_inworld(Path(a.out), voice=a.voice, cast_file=a.cast, on_row=show)
        bad = [r for r in rows if not r["ok"]]
        print(
            f"\n{len(rows) - len(bad)}/{len(rows)} passed"
            + ("" if rows[0]["ok"] else " (auth failed; nothing else ran)")
        )
        return 1 if bad else 0
    if a.cmd in ("check-llm", "check-voices"):
        import os

        from .livecheck import check_llm, check_voices

        def show(r):
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['step']:28} {r['seconds']:6.1f}s  {r['detail']}", flush=True)

        if a.cmd == "check-llm":
            from .llm import LLMConfig

            if not a.llm:
                ap.error("check-llm needs --llm provider:model (keys come from the provider's usual env vars)")
            llm = LLMConfig.from_spec(a.llm, base_url=a.llm_base_url, region=a.region)
            text = Path(a.source).read_text(encoding="utf-8") if a.source else None
            kw = {"source_text": text} if text else {}
            rows = check_llm(llm, Path(a.out), render=a.render, voice=a.voice, on_row=show, **kw)
        else:
            rows = check_voices(a.voice, Path(a.out), stt_key=os.environ.get("INWORLD_API_KEY"), on_row=show)
        bad = [r for r in rows if not r["ok"]]
        print(f"\n{len(rows) - len(bad)}/{len(rows)} passed")
        return 1 if bad or not rows else 0
    if a.cmd == "brief":
        import os

        from .brief import brief_json, make_brief

        msg = Path(a.file).read_text(encoding="utf-8") if a.file else a.message
        if a.file and a.message and a.message != "-":
            msg = a.message + "\n\n" + msg
        use_model = a.llm or os.environ.get("KINETRY_LLM")
        print(brief_json(make_brief(msg, llm=a.llm or None, settings=Settings() if use_model else None)))
        return 0
    if a.cmd == "sections":
        from .sources import MAX_SOURCE_WORDS, read_markdown, split_sections

        md, title, kind = read_markdown(a.source)
        secs = split_sections(md)
        if title or kind:
            print(f"{title or a.source}" + (f" ({kind})" if kind else ""))
        for i, (t, body) in enumerate(secs, 1):
            n = len(body.split())
            print(f"{i}. {t}  ({n} words{', too long for one video' if n > MAX_SOURCE_WORDS else ''})")
        if not secs:
            print(f"no sections; {len(md.split())} words in total")
        return 0
    if a.cmd == "probe":
        from .probe import probe_site

        res = probe_site(a.url, settings, Path(a.out))
        print(
            json.dumps(
                {
                    "site": res.get("site_name"),
                    "logos": len(res.get("logos") or []),
                    "fonts": res.get("fonts"),
                    "out": a.out,
                }
            )
        )
        return 0
    if a.cmd == "serve":
        try:
            import uvicorn
        except ImportError:
            print("pip install 'kinetry[service]'", file=sys.stderr)
            return 1
        uvicorn.run("kinetry.service:app", host=a.host, port=a.port)
        return 0
    if a.cmd == "mcp":
        from .integrations.mcp_server import main as mcp_main

        mcp_main([])
        return 0

    if a.cmd == "catalog":
        from .design.catalog import load_catalog

        cat = load_catalog()
        if a.markdown:
            print(cat.to_markdown())
        elif a.json:
            print(json.dumps({**cat.to_dict(), "combinations": cat.combinations()}, indent=2))
        else:
            n = cat.combinations()
            print(
                f"{n['components']} scene types, {n['layouts']} layouts, {n['styles']} styles, {n['motions']} motion "
                f"packs, {n['transitions']} transitions, 3 formats -> {n['scene_renderings']} scene renderings\n"
            )
            print("Styles:\n" + cat.styles_guide() + "\n")
            for c in cat.components.values():
                print(f"  {c.id:16} {', '.join(c.layouts):28} {c.purpose}")
        return 0
    if a.cmd == "gallery":
        from .branding import BrandPack
        from .design.gallery import build_gallery

        split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731
        res = build_gallery(
            Path(a.out),
            settings,
            pack=BrandPack.load(a.brand) if a.brand else None,
            styles=split(a.styles),
            formats=split(a.formats),
            components=split(a.components),
            check=not a.no_check,
            effects=a.effects,
            lang=a.lang,
            depth=a.depth,
        )
        print(json.dumps(res, indent=2))
        print(f"open {Path(a.out) / 'index.html'}")
        return 1 if res["failed"] else 0
    if a.cmd == "assets3d":
        return _assets3d(a, ap, settings)
    if a.cmd == "profile":
        from .branding import BrandPack
        from .jobs import check_profile

        pack = BrandPack.load(a.brand_dir)
        prof = pack.profile
        split = lambda v: [x.strip() for x in v.split(",") if x.strip()]  # noqa: E731
        bad_voice = [kv for kv in (a.voice or []) if "=" not in kv]
        if bad_voice:
            ap.error(f"--voice takes ROLE=SPEC, e.g. narrator=kokoro:bf_emma (got {bad_voice[0]!r})")
        if a.music and not Path(a.music).is_file():
            ap.error(f"--music: no such file {a.music}")
        if a.mark:
            data = Path(a.mark).read_bytes() if Path(a.mark).is_file() else b""
            if not a.mark.lower().endswith(".svg") or b"<path" not in data or len(data) > 300_000:
                ap.error("--mark takes an SVG file with <path> shapes, under 300 KB")
            pack.mark = ("mark.svg", data)
            pack.save(a.brand_dir)
            print(f"mark saved: {Path(a.brand_dir) / 'mark.svg'}")
        changes = {
            k: v
            for k, v in {
                "styles": split(a.styles) if a.styles else None,
                "style": a.style,
                "format": a.format,
                "transition": a.transition,
                "avoid_components": split(a.avoid) if a.avoid else None,
                "prefer_components": split(a.prefer) if a.prefer else None,
                "music": str(Path(a.music).resolve()) if a.music else None,
                "notes": a.notes,
                "effects": {"level": a.effects} if a.effects else None,
                "voices": {**prof.voices, **dict(kv.split("=", 1) for kv in a.voice)} if a.voice else None,
            }.items()
            if v is not None
        }
        if changes:
            new = prof.model_copy(update=changes)
            try:
                check_profile(new.model_copy(update={"music": None}))  # same rules as the API, plus a local music file
            except ValueError as e:
                ap.error(str(e))
            pack.profile = new
            pack.profile.save(a.brand_dir)
        print(pack.profile.model_dump_json(indent=2, exclude_defaults=True))
        return 0

    if a.cmd == "transcribe":
        from dataclasses import asdict

        from .stt import make_transcriber

        t = make_transcriber(a.stt, language=a.lang).transcribe(Path(a.file))
        print(json.dumps(asdict(t), indent=2) if a.json else t.text)
        return 0
    if a.cmd == "cast":
        from .cast import load_cast

        cast = load_cast(a.file)
        found = None
        if a.verify:
            from .voice import InworldProvider

            found = cast.verify_inworld(InworldProvider("x").list_voices(None))
        for ch in cast.characters:
            mark = "" if found is None or ch.id not in found else ("  ok" if found[ch.id] else "  NOT FOUND on Inworld")
            look = f"  [{ch.appearance}]" if ch.appearance else ""
            print(f"{ch.id:28} {cast.spec(ch.id):40}{look}{mark}")
        return 0 if not found or all(found.values()) else 3
    if a.cmd == "voices":
        if a.provider == "inworld":
            from .voice import INWORLD_MODELS, InworldProvider

            for v in InworldProvider("x").list_voices(a.lang):
                tags = ", ".join(v.get("tags") or [])
                print(f"inworld:{v['voiceId']:24} {'/'.join(v.get('languages') or [])[:20]:20} {tags}")
            print(f"\nmodels: {', '.join(INWORLD_MODELS)}  (inworld:<model>:<voice>; default inworld-tts-2)")
        else:
            from .voice import KOKORO_LANGS, kokoro_voices

            for v in kokoro_voices(settings):
                gender = "female" if v[1:2] == "f" else "male"
                print(f"kokoro:{v:16} {KOKORO_LANGS.get(v[0], '?')}, {gender}")
        return 0
    if a.cmd == "models":
        from .llm import LLMConfig, list_models

        try:
            models = list_models(LLMConfig(provider=a.provider, base_url=a.base_url, region=a.region))
        except Exception as e:  # noqa: BLE001
            print(f"could not list {a.provider} models: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        for row in models:
            print(f"{a.provider}:{row['id']}" + (f"   ({row['name']})" if row.get("name") != row["id"] else ""))
        return 0

    def design_of(args) -> dict:
        keys = ("style", "format", "motion", "transition", "pacing", "captions", "seed", "lang")
        out = {k: getattr(args, k) for k in keys if getattr(args, k, None) is not None}
        fx = {
            k2: getattr(args, k1)
            for k1, k2 in (
                ("effects", "level"),
                ("camera", "camera"),
                ("kinetic", "kinetic"),
                ("ambient", "ambient"),
                ("illustration", "illustration"),
                ("depth", "depth"),
                ("characters", "characters"),
                ("depth_models", "depth_models"),
            )
            if getattr(args, k1, None)
        }
        if fx:
            out["effects"] = fx
        return out

    if a.cmd == "preview":
        from .api import Kinetry

        tf = Kinetry(settings=settings)
        frames = tf.preview(json.loads(Path(a.plan).read_text()), brand=a.brand, out_dir=a.out, design=design_of(a))
        print(json.dumps({"frames": [str(f) for f in frames]}, indent=2))
        return 0

    if a.cmd == "localize":
        return _localize(a, ap, settings)

    if a.cmd in ("brand", "plan", "run"):
        from .api import Kinetry
        from .llm import LLMConfig
        from .sources import load_source

        def source_of(args):
            from .stt import AUDIO_EXTS, make_transcriber

            stt = None
            if args.source and Path(args.source).suffix.lower() in AUDIO_EXTS:
                stt = make_transcriber(args.stt, language=args.stt_lang)
            return load_source(args.source, args.section, _context(args), transcriber=stt)

        def cfg(spec):
            return LLMConfig.from_spec(spec, base_url=a.llm_base_url, region=a.region) if spec else None

        tf = Kinetry(settings=settings, replay_dir=a.replay, llm=cfg(a.llm), llm_fast=cfg(a.llm_fast))
        if a.cmd == "brand":
            pack = tf.brand(a.url, use_logo=not a.no_logo)
            pack.save(a.save)
            print(
                json.dumps(
                    {
                        "saved": a.save,
                        "accent": pack.kit.accent,
                        "fonts": [pack.kit.display_font, pack.kit.body_font],
                        "logo": bool(pack.logo),
                        "notes": pack.notes,
                    },
                    indent=2,
                )
            )
            return 0
        if a.cmd == "plan":
            plan = tf.plan(source_of(a), brand=a.brand, design=design_of(a))
            Path(a.out).write_text(plan.model_dump_json(indent=2))
            print(
                json.dumps(
                    {
                        "plan": a.out,
                        "style": plan.design.style,
                        "format": plan.design.resolved_format(),
                        "scenes": [f"{s.type}/{s.layout}" for s in plan.scenes],
                        "words": plan.word_count(),
                    }
                )
            )
            return 0
        voices = {}
        if a.cast or a.speaker:
            from .cast import load_cast, parse_assign

            if not (a.cast and a.speaker):
                ap.error("--cast and --speaker go together")
            voices = load_cast(a.cast).voices(parse_assign(a.speaker))
        voices |= {k: v for k, v in (("a", a.voice_a), ("b", a.voice_b)) if v}
        if "narrator" in voices and not a.voice:  # the cast's narrator beats the default
            a.voice = voices.pop("narrator")
        common = dict(
            brand=a.brand,
            out=a.out,
            voice=a.voice,
            run_dir=a.run_dir,
            use_logo=not a.no_logo,
            qa_frames=not a.no_qa,
            design=design_of(a),
            voices=voices,
            music=a.music,
            music_volume=a.music_volume,
            voice_check=a.voice_check,
            quality=a.quality,
        )
        if a.plan:
            res = tf.render(json.loads(Path(a.plan).read_text()), **common)
        else:
            if not a.source:
                ap.error("run needs a source file or --plan")
            res = tf.generate(source_of(a), **common)
        pkg = None
        if a.package and res.ok:
            n = _quiz_count(a.quiz, ap)
            pkg = tf.package(res, out=Path(a.out).with_suffix(".zip"), standard=a.package, quiz=n > 0, questions=n or 3)
        print(
            json.dumps(
                {
                    "status": res.status,
                    "video": str(res.video) if res.video else None,
                    "run_dir": str(res.run_dir),
                    "error": res.error,
                    **(
                        {"package": str(pkg.path), "quiz_questions": pkg.questions, "package_notes": pkg.notes}
                        if pkg
                        else {}
                    ),
                    **(
                        {"voice_check_flagged": [r["beat"] for r in res.voice_check if not r["ok"]]}
                        if res.voice_check is not None
                        else {}
                    ),
                }
            )
        )
        return 0 if res.ok else 2

    from .voice import VoiceStudioProvider

    vs = VoiceStudioProvider(settings=settings)
    if not vs.health():
        print(f"VoiceStudio not reachable at {settings.voicestudio_url}", file=sys.stderr)
        return 1
    if a.cmd == "voice-design":
        print(json.dumps(vs.design_voice(a.name, a.description), indent=2))
    elif a.cmd == "voice-clone":
        print(
            json.dumps(
                vs.clone_voice(
                    a.name,
                    Path(a.ref),
                    consent_audio=Path(a.consent_audio),
                    consent_text=a.consent_text,
                    reference_text=a.ref_text,
                ),
                indent=2,
            )
        )
    return 0


def _quiz_count(v: str, ap) -> int:
    if str(v).lower() in ("off", "0", "none", "no"):
        return 0
    try:
        n = int(v)
    except ValueError:
        ap.error(f"--quiz takes a number of questions (1-6) or off, not {v!r}")
    if not 1 <= n <= 6:
        ap.error("--quiz takes 1-6 questions, or off")
    return n


def _package(a, ap, settings) -> int:
    from .api import Kinetry
    from .llm import LLMConfig
    from .package import Quiz

    n = _quiz_count(a.quiz, ap)
    quiz = n > 0
    if a.quiz_file:
        quiz = Quiz.model_validate_json(Path(a.quiz_file).read_text(encoding="utf-8"))
    tf = Kinetry(settings=settings, replay_dir=a.replay, llm=LLMConfig.from_spec(a.llm) if a.llm else None)
    try:
        pkg = tf.package(
            a.run_dir,
            out=a.out,
            standard=a.standard,
            quiz=quiz,
            questions=n or 3,
            mastery=a.mastery,
            title=a.title,
            video=a.video,
        )
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"package": str(pkg.path), "standard": pkg.standard, "quiz_questions": pkg.questions, "notes": pkg.notes},
            indent=2,
        )
    )
    return 0


_DEMO_STEPS = {
    "brand": "brand loaded",
    "design": "look set",
    "plan": "plan checked",
    "voice": "every line voiced",
    "compose": "scenes composed",
    "fit_check": "text fit checked",
    "shrink": "type adjusted to fit",
    "hf_check": "composition checked; rendering the frames (the longest step)",
    "render": "frames rendered",
}


def _demo(a, settings) -> int:
    from .demos import DEMOS, missing_tools, render_demo

    if a.list:
        for d in DEMOS.values():
            print(f"{d.name:10} {d.title} (about {d.seconds} s)\n{'':10} {d.about}")
        return 0
    if a.name not in DEMOS:
        print(f"no demo called {a.name!r}; choose one of: {', '.join(DEMOS)}", file=sys.stderr)
        return 2
    fixes = missing_tools(settings)
    if fixes and a.setup and any("kinetry setup" in f for f in fixes):
        from .tooling import setup

        print("Setting up the renderer (once)...", flush=True)
        setup(settings)
        fixes = missing_tools(settings)
    if fixes:
        print("Almost there. Before the demo can run:", file=sys.stderr)
        for f in fixes:
            print(f"  - {f}", file=sys.stderr)
        return 1
    d = DEMOS[a.name]
    out = Path(a.out or f"kinetry-{d.name}.mp4").resolve()
    print(f'Making "{d.title}" (about {d.seconds} s of video) with the free local voice. No keys needed.', flush=True)

    def step(name: str, t: float) -> None:
        if name in _DEMO_STEPS:
            print(f"  {t:5.0f}s  {_DEMO_STEPS[name]}", flush=True)

    res = render_demo(d.name, out=out, settings=settings, quality=a.quality, on_step=step)
    if not res.ok:
        print(f"\nThe demo stopped: {res.status}. {res.error or ''}".rstrip(), file=sys.stderr)
        print(f"Details: {res.run_dir / 'report.json'}", file=sys.stderr)
        return 2
    print(f"\nDone: {res.video}  ({res.duration:.0f} s)")
    print("Next: make one from your own content, with any model key: https://kinetry.xyz/docs/#start")
    return 0


def _localize(a, ap, settings) -> int:
    from .api import Kinetry
    from .llm import LLMConfig
    from .localize import parse_langs, parse_voice_args

    try:
        langs = parse_langs(a.to)
        voices = parse_voice_args(a.voice)
    except ValueError as e:
        ap.error(str(e))
    quiz = 0
    if a.package:
        q = str(a.quiz).lower()
        quiz = 0 if q in ("off", "0", "none", "no") else int(q) if q.isdigit() and 1 <= int(q) <= 6 else -1
        if quiz < 0:
            ap.error("--quiz takes 1-6 questions, or off")

    def cfg(spec):
        return LLMConfig.from_spec(spec, base_url=a.llm_base_url, region=a.region) if spec else None

    tf = Kinetry(settings=settings, replay_dir=a.replay, llm=cfg(a.llm), llm_fast=cfg(a.llm_fast))

    def show(e: dict) -> None:
        if e.get("step") == "translate":
            print(f"[kinetry] {e['lang']}: translating into {e['language']}", file=sys.stderr, flush=True)
        elif e.get("step") == "render" and "voices" in e:
            print(f"[kinetry] {e['lang']}: rendering", file=sys.stderr, flush=True)

    try:
        items = tf.localize(
            a.plan,
            to=langs,
            out_dir=a.out_dir,
            brand=a.brand,
            voices=voices,
            render=not a.translate_only,
            package=a.package,
            quiz=quiz,
            mastery=a.mastery,
            name=a.name,
            quality=a.quality,
            on_event=show,
        )
    except (ValueError, FileNotFoundError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps({"out_dir": a.out_dir, "languages": [i.to_dict() for i in items]}, indent=2, ensure_ascii=False))
    return 0 if all(i.ok for i in items) else 2


def _assets3d(a, ap, settings) -> int:
    from . import brand3d
    from .branding import BrandPack

    if not (Path(a.brand_dir) / "brand.json").exists():
        ap.error(f"{a.brand_dir} is not a brand pack (make one with `kinetry brand URL --save DIR`)")
    show = lambda x: print(json.dumps(x, indent=2, ensure_ascii=False))  # noqa: E731
    llm = None
    if a.llm:
        from .llm import LLMConfig

        llm = LLMConfig.from_spec(a.llm)
    if a.action == "list":
        show([x.model_dump(exclude={"facts"}) for x in brand3d.load_library(a.brand_dir)])
        return 0
    if a.action == "add":
        if not a.target:
            ap.error("add takes a .glb file or an https URL")
        if a.target.startswith(("https://", "http://")):
            notes = brand3d.fetch_site_models(
                [a.target], a.brand_dir, public_only=settings.public_urls_only, settings=settings
            )
            print("\n".join(notes))
            return 0 if notes and not notes[0].startswith("skipped") else 1
        try:
            item = brand3d.add_asset(
                a.brand_dir,
                Path(a.target).read_bytes(),
                name=a.name or brand3d.nice_name(Path(a.target).stem),
                about=a.about or "",
                tags=[t for t in (a.tags or "").split(",") if t.strip()] or None,
                role=a.role,
                source="cli",
                llm=llm,
                settings=settings,
            )
        except (OSError, brand3d.AssetError) as e:
            print(f"not added: {e}", file=sys.stderr)
            return 1
        show(item.model_dump(exclude={"facts"}))
        return 0
    if a.action == "remove":
        if not a.target or not brand3d.remove_asset(a.brand_dir, a.target):
            print(f"no model {a.target!r} in {a.brand_dir}", file=sys.stderr)
            return 1
        print(f"removed {a.target}")
        return 0
    if a.action == "describe":
        items = brand3d.load_library(a.brand_dir)
        for x in items:
            if a.target not in (None, x.id):
                continue
            if a.about or a.tags or a.role or a.name:  # the brand's own words win
                x.name = a.name or x.name
                x.about = a.about or x.about
                x.tags = [t.strip().lower() for t in a.tags.split(",") if t.strip()] if a.tags else x.tags
                x.role = a.role or x.role
            else:
                x.about, x.tags, x.role = brand3d.describe(x.name, x.facts, note=x.about, llm=llm, settings=settings)
        brand3d.save_library(a.brand_dir, items)
        show([x.model_dump(exclude={"facts"}) for x in items if a.target in (None, x.id)])
        return 0
    # mark: cut the symbol out of the logo
    pack = BrandPack.load(a.brand_dir)
    logo = (Path(a.target).name, Path(a.target).read_bytes()) if a.target else pack.logo
    if not logo:
        ap.error("the pack has no logo; give a logo image")
    png = brand3d.rasterize_svg(logo[1], settings) if logo[0].lower().endswith(".svg") else None
    svg = brand3d.extract_mark(logo, png=png)
    if not svg:
        print("no separate symbol found: the logo looks like a wordmark or a symbol on its own", file=sys.stderr)
        return 1
    pack.mark = ("mark.svg", svg)
    pack.save(a.brand_dir)
    print(f"mark saved: {Path(a.brand_dir) / 'mark.svg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
