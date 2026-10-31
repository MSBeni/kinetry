# Voices and voice cloning

Each narration beat is spoken separately and measured, so any voice that returns audio works. The timeline is built from real durations.

| Voice | Where it runs | Custom voices | Cost | Good for |
|---|---|---|---|---|
| `kokoro:<voice>` | Locally, on CPU | No (54 preset voices, 28 of them English) | Free | Defaults, drafts, CI |
| `openai:<voice>` | OpenAI | No (preset voices, delivery steered by instructions) | Per character | Quick, natural narration with no setup |
| `elevenlabs:<voice_id>` | ElevenLabs | Yes, cloned or designed in ElevenLabs | Per character | Highest polish, many languages |
| `inworld:[<model>:]<voice_id>` | Inworld | Yes, cloned in your Inworld workspace | Per character | Expressive voices at lower per-character prices; `inworld-tts-2-flash` for volume |
| `voicestudio:<profile_id>` | Your own GPU server | Yes: clone and design through Kinetry | Your hardware | Voices you own and host yourself |
| your object | anywhere | — | — | A TTS your platform already pays for |

## Languages

Set the script's language with `design.lang` (`--lang es`, `"design": {"lang": "es"}`); the planner then writes in it. When no voice is chosen and the default is a Kokoro voice in another language, Kinetry switches the narrator and both dialogue speakers to Kokoro voices in the script's language:

