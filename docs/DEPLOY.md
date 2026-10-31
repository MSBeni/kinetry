# Deploying the service

Two supported ways to run the Kinetry HTTP service. Both are tested end to end in CI on every relevant change:
the server starts, refuses requests without its key, renders a real video through the API and serves it.

| | Docker image | Without Docker (systemd) |
|---|---|---|
| Use when | containers are allowed (ECS, Kubernetes, a Docker host) | containers aren't allowed, or you want a plain VM |
| Install | `docker build -t kinetry .` | `sudo deploy/install.sh` |
| CI check | `docker` job (every PR) | **Install without Docker** workflow (Ubuntu 22.04 and 24.04) |

## Without Docker

Supported: Ubuntu 22.04, Ubuntu 24.04, Debian 12. Each render uses about 2 vCPUs and 1.5 GB of RAM for a few
minutes; size the machine for `KINETRY_WORKERS` renders at once (start with a 4 vCPU / 8 GB VM and 1 worker).

```bash
git clone <your Kinetry repository> /srv/kinetry-src
sudo /srv/kinetry-src/deploy/install.sh /srv/kinetry-src
```

The script, which is safe to re-run (re-running upgrades in place):

1. installs system packages: Python, ffmpeg, espeak-ng, fonts for every script Kinetry renders (Latin, CJK,
   Devanagari, Arabic, Thai, ...), and the libraries Chrome needs;
2. installs Node.js 22 from NodeSource if it isn't there;
3. creates a `kinetry` system user with no login shell;
4. creates a Python environment in `/opt/kinetry/venv` and installs `kinetry[all]` into it;
5. writes `/etc/kinetry/env` (only the first time) with a **new random API key**, readable by root and the
   service only;
6. installs the renderer, Chrome's headless shell and the local voice model as the `kinetry` user;
7. installs and starts `kinetry.service` and waits for `/health`.

| Path | What |
|---|---|
| `/opt/kinetry/venv` | Python environment |
| `/opt/kinetry/home` | renderer, Chrome, fonts (`KINETRY_HOME`) |
| `/var/lib/kinetry/data` | jobs, videos, brand packs (`KINETRY_DATA_DIR`) |
| `/etc/kinetry/env` | settings and keys |

Day to day:

```bash
sudo systemctl status kinetry
sudo journalctl -u kinetry -f
sudo nano /etc/kinetry/env && sudo systemctl restart kinetry
sudo grep KINETRY_API_KEY /etc/kinetry/env        # the key callers send as "Authorization: Bearer <key>"
```

The service listens on `127.0.0.1:8080`. To reach it from other machines, put a TLS reverse proxy in front
(nginx, Caddy, a load balancer) rather than binding it to a public address, and keep `KINETRY_API_KEY` set.
The unit runs with `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp` and `NoNewPrivileges`; it can only write to
`/var/lib/kinetry` and `/opt/kinetry/home`.

## Finished videos: links, storage and callbacks

By default the finished video stays on the server and is served at `GET /v1/videos/{id}/video`.

**Object storage.** Set `KINETRY_S3_BUCKET` (plus, if needed, `KINETRY_S3_PREFIX`, `KINETRY_S3_ENDPOINT_URL` for
R2/MinIO, `KINETRY_S3_REGION`) and every finished video is uploaded to `s3://<bucket>/<prefix><job_id>.mp4`. The
job then carries `storage: {uri, url, expires_at}`, where `url` is a pre-signed download link valid for
`KINETRY_S3_URL_EXPIRES` seconds (default 7 days). `KINETRY_S3_DELETE_LOCAL=1` removes the local copy after a
successful upload. Credentials come from the usual AWS chain (instance role, environment, profile); needs
`kinetry[s3]` (included in `[all]`). A failed upload is recorded on the job and the video is still served locally.

**Callbacks.** Send `"callback_url": "https://your-app/hooks/kinetry"` with `POST /v1/videos` and the service
POSTs once when the job finishes:

```json
{"event": "video.finished", "job_id": "…", "status": "done", "error": null, "duration": 48.2,
 "metadata": {"course_id": "…"}, "status_url": "https://kinetry.example/v1/videos/…",
 "video_url": "https://kinetry.example/v1/videos/…/video",
 "storage": {"uri": "s3://…", "url": "https://…", "expires_at": 1767225600}}
```

with headers `X-Kinetry-Event`, `X-Kinetry-Timestamp` and `X-Kinetry-Signature: sha256=<hex>`, the
HMAC-SHA256 of `<timestamp>.<raw body>` keyed with `KINETRY_CALLBACK_SECRET` (or `KINETRY_API_KEY` when unset).
Verify it on your side, and reject timestamps older than a few minutes:

```python
import hashlib, hmac, time

def verify(secret: str, ts: str, body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return abs(time.time() - int(ts)) < 300 and hmac.compare_digest(expected, signature)
```

Callbacks are retried on network errors and 5xx (3 attempts), not on 4xx, and don't follow redirects. Callback URLs
must resolve to public addresses unless `KINETRY_ALLOW_PRIVATE_URLS=1`. Set `KINETRY_PUBLIC_URL` so the links in
the payload are absolute. The job record keeps the outcome as `callback: {status, attempts, error}`.

## Outbound requests

The service fetches what callers point it at: brand websites, web pages, images, 3D models, callbacks and model
endpoints. Unless `KINETRY_ALLOW_PRIVATE_URLS=1`, every one of them must resolve to a public address, every
redirect is checked again, and each connection goes to the exact address that was checked, so a host can't
switch to an internal address between the check and the connection (DNS rebinding). The brand probe's browser
reaches the web only through a small local proxy that does the same. Response bodies are read only up to the
size Kinetry keeps.

When the server's outbound traffic goes through a proxy (`HTTP_PROXY`/`HTTPS_PROXY`), that proxy does the final
lookup, so the address pinning can't apply there. In that setup, and as defense in depth anywhere, block
private, loopback and link-local ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16,
fc00::/7, fe80::/10) for the service's outbound traffic at the network level: a security group, firewall or
egress policy.
