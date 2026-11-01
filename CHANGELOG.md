# Changelog

## Unreleased

- **Generated media** (experimental, `kinetry[media]`, `kinetry media estimate|image|clip|cast`): images and video from your own Google account (Gemini image models or Imagen, and Veo; Vertex AI or the Gemini API). Every call is priced first from list prices (`kinetry.media.pricing`), a per-run spending cap refuses calls that would go over it, and a content-addressed cache means a request is only paid for once.
- **Character packs from a photo** (`kinetry media cast --consent`): a styled cartoon of the person plus expressions, mouth shapes and a blink, generated as edits of one base; variants are registered to the base (phase correlation) and the mouth and eyes are cut into feathered patches so the face stays still while it talks; the background is cut out. A `character` speaker's `"sprite"` uses the pack (expressions crossfade, the lip-sync drives the mouth patches).
- **`clip` scene type** (`--clips`): a generated or supplied video, full-frame with text over it or in a rounded frame. Media clips can't be timed inside a timed scene, so the renderer hoists them to the top level of the page and the scene fades them in and out; on a full-frame clip the bottom chrome turns white and the top fades into the page.

- **Animated characters** (experimental, `--characters` / `design.effects.characters`): a new `character` scene type with one or two flat SVG people in a simple set (`plain`, `night`, `shower`, `office`). They walk in, breathe and blink, look at each other, change expression on cue per line or thought (`neutral`, `happy`, `worried`, `annoyed`, `thinking`, `shocked`, `calm`), and their mouths move only during their own voiced lines (from the scene's speaker windows). Looks are set per speaker: skin tone, hair style and color, shirt in the brand's colors, glasses, a phone or mug; `imagined` draws a person as someone in the other's head. Speech bubbles for spoken lines, thought bubbles for narrated beats. Seek-safe like every other scene: absolute times, finite loops, blink gaps from a fixed hash.
- **Lip-sync from the audio** (`kinetry.visemes`): each voiced line gets classic 2D mouth shapes (closed, m/b/p, teeth, open, wide, round, pucker, f/v), timed from the line's own loudness and its phonemes (espeak-ng via `phonemizer`, installed with the local voice); offline and deterministic. Previews (no audio) fall back to a simple open-close mouth.
- **Gestures and listening**: per line `gesture` (`explain`, `shrug`, `chest`, `wave`) raises a forearm and hand into frame for that line; the other person nods while someone speaks.
- **More looks**: `swept` hair, `salt` (salt-and-pepper) hair color, `beard` (`stubble`, `full`), bold round `frames`, polo `collar`, named shirt colors (`olive`, `navy`, `white`, `gray`).

## 0.3.0 (2026-10-31): first public release

- **Open source** under the Apache License 2.0. `NOTICE` names the adapted HyperFrames registry designs and the vendored Lucide shapes; `THIRD_PARTY.md` lists what's installed separately under its own license (GSAP, HyperFrames, Chromium, FFmpeg, Kokoro).
- **`kinetry demo`**: a ready-made video on any machine with no keys, no account and no model calls (`welcome`, `developer`, `spanish`; `--list`, `--setup`). It names exactly what's missing when the toolchain isn't ready.
- **LMS packages**: `kinetry package RUN_DIR` or `run --package scorm12|scorm2004|web` writes a zip an LMS can import: the video, WebVTT captions (speaker names in dialogues), chapters, a transcript, a poster and a small player that only counts what was actually watched. An optional knowledge check (1-6 questions) is written from the same source; a question is kept only if its supporting quote is found word for word. Score, passed/failed, completion, resume data and session time go to the LMS. Python `Kinetry.package()`; HTTP `"package"` on `POST /v1/videos` and `GET /v1/videos/{id}/package`. Every run now writes `timing.json`.
- **`kinetry localize`**: one reviewed plan (or finished run) into many languages as one batch. Only the words change; each language gets its own voice (Kokoro where it speaks the language, otherwise the cloud voice you name), its own timing and fit check, and optionally its own LMS package. Every language is checked for a usable voice before anything runs. Python `Kinetry.localize()`.
- **Outbound requests in the HTTP service**: caller-supplied URLs must resolve to public addresses, and every connection goes to the address that was checked (no DNS rebinding), in Python and in the brand probe's browser (through a local checking proxy). URL sources accept web addresses only, and downloads stop at the size Kinetry keeps.
- **First run**: `kinetry setup` stops with a clear message when the browser download fails; the local voice runs with Kinetry's own Python (works from a virtualenv that isn't activated, or pipx); `kinetry doctor` flags a default model whose package isn't installed; the CLI prints one clear line for expected errors (`KINETRY_DEBUG=1` shows the traceback); `kinetry --version`.

