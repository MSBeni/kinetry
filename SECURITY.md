# Security

## Reporting a vulnerability

Please report security problems privately, through GitHub's **Report a vulnerability** button on the repository's Security tab. Don't open a public issue for them. Include what you found, how to reproduce it, and what it affects.

Supported versions: the latest release and `main`.

## Notes for operators

- **HTTP service auth:** set `KINETRY_API_KEY`. Without it the service only answers localhost.
- **Brand probing loads arbitrary URLs in Chrome.** The service refuses non-http(s) URLs and hosts that resolve to private, loopback or link-local addresses (blocks cloud metadata endpoints). Every other outside fetch (pages, images, 3D models, callbacks, model endpoints) goes through the same check, every connection goes to the address that was checked (no DNS rebinding), and response bodies are read only up to what Kinetry keeps. See [docs/DEPLOY.md](docs/DEPLOY.md#outbound-requests) for deployments behind an outbound proxy. Only set `KINETRY_ALLOW_PRIVATE_URLS=1` on trusted internal deployments.
- **Callers' models and keys:** `KINETRY_CLIENT_LLM` (`off` | `byok` | `any`) and `KINETRY_LLM_PROVIDERS` decide whether callers may bring their own model. A key sent with a request is used for that request only: never stored, logged or returned.
- **Voices:** `KINETRY_VOICE_PROVIDERS` narrows which voice providers callers may use. Cloud voices need the caller's own key (`voice_api_key`); the operator's key is lent only when `KINETRY_CLIENT_LLM=any`. VoiceStudio credentials come from the server environment, never from requests.
- **Voice cloning** is off unless `KINETRY_VOICE_CLONING=1`, and requires a consent recording and statement from the speaker; the clone is deleted if storing consent fails.
- **Uploads** are checked by type and size (images 15 MB, Lottie 3 MB, 3D models 25 MB, audio 20 MB, documents 50 MB).
- **Files:** job and brand IDs are validated as alphanumeric; the API never returns server file paths.
- **Secrets:** AWS credentials come from the standard AWS chain (env, profile, instance role). Never commit `.env` files.
