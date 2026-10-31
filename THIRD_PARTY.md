# Third-party components

Kinetry itself is licensed under the Apache License 2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). It vendors or adapts a few small pieces (marked below); everything else is installed at setup or run time, and each keeps its own license. Using Kinetry means using these components under their terms, so check the ones that matter for your use, GSAP's especially.

| Component | Used for | License | How it arrives |
|---|---|---|---|
| [HyperFrames](https://github.com/heygen-com/hyperframes) | HTML → video rendering, checks, Kokoro TTS CLI | Apache-2.0 | `kinetry setup` (npm, pinned) |
| [GSAP](https://gsap.com) | Animation timeline in rendered compositions | [GSAP Standard "No Charge" License](https://gsap.com/standard-license): free, including commercially, but not open source; it excludes some uses (such as no-code animation builders that compete with Webflow) | `kinetry setup` (npm, pinned); **not bundled** |
| Chrome Headless Shell / Chromium | Layout measurement, brand probe, rendering | Chromium licenses | `kinetry setup` or your own browser |
| FFmpeg | Encoding | LGPL/GPL (depends on build) | system package |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via kokoro-onnx | Free local narration | Apache-2.0 (model), MIT (kokoro-onnx) | `pip install 'kinetry[kokoro]'` |
| [LangChain / LangGraph](https://github.com/langchain-ai) and provider packages (`langchain-anthropic`, `-openai`, `-google-genai`, `-aws`) | Agents, pipeline graph, model clients | MIT | pip (extras) |
| [pypdf](https://github.com/py-pdf/pypdf), [python-docx](https://github.com/python-openxml/python-docx), [python-pptx](https://github.com/scanny/python-pptx), [trafilatura](https://github.com/adbar/trafilatura), fontTools | Reading PDF, Word, PowerPoint and web pages as sources | BSD-3-Clause, MIT, MIT, Apache-2.0, MIT | `pip install 'kinetry[docs]'` (optional) |
| [VoiceStudio](https://github.com/debpalash/VoiceStudio) | Optional cloning/design voice backend | AGPL-3.0 | **not bundled**: called over HTTP as a separate service. Keep it that way; linking or embedding it would bring AGPL obligations. |
| Fonts from [Fontsource](https://fontsource.org) | Brand-matched typography and style accents (Fraunces, JetBrains Mono, Caveat) | SIL OFL / Apache (per family) | downloaded per brand and style at run time |
| [three.js](https://threejs.org) | The 3D stage (`design.effects.depth`) | MIT | `kinetry setup` (npm, pinned); copied into projects that use it |
| [lottie-web](https://github.com/airbnb/lottie-web) (light player) | Playing callers' Lottie animations in illustration scenes | MIT | `kinetry setup` (npm, pinned); copied into projects that use it |
| [Lucide](https://lucide.dev) icons (`lucide-static`) | Icons for scenes (~1,900, searchable by tag) | ISC (some shapes derive from Feather, MIT) | `kinetry setup` (npm, pinned); a handful of shapes are **vendored** in `design/icons.py` as an offline fallback ([licenses/lucide-ISC.txt](licenses/lucide-ISC.txt)) |
| `code-typing`, `terminal-simulator`, `chat-message`, `thread-message-stack`, `decline-chart`, `data-chart`, `flowchart` and `hw-pipeline` from the [HyperFrames registry](https://github.com/heygen-com/hyperframes) | The designs behind the `code_snippet`, `chat_thread`, `line_chart` and `decision` scene types | Apache-2.0 | **adapted**: rewritten as Kinetry scene types (manifest, template, CSS, motion) that take brand tokens, every style and format, and right-to-left text; each file names its source |
| `hw-scribble-transition` from the [HyperFrames registry](https://github.com/heygen-com/hyperframes) | The `scribble` scene transition | Apache-2.0 | **vendored** in `design/assets/transitions/scribble.html`, with attribution, adapted to take the brand color and frame size |

Hosted model and voice APIs (Anthropic, OpenAI, Amazon Bedrock, Google, Azure, ElevenLabs, Inworld) are called with the user's or operator's own account and are subject to those providers' terms. Content sent for planning and narration goes to the chosen provider.

Brand assets (logos, colors) captured from a website belong to that website's owner. Use them only with permission.
