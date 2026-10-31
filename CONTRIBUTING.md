# Contributing to Kinetry

Thanks for helping. Bug reports, new scene types, styles, transitions, voices and fixes are all welcome.

## Before you start

- **Bugs:** open an issue with the command you ran, what you expected, what happened, and `kinetry doctor` output. A plan JSON or the run's `report.json` helps most.
- **Bigger changes** (a new provider, a pipeline step, an API change): open an issue first so we can agree on the shape before you build it.
- **Security problems:** don't open an issue; see [SECURITY.md](SECURITY.md).

## Set up

Requires Python 3.10+, Node.js 22+ and FFmpeg.

```bash
git clone <this repository> kinetry && cd kinetry
pip install -e ".[dev,kokoro]"
kinetry setup        # pinned HyperFrames, GSAP and a browser, into ~/.cache/kinetry
kinetry doctor
```

## Checks

```bash
ruff check src tests && ruff format --check src tests
pytest               # no Chrome, keys or model calls needed
```

Changes to rendering (components, styles, motion, transitions, the 3D stage) should also be looked at, not just tested:

```bash
kinetry demo welcome --out /tmp/welcome.mp4 --quality draft
kinetry gallery --out gallery/ --styles editorial --formats 9:16
```

CI runs lint, tests on Python 3.10 to 3.13, a Docker build, install checks and real renders from recorded model outputs.

## Recorded model outputs

Tests and CI never call a model. Model steps go through a recorder: a live run writes each output to `<run>/llm/<step>.json`, and `--replay DIR` (or `Kinetry(replay_dir=...)`) reads them back instead. To add a test that needs model output, run it once live with your own key, review the recorded JSON, and commit it under `examples/replay/` or `tests/fixtures/`.

## Adding to the catalog

- **Scene type:** a folder in `src/kinetry/design/components/<id>/` with `component.json` (fields, limits, reveal keys, layouts, an example), `template.html`, `style.css` and `motion.js`. Validation, the planner's guide, the gallery and `docs/CATALOG.md` all read the manifest. It must work in every style, all three formats and right-to-left text.
- **Style:** `src/kinetry/design/styles/<id>/style.json` (tokens) and optional `style.css`.
- After changing the catalog: `kinetry catalog --markdown > docs/CATALOG.md`.

## Ground rules

- **Keep it general.** No code specific to one company, brand or industry. Examples use fictional brands (like Fernhill Academy).
- **No real customer content, brand assets or secrets** in code, fixtures, examples or commit messages. Brand assets captured from a website belong to its owner.
- **Keys stay in memory.** Never write an API key to disk, logs, reports or responses.
- **Voice cloning needs consent** and stays off unless the operator turns it on.
- **Licenses:** only add dependencies with licenses compatible with Apache-2.0, and list them in [THIRD_PARTY.md](THIRD_PARTY.md). Code adapted from elsewhere names its source in the file and in [NOTICE](NOTICE). VoiceStudio (AGPL) stays a separate service called over HTTP.

## Pull requests

Keep each pull request to one change, with a short description of what changed and why. Contributions are accepted under the [Apache License 2.0](LICENSE), the project's license: by opening a pull request you agree your contribution is licensed under it.

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).
