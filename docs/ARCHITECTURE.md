# How Kinetry works

Kinetry has two halves. **LLM steps** decide what to say, how the brand looks and which look fits. A **deterministic renderer** turns those decisions into frames. The model never writes HTML or animation code, so any capable model gives a correct video, and the same plan, brand and voice always give the same frames.

```mermaid
flowchart TB
    SRC["<b>Content</b><br/>lesson, guide, policy"]
    WEB["<b>Brand source</b><br/>website or saved pack"]

    subgraph LLM["LLM steps · any provider · recorded for replay"]
        direction LR
        BRAND["<b>Brand agent</b><br/>colors, fonts, logo"]
        DIR["<b>Creative director</b><br/>style, format, pacing"]
        PLAN["<b>Planner</b><br/>script + catalog scenes"]
    end
    CAT["<b>Catalog</b><br/>29 scene types · 59 layouts<br/>7 styles · 9 transitions<br/>+ opt-in motion layers"]
    PROF["<b>Brand profile</b><br/>allowed styles, voices, music"]

    REV["<b>Reviewed plan</b><br/>plan.json"]
    VOX["<b>Voice</b><br/>Kokoro, VoiceStudio,<br/>OpenAI, ElevenLabs"]

    subgraph DET["Deterministic renderer"]
        TTS["<b>Voice each beat</b><br/>measure real durations"]
        COMP["<b>Compose scenes</b><br/>each item appears as it is spoken"]
        FIT{"Does every<br/>line fit?"}
        FIX["<b>Fix the overflow</b><br/>1. shrink type one step<br/>2. at the smallest size,<br/>a fast LLM shortens the copy"]
        RENDER["<b>Check + render</b><br/>HyperFrames, Chrome, FFmpeg<br/>+ music bed with ducking"]
    end

    OUT["<b>MP4</b> + QA frames + report.json"]
    NR["needs_review"]

    SRC --> DIR
    WEB --> BRAND --> DIR
    PROF --> DIR
    CAT --> DIR & PLAN
    DIR -- Design --> PLAN
    PLAN -- "VideoPlan<br/>(layouts picked by code)" --> TTS
    REV -. "skip planning" .-> TTS
    VOX --> TTS
    BRAND -- BrandKit --> COMP
    TTS --> COMP --> FIT
    FIT -- yes --> RENDER --> OUT
    FIT -- no --> FIX --> COMP
    FIT -. "still too long<br/>after 4 rounds" .-> NR

    classDef input fill:#eef2ff,stroke:#6366f1,color:#1e1b4b
    classDef llm fill:#fff7ed,stroke:#ea580c,color:#431407
    classDef det fill:#ecfeff,stroke:#0891b2,color:#083344
    classDef out fill:#f0fdf4,stroke:#16a34a,color:#052e16
    classDef fix fill:#fff7ed,stroke:#0891b2,color:#083344,stroke-dasharray:4 3
    classDef warn fill:#fef2f2,stroke:#dc2626,color:#450a0a
    class SRC,WEB,REV,VOX,CAT,PROF input
    class PLAN,BRAND,DIR llm
    class FIX fix
    class TTS,COMP,FIT,RENDER det
    class OUT out
    class NR warn
    style LLM fill:#fffbf5,stroke:#fdba74
    style DET fill:#f7feff,stroke:#67e8f9
```

