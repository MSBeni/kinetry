# Output quality

`quality` picks how the finished MP4 is encoded. It never changes what is drawn, only how much detail the encoder keeps.

| Value | What it does | Use it for |
|---|---|---|
| `standard` (default) | x264 at CRF 22 | Everything you publish: LMS, web, email |
| `high` | HyperFrames' own default, CRF 16 (Kinetry's output before this setting existed) | Masters you'll edit or re-encode later |
| `draft` | ultrafast x264 at CRF 28 | Quick checks; encodes fastest but files are not smaller than `standard` |
| `0`–`51` | that exact CRF (lower = better and bigger) | Tuning, e.g. `26` for very low bandwidth |

Set it per video (`quality=` in Python, `--quality` on `kinetry run`, `"quality"` in `POST /v1/videos`, the MCP and LangChain `start_video` tools) or for every video with `KINETRY_QUALITY`.

## How the default was chosen

Two videos were rendered near-lossless (CRF 8) as references, then encoded the way HyperFrames does (x264 `medium`, no B-frames) at several CRFs and compared frame by frame with SSIM (1.0 = identical):

| Video | CRF 16 (old default) | CRF 20 | **CRF 22** | CRF 24 | CRF 26 |
|---|---|---|---|---|---|
| Capability reel, 16:9, every motion effect on (120 s) | 62.4 MB, 0.9985 | 34.7 MB, 0.9978 | **26.3 MB, 0.9974** | 20.1 MB, 0.9969 | 15.6 MB, 0.9964 |
| Editorial lesson, no effects (43 s) | 3.07 MB, 0.9995 | 2.23 MB, 0.9992 | **1.99 MB, 0.9990** | 1.82 MB, 0.9988 | 1.67 MB, 0.9984 |

The worst single frame at CRF 22 scored 0.9945. Zoomed crops of soft glows and gradients (where banding shows first) looked identical to the reference at CRF 22 and 24. CRF 22 keeps a margin below where that might start; sizes include about 158 kb/s of audio.

A real render of `examples/plans/feedback-that-lands.json` through Kinetry: `high` 4.27 MB, `standard` 2.48 MB.

Re-encoding afterwards with B-frames would save about 19% more at the same quality, but it costs a second full encode (2 minutes for the 2-minute reel on 2 CPUs), so it isn't done.