| Language | `lang` | Narrator | Dialogue a / b | Tested |
|---|---|---|---|---|
| English | `en` | `af_heart` | `am_michael` / `af_nova` | yes |
| Spanish | `es` | `ef_dora` | `em_alex` / `ef_dora` | rendered, natural timing |
| Chinese (Mandarin) | `zh` | `zf_xiaoxiao` | `zm_yunxi` / `zf_xiaoyi` | rendered, natural timing |
| Hindi | `hi` | `hf_alpha` | `hm_omega` / `hf_beta` | rendered, natural timing |
| French | `fr` | `ff_siwis` (Kokoro's only French voice, for all speakers) | | pronunciation checked |
| Italian | `it` | `if_sara` | `im_nicola` / `if_sara` | pronunciation checked |
| Portuguese (Brazil) | `pt` | `pf_dora` | `pm_alex` / `pf_dora` | pronunciation checked |
| **Japanese** | `ja` | **not with Kokoro**: use `inworld:`, `openai:` or `elevenlabs:` | | broken locally |

Kokoro reads text through espeak-ng, which can't read Japanese kanji (it says the words "Japanese letter" instead), so a Japanese script with a Kokoro voice stops with a clear error rather than producing that audio. A voice you choose yourself is always kept; if its language doesn't match the script, the voice step logs a warning. Languages Kokoro doesn't cover (German, Korean, Arabic, ...) keep the default voice with a warning: use a cloud voice for them.

On screen, Chinese and Japanese text is revealed and captioned by character instead of by word (punctuation stays with the character before it), and length limits count visual width: CJK characters count 2, accents and Hindi vowel signs 0. The Docker image and the systemd install ship Noto fonts for CJK, Devanagari, Arabic, Hebrew, Thai and other scripts.

### Right-to-left: Farsi, Arabic, Hebrew, Urdu

With `lang` set to `fa`, `ar`, `he` or `ur` (also `ps`, `sd`, `yi`, `ug`, `ckb`, `dv`) the whole video is laid out right to left: text aligns right, side-by-side layouts mirror, timelines and progress bars run from the right, the top bar swaps sides, and captions put punctuation where readers expect it. Latin words inside the text ("Microsoft Outlook", "v2.0") stay in reading order. Arabic-script languages get no letter-spacing, which would break the joined letters. Tested by rendering every scene type mirrored and short videos in all four languages.

Kokoro has no voice for these languages, so use a cloud voice; Inworld lists Farsi among its supported languages (`kinetry voices inworld --lang fa` shows the voices on your account). Without one, the voice step logs a warning.

## Is cloning with VoiceStudio feasible?

Yes. The code is in place and tested against VoiceStudio's API contract (`kinetry voice-clone`, `POST /v1/voices/clone`). It hasn't yet been run against a live VoiceStudio server, because that needs a GPU machine. What it takes:

1. **A VoiceStudio server.** Run it on a machine with an NVIDIA GPU. It can run on CPU, but too slowly for a 90-second narration. Run it as its own service (it's AGPL-3.0). Set `KINETRY_VOICESTUDIO_URL` and `KINETRY_VOICESTUDIO_API_KEY`.
2. **A reference recording.** 10–30 seconds of the speaker talking naturally, with no music or room echo. A transcript (`ref_text`) improves results.
3. **The speaker's consent.** A recording of the speaker reading a consent statement, plus the statement's text. Kinetry refuses to clone without it. If the consent upload fails, it deletes the new profile, so no unconsented voice is left behind.
4. **A test render.** Clone, render one lesson, listen. Zero-shot clones vary with the reference audio, so try two or three reference clips.

```bash
kinetry voice-clone --name "Dana" --ref dana-30s.wav --ref-text "…what Dana says in the clip…" \
  --consent-audio dana-consent.wav --consent-text "I, Dana Lee, agree to my voice being used for training videos."
# -> {"id": "3f9a2c1d", ...}
kinetry run lesson.md --voice voicestudio:3f9a2c1d --out lesson.mp4
```

Over HTTP (operator sets `KINETRY_VOICE_CLONING=1`):

```bash
curl -X POST $TF/v1/voices/clone -H "Authorization: Bearer $KEY" \
  -F name=Dana -F ref_audio=@dana-30s.wav -F consent_audio=@dana-consent.wav \
  -F "consent_text=I, Dana Lee, agree to my voice being used for training videos."
# -> {"voice": "voicestudio:3f9a2c1d", ...}   use it as "voice" in POST /v1/videos
```

**Designed voices** need no recording: `POST /v1/voices/design {"name": "Coach", "description": "male, middle-aged, low pitch, british accent"}`. They suit a consistent "course narrator" without involving a real person.

**ElevenLabs instead?** If you'd rather not host a GPU, clone the voice in ElevenLabs (it runs its own consent and verification) and use `elevenlabs:<voice_id>` here.

## Rules worth keeping

- Clone only people who agreed, in writing and on a recording, and keep that consent with the profile.
- To revoke a voice, delete the profile in VoiceStudio; videos rendered earlier keep their audio.
- Don't clone public figures or anyone who can't consent.
- Tell learners when a narrator's voice is synthetic, especially if it is a real colleague's.

## Inworld

`inworld:Ashley` uses Inworld's `inworld-tts-2` model; name a model first to change it: `inworld:inworld-tts-2-flash:Ashley` (fastest and cheapest) or `inworld:inworld-tts-1:Ashley`. Inworld retired TTS-1 on 2026-06-15 and reroutes those requests to a newer model, so Kinetry accepts it but logs a warning. `kinetry voices inworld --lang en` lists the voices your key can use, including voices cloned in your workspace (clone only with the speaker's consent). Long beats are split at sentence ends to stay under Inworld's 2,000-character limit per request. In dialogue scenes the two speakers default to other Inworld voices on the same model as the narrator.

### Live check

`kinetry check-inworld [--cast cast.json]` tests your key end to end: lists your voices, checks the cast's voice ids, synthesizes a sentence with each TTS model and transcribes it back with `inworld-stt-1` (pass when the transcript matches at 0.8 or better). Set `INWORLD_API_KEY` in the environment first; the test audio is kept in `./inworld-check/`.

### Casts for role-play

A cast file names each character once, with its voice and (optionally) the avatar look it has on another platform:

```json
{
  "name": "Customer conversations",
  "model": "inworld-tts-2",
  "characters": [
    {"id": "skeptic_female", "label": "The Skeptic (female)", "voice": "inworld:Ashley", "appearance": "<avatar name>"}
  ]
}
```

`model` fills in for `inworld:<voice>` entries that don't name one. Run `kinetry cast cast.json --verify` with `INWORLD_API_KEY` set: it lists every character and marks Inworld voice ids your account can't see (exit code 3 if any are missing). Then pick who plays each dialogue role: `--speaker a=skeptic_female --speaker b=newcomer_male` (`narrator=` works too).

### Speech to text: `inworld-stt-1`

Kinetry uses Inworld's `inworld/inworld-stt-1` model in two places:

- **Recordings as source content.** An audio or video file passed as the source is converted to 16 kHz mono MP3 with ffmpeg, sent to `POST /stt/v1/transcribe` (in 10-minute pieces for long recordings, with word timings stitched back together) and planned from the transcript. `--stt-lang` sets the language (default `en`).
- **Voice check.** After the voice step, every narrated clip is transcribed and compared word by word with its script (score 0 to 1; below 0.8 is flagged). This catches TTS that drops, repeats or garbles words, and numbers, names or acronyms that are read differently from how they're written. It costs one STT request per line and doesn't fail the render.

The STT key is held in memory only, like voice keys. Over HTTP the server never lends its own Inworld key for the voice check.