| Step | What it does | Uses an LLM? | Output |
|---|---|---|---|
| Brand agent | Reads the site (real browser, computed styles, logo), checks contrast and font availability with tools, picks colors and fonts. | yes (`llm`) | `BrandKit` + logo, saved as a brand pack (with an optional `profile.json`) |
| Creative director | Picks the style, format, transition, pacing and captions from the content, audience and brand, within the brand profile's limits; names scene types that suit the content. Falls back to a keyword heuristic with no model. Anything the request sets wins. | yes (`llm`), optional | `Design` |
| Planner | Turns the content into narration beats and catalog scenes. Its guide is generated from the component manifests; the catalog validates every field, limit, reveal key and dialogue voice, and errors go back to the model. | yes (`llm`) | `VideoPlan` v2 (JSON you can review and edit) |
| Layout picker | Chooses each scene's layout: only layouts that support the format, nudged by the style, never the same layout twice in a row for a type, seeded so reruns match. | no | layouts filled in |
| Brand rules | Darkens text until it passes WCAG AA, swaps proprietary fonts for open ones, drops a logo that won't show up. | no | the kit actually used |
| Voice | Speaks each beat separately (dialogue lines in each speaker's voice) and measures its real length. | no | WAV per beat, timeline |
| Compose | Renders each scene's template with the style's tokens, the motion pack and the transition. Each item appears on the beat that mentions it. | no | HTML + GSAP timeline |
| Fit check | Measures every text field in Chrome: line count, overflow, single-word last lines. | no | list of problems |
| Fix the overflow | Shrinks type one step where the template allows it. At the smallest size, asks a model to shorten the copy. | only for rewrites (`llm_fast`) | updated composition |
| Check + render | HyperFrames lint, then render with Chrome and FFmpeg, then a QA frame per scene. | no | MP4, PNGs, `report.json` |
| Music | Loops a music bed under the voice, fades it, and ducks it with a sidechain compressor. | no | MP4 with the mix |

Every model output is saved under `<run>/llm/`. Running with `--replay <dir>` (or `KINETRY_LLM=replay`) reuses them with no model calls, which is how CI renders real videos without keys.

## The design engine

```mermaid
flowchart LR
    M["<b>Component manifests</b><br/>fields · limits · reveal keys<br/>layouts × formats · example"]
    S["<b>Style packs</b><br/>tokens: ground, type, fonts,<br/>radius, shadow, chrome"]
    K["<b>BrandKit</b><br/>colors, fonts, logo"]
    M --> G["planner guide"] & V["validation"] & D["docs/CATALOG.md"] & GAL["gallery"]
    S & K --> T["<b>tokens</b><br/>contrast-checked palette<br/>+ inverse palette, type scale"]
    T & M --> R["<b>render</b><br/>template + style.css<br/>+ motion pack + transition"]
    classDef a fill:#eef2ff,stroke:#6366f1,color:#1e1b4b
    classDef b fill:#ecfeff,stroke:#0891b2,color:#083344
    class M,S,K a
    class G,V,D,GAL,T,R b
```

- **A scene is data.** `{type, layout, data, beats}`. The component's manifest says which fields exist, their limits, which keys a beat can reveal, and which layouts work in which format. One manifest feeds the planner, validation, docs and the gallery, so they can't drift apart.
- **Styles are tokens.** Each style sets the ground (brand tint, paper, white, dark), a type scale by role, which brand font plays which role, radius, shadow, chrome and inverse scenes. Brand colors pass through contrast checks for each style, so a dark style with a dark brand color still reads.
- **Formats are variables.** One template serves 16:9, 9:16 and 1:1 through scale and safe-area variables; layouts declare which formats they support.
- **Motion is a shared API.** Templates call `head`, `text`, `item`, `card`, `mark`, `emph`, `line` and `out`; each motion pack implements them, so swapping the pack changes how everything moves without touching templates.
- **Motion layers are separate and opt-in.** Camera rigs wrap the stage, ambient light sits in the ground, and kinetic type wraps the motion pack. With `effects` off none of it reaches the page. Ambient strength is computed per ground so text keeps its contrast, and every "random" placement comes from a PRNG seeded by the scene id.
- **Fit stays measurable.** Every text element carries `data-field` and `data-max-lines`; the fit loop measures the real layout and shrinks type by role before asking a model to rewrite.

## Choosing models

Two roles, each any provider:

- `llm`: planning and branding. These need a strong model.
- `llm_fast`: copy rewrites in the fit loop. Small, frequent jobs, so a cheaper model is fine. Defaults to `llm`.

A model is a `provider:model` spec, an `LLMConfig` (to pass your own key, endpoint or AWS credentials) or any LangChain chat model. Models without tool calling still work: structured output falls back to a JSON-schema prompt, and the brand agent gets its evidence up front instead of through tools.

## Where Kinetry sits

```mermaid
flowchart LR
    subgraph CALLERS["Your platform"]
        direction TB
        PY["Python service<br/>or batch worker"]
        ANY["Any language<br/>or a queue"]
        AGENT["LangChain /<br/>LangGraph agent"]
        MCPC["MCP client<br/>Claude, Cursor"]
    end

    subgraph TF["Kinetry"]
        direction TB
        SVC["HTTP service<br/><code>kinetry serve</code>"]
        LCT["LangChain tools"]
        MCPS["MCP server"]
        JOBS["JobManager<br/>start and poll"]
        API["Python API<br/><code>Kinetry()</code>"]
    end

    subgraph YOURS["Bring your own"]
        direction TB
        MODELS[("LLM<br/>Anthropic, OpenAI, Bedrock,<br/>Google, Azure, compatible")]
        VOICES[("Voices<br/>Kokoro, VoiceStudio,<br/>OpenAI, ElevenLabs")]
    end

    PY --> API
    ANY -- REST --> SVC --> JOBS
    AGENT --> LCT --> JOBS
    MCPC --> MCPS --> JOBS
    JOBS --> API
    API --> MODELS
    API --> VOICES

    classDef caller fill:#eef2ff,stroke:#6366f1,color:#1e1b4b
    classDef tf fill:#ecfeff,stroke:#0891b2,color:#083344
    classDef ext fill:#fff7ed,stroke:#ea580c,color:#431407
    class PY,ANY,AGENT,MCPC caller
    class SVC,LCT,MCPS,JOBS,API tf
    class MODELS,VOICES ext
    style CALLERS fill:#f8f9ff,stroke:#a5b4fc
    style TF fill:#f7feff,stroke:#67e8f9
    style YOURS fill:#fffbf5,stroke:#fdba74
```

Rendering takes minutes, so everything except the Python API is start-and-poll:

```mermaid
sequenceDiagram
    autonumber
    participant P as Your platform
    participant S as Kinetry service
    participant L as Your LLM
    P->>S: POST /v1/brands {url, llm?}
    S->>L: brand agent
    S-->>P: brand_id (cache per client)
    P->>S: POST /v1/plans {source, brand_id?, design?, llm?}
    S->>L: creative director, then planner
    S-->>P: VideoPlan JSON
    Note over P: editor reviews and edits the plan
    P->>S: POST /v1/videos {plan, brand_id, voice, voices?, design?, llm?}
    S-->>P: 202 {job_id}
    loop every few seconds
        P->>S: GET /v1/videos/{job_id}
        S-->>P: running · step=voice | compose | render
    end
    S-->>P: done · video_url, frame_urls
    P->>S: GET video_url
```