## 0.2.0 (2026-10-05)

### Motion layers

- **Motion layers**, opt-in via `design.effects` (`off` | `subtle` | `rich`, all at once or per layer); off by default so plain videos render exactly as before.
  - **camera**: push-ins and background parallax; rich adds directional drift and a punch-in on each scene's key moment (from the component manifest's `focus`).
  - **kinetic**: headline words animate word by word with emphasis pops; new **`statement`** scene type whose words land across the sentence that speaks them. Scene types can declare `requires`; the planner offers them only when that layer is on.
  - **ambient**: drifting pools of brand color (a moving spotlight in `technical`), particles in rich. Strength is capped per ground so text keeps WCAG contrast even where pools overlap.
- `--effects/--camera/--kinetic/--ambient` on `plan`, `run`, `preview`; `gallery --effects`; `profile --effects`; `effects` on HTTP `design`, MCP and LangChain tools; brand profiles can set a default.

### Design engine, brands and 3D

- **The brand's own 3D models on the 3D stage.** A brand pack keeps a library of the company's models (`.glb`: checked for size, embedded files and decoder-only compression) in `assets3d/`. An **asset agent** reads each one (parts, materials, colors, size, triangles, animations), describes it (with a model when configured, else from the names inside it; the brand's own words win), picks per scene which model may appear by matching its tags to the scene's words, and takes what it can from the brand's website: models the site shows or loads, and the logo's symbol cut out of a symbol-plus-wordmark logo and traced to SVG (`kinetry[brand3d]`). The stage places a model only where the settled layout leaves room, plays its own animations from the scene's clock (or turns it slowly), and lights it with a soft studio environment; title and closing scenes get a hero model or the logo mark in 3D. `kinetry assets3d add|list|describe|remove|mark`, `POST/GET/DELETE /v1/brands/{id}/assets3d`, `PUT /v1/brands/{id}/mark`, `design.effects.depth_models` (`auto`, `off`, or scene → model). Nothing on the stage is specific to a business or industry. Free space is measured from everything a scene paints (text, boxes, rules, images), with a margin for the page's own camera moves. The stage no longer dims the whole canvas; shapes are softened toward the page color instead, so models and the logo keep full color.

- Fixed: the illustration scene's `hero` layout sized the art by width, so with an eyebrow, headline and body it ran past the bottom of the safe area in 16:9 and 1:1 (the video ended as needs_review). The art is now sized by height there.

- **Motion levels 4 and 5**, opt-in by name (`design.effects.illustration` / `.depth`, `--illustration` / `--depth`; `level` doesn't turn them on, so existing videos are unchanged):
  - **illustration**: a new `illustration` scene type with eight original animated illustrations in the brand's palette, built part by part (pop, rise, grow, draw-on; rich keeps them floating, swinging and ticking), or the caller's own Lottie file (`context.animations`, uploaded with `POST /v1/images`). Lottie files are checked (3 MB, embedded images only) and played by lottie-web's light player (no expressions), frame by frame from the video's timeline.
  - **depth**: a Three.js stage behind the scenes: brand-colored shapes at the frame edges, fogged into the page color until the camera reaches them, and a camera that glides from scene to scene. Rendered from time alone, so frames match in any order; works with software WebGL.
  - `kinetry setup` installs three and lottie-web (pinned); `kinetry doctor` reports them; `gallery --depth`.

- **Video kinds**: `kind` on a source (`lesson`, `course_summary`, `session_recap`, `explainer`, `how_to`, `announcement`, `onboarding`) gives the planner a structure for that kind of video, a default length, scene types that suit it and a pacing hint; explicit choices still win. `--kind`, `GET /v1/kinds`, `kind` on the MCP and LangChain tools.
- **Brief agent**: a request in plain words becomes a structured request (kind, audience, length, language, format, captions, pasted content kept verbatim, a link to read, and questions for what's missing). The code checks every field the model returns and drops content that isn't in the message; without a model, keyword rules read English requests. `kinetry brief`, `POST /v1/briefs`, `brief_video` for MCP and LangChain.

- **Four scene types adapted from the HyperFrames registry** (Apache-2.0, credited in THIRD_PARTY.md): `code_snippet` (editor or terminal; code types out character by character with a caret, one line called out; JetBrains Mono is fetched only for plans that show code), `chat_thread` (a team-chat window, or a phone with typing dots before replies), `line_chart` (a trend over time, line or area, drawn left to right with the key point called out) and `decision` (an if/then rule branching into two outcomes, as a tree or rows). All work in every style and format and in right-to-left languages; the gallery checks pass for all of them.

- **Image scenes**: a new `image_caption` scene type (full, split and framed layouts, Ken Burns drift, every style and format, mirrored in RTL). Images come only from the request: `context.images` (`--image REF::ABOUT` on the CLI) with https URLs, uploads (`POST /v1/images`, content-addressed), `brand:<n>` site images found by the brand probe, or local files outside the service. The planner is offered the scene type only when images are listed and must use the listed refs; the bytes are checked (PNG/JPEG/WebP/GIF, 15 MB, no SVG), URLs go through the private-address guard, and images are copied into the project so renders stay offline.

- **Right-to-left languages** (Farsi, Arabic, Hebrew, Urdu and other RTL `lang` codes): mirrored layouts, right-aligned text, timelines and bars that grow from the right, swapped top bar, Latin words kept in reading order inside RTL headlines, no letter-spacing for Arabic script, and overflow checks on the left edge. One-sided CSS moved to logical properties (identical in left-to-right). Direction is set on the composition root, because HyperFrames renders a blank video when the document itself is rtl (its own check caught this). `kinetry gallery --lang fa` audits every layout mirrored.
- **Running as a service**: `callback_url` on video jobs (one signed POST when the job finishes, HMAC-SHA256, retried, public addresses only, no redirects); upload of finished videos to S3-compatible storage with a pre-signed link (`KINETRY_S3_BUCKET`, `kinetry[s3]`); `deploy/install.sh` + `kinetry.service` to run under systemd without Docker on Ubuntu 22.04/24.04 and Debian 12, tested end to end by the new **Install without Docker** workflow. `docker/smoke.py --url` checks any running server. Guide: docs/DEPLOY.md.
- **Sources from Word, PowerPoint, PDF and web pages** (`pip install 'kinetry[docs]'`): `load_source`, the CLI and `POST /v1/sources` / `POST /v1/sources/url`. Sections follow Word headings, slides (with speaker notes), PDF bookmarks or page groups (running headers and footers removed), and page headings; `kinetry sections` lists them. Office files are checked for decompression bombs, web pages go through the private-address guard in service mode. Not supported yet, with clear errors: scanned PDFs, .doc/.ppt, SCORM/Common Cartridge zips, and sources over 12,000 words (no summarizing yet; plan a section at a time).
- **Live checks**: `kinetry check-llm` (a real model through the creative director and script writer, failing loudly instead of falling back to keyword rules; `--render` for a full video) and `kinetry check-voices` (any voices, listened back with Inworld STT). A manual **Live checks** workflow runs them with repository secrets, plus a live website brand probe that needs no keys.
- Fixed: the voice check compared only the letters a-z, so every line in Japanese, Chinese, Hindi, Farsi or Arabic scored a perfect match, and accented words were split. It now compares words in any script (characters for Chinese, Japanese and Korean), and transcribes in the script's language instead of English.
- **Languages beyond English**, tested end to end in Spanish, Chinese, Hindi and Japanese:
  - With no voice chosen, the narrator and dialogue speakers switch to Kokoro voices in the script's language (`design.lang`); a mismatched chosen voice is logged as a warning.
  - Japanese with a Kokoro voice now stops with a clear error: Kokoro's pronunciation step reads kanji as "Japanese letter". Use a cloud voice.
  - Chinese and Japanese headlines are revealed by character (they used to be one unbreakable "word" that couldn't wrap) and captions break at 。、！？ instead of spaces.
  - Plan and catalog length limits count visual width (CJK 2, combining marks 0), so Hindi labels aren't rejected and CJK text can't be twice too long.
  - The Docker image adds Noto fonts for CJK, Devanagari, Arabic, Thai and more (it had Latin, Greek and Cyrillic only); the smoke test checks they're installed.
- Fixed: the checklist's stacked layout in 16:9 and 1:1 reserved 40% of the stage height for the headline, so it always overflowed and ended as needs_review.
- **Output quality setting**: `quality` = `draft` | `standard` | `high` | a CRF number, on `render`/`generate`, `--quality`, the HTTP and MCP/LangChain video requests, and `KINETRY_QUALITY`. The new default, `standard` (CRF 22), makes files 1.7-2.4x smaller than before with no visible difference (SSIM 0.997 or better against a near-lossless reference); `high` is the previous output. The render step logs the file size. See docs/QUALITY.md.
- **Docker image tested in CI**: every pull request builds the image, starts the service and renders a short video through the HTTP API (`docker/smoke.py`). Fixed on the way: the Kokoro voice model was warmed as root, so the service user (uid 10001) couldn't see it and would download it again on the first job; Chrome now gets `--disable-dev-shm-usage` for Docker's small shared memory; HyperFrames telemetry and update checks are off in the image.
- **Inworld voices**: `inworld:<voice_id>` or `inworld:<model>:<voice_id>` with `inworld-tts-2` (default), `inworld-tts-2-flash` and `inworld-tts-1` (retired by Inworld, rerouted). Same key and policy rules as the other cloud voices. `kinetry voices kokoro|inworld` lists voices.
- **Inworld speech to text (`inworld-stt-1`)**: audio and video recordings work as sources (`kinetry plan talk.mp4`, `kinetry transcribe`), and an optional **voice check** transcribes every narrated line and flags ones that don't match the script (`--voice-check`, `voice_check=`, report.json `voice_check`).
- `kinetry check-inworld`: live test of an Inworld key (voices, cast voice ids, every TTS model, STT round trip).
- **Casts**: named characters with voices (and an avatar appearance as metadata) for role-play videos; `--cast/--speaker`, `kinetry cast --verify`, `kinetry.load_cast`.

**Design engine.** Videos no longer share one look.

- A catalog of **22 scene types** (title, chapter, closer, split_list, card_grid, icon_grid, question_cards, checklist, numbered_steps, steps_path, agenda_timeline, journey, comparison, do_dont, instead_try, bar_chart, big_stat, pull_quote, definition, sticky_tip, annotated_mock, dialogue) with **44 layouts**, **7 styles** (editorial, technical, warm, bold, minimal, corporate, classic), **7 motion packs**, **9 transitions** and **3 formats** (16:9, 9:16, 1:1): 819 scene renderings. Each scene type is a folder with a manifest that drives the planner guide, validation, the docs and the gallery.
- **Creative director** step picks style, format, transition, pacing and captions from the content, audience and brand (keyword heuristic without a model). **Layouts** are picked by code: seeded, format-aware, no back-to-back repeats.
- **Plan v2**: generic `{type, layout, data, beats}` scenes plus a `design` block. v1 plans and recordings still load (as the `classic` style).
- **Brand profiles** (`profile.json` beside a brand pack): allowed styles, pinned format, scene types to avoid or favor, voices per role, music, notes. `kinetry profile`, `PUT /v1/brands/{id}/profile`.
- **Dialogue** with a voice per speaker; **captions**; **music bed** with ducking; **Lucide icons** resolved from plain words; inverse scenes set on the brand color, with contrast checked per style.
- `kinetry catalog | gallery | preview`, design flags on `plan` and `run` (`--style --format --motion --transition --pacing --captions --seed --lang --voice-a --voice-b --music`), `GET /v1/catalog`, `design` and `voices` on plan and video requests, `list_design_options` for MCP and LangChain.
- Six golden example plans in `examples/plans/` (fictional brands).
- **Breaking (Python API):** `kinetry.VideoPlan` is now the v2 plan (`scene.type`, not `scene.kind`). Load saved v1 JSON with `kinetry.load_plan(...)` (the HTTP API still accepts v1 plans as before); the v1 model stays available as `kinetry.VideoPlanV1`.

**Hardening** (from a full review of the service):
- Voices inside a plan or a brand profile follow the same provider policy as request voices; voice ids are restricted to safe characters; a caller's voice key is used for every dialogue role and never stored.
- A caller-chosen model endpoint (`base_url`) must come with the caller's own key and doesn't follow redirects; job records strip credentials from it.
- Brand fetches re-check every redirect and every browser request against private, link-local, CGNAT, NAT64 and mapped addresses; the brand agent can only read pages on the brand's own site.
- Brand colors and font names are canonicalized before they reach CSS; plan data is escaped inside the page script.
- Brand profiles are validated (styles, scene types, motion, transition, format, pacing, voices); malformed plans return 400.
- Copy repair only rewrites the fields that failed the fit check; the fit loop now reaches the rewrite step.
- Animations are seek-order independent (identical frames for parallel render workers); fixed items stuck at preview opacity, do/don't order, the scan transition's glow, and the big-stat count-up for "1,200".

### Models and voices

- **Bring your own model**: `provider:model` specs or `LLMConfig` with your own key for Anthropic, OpenAI, Amazon Bedrock (any model or inference profile, IAM keys or a Bedrock API key), Google Gemini, Azure OpenAI, OpenAI-compatible endpoints and any LangChain provider. Separate `llm_fast` model for copy rewrites. Per-call overrides. `kinetry models <provider>` and `POST /v1/models` list what your credentials can call.
- Models without tool calling work, through a JSON-schema fallback for structured output and the brand agent.
- HTTP service: per-request `llm` and `voice_api_key`, kept in memory only and never stored or returned. Operator policy via `KINETRY_CLIENT_LLM` (off | byok | any), `KINETRY_LLM_PROVIDERS` and `KINETRY_VOICE_PROVIDERS`.
- Voices: OpenAI (`openai:<voice>`) and ElevenLabs (`elevenlabs:<voice_id>`). Service endpoints for VoiceStudio voice design and consented cloning (`KINETRY_VOICE_CLONING=1`).
- Docs: new architecture diagrams (Mermaid), `docs/ARCHITECTURE.md`, `docs/VOICES.md`, `docs/ROADMAP.md`.

## 0.1.0 (2026-10-02)

First version.

- LangGraph pipeline: brand → plan → per-beat voice → compose → layout fit loop (shrink, then LLM rewrite) → HyperFrames check → render → QA frames.
- Brand from a website: headless-Chrome probe (computed colors, CSS tokens, gradients, fonts, header logo) + brand agent + enforced contrast rules + open-font substitution. Reusable `BrandPack`.
- Python API (`Kinetry.generate/plan/brand/render`), any LangChain chat model (Bedrock default), bring-your-own TTS.
- CLI (`kinetry`), HTTP job service, MCP server, LangChain tools, Dockerfile.
- Voices: Kokoro (local), VoiceStudio (speech, voice design, consented cloning).
