"""End-to-end check of the Kinetry service image, the way a client uses it.

    docker build -t kinetry:ci .
    python docker/smoke.py --image kinetry:ci --out smoke-out

    # a server installed without Docker (deploy/install.sh), on this machine:
    python docker/smoke.py --url http://127.0.0.1:8080 --key "$KINETRY_API_KEY" --expect-user kinetry

Starts the container (as its non-root user, with an API key and a named data volume), waits for /health,
checks that requests without the key are refused, submits docker/smoke-plan.json to POST /v1/videos,
polls the job, downloads the MP4 and checks it inside the container with ffprobe (video and audio
streams, sensible duration). Prints the container logs on failure. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
KEY = "ci-smoke-key-0123456789"
NAME = "kinetry-smoke"


def sh(*cmd: str, check: bool = True) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {res.stderr[-800:]}")
    return res.stdout.strip()


def call(base: str, method: str, path: str, body: dict | None = None, key: str | None = "default"):
    req = urllib.request.Request(base + path, method=method)
    if key == "default":
        key = KEY
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=60) as r:
            raw = r.read()
            return r.status, raw if not r.headers.get("content-type", "").startswith(
                "application/json"
            ) else json.loads(raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def check(ok: bool, what: str) -> None:
    print(("PASS  " if ok else "FAIL  ") + what, flush=True)
    if not ok:
        raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="kinetry:ci")
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--out", default="smoke-out")
    ap.add_argument("--timeout", type=int, default=900, help="seconds to wait for the render")
    ap.add_argument("--url", help="test a running server at this URL instead of starting the Docker image")
    ap.add_argument("--key", help="that server's KINETRY_API_KEY (with --url)")
    ap.add_argument("--expect-user", help="with --url: the service must run as this OS user")
    a = ap.parse_args()
    global KEY
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    docker = not a.url
    base = a.url.rstrip("/") if a.url else f"http://127.0.0.1:{a.port}"
    if a.key:
        KEY = a.key

    def inside(*cmd: str) -> str:  # run a command where the service runs
        return sh("docker", "exec", NAME, *cmd) if docker else sh(*cmd)

    if docker:
        sh("docker", "rm", "-f", NAME, check=False)
        sh(
            "docker", "run", "-d", "--name", NAME, "-p", f"127.0.0.1:{a.port}:8080",
            "-e", f"KINETRY_API_KEY={KEY}", "-v", "kinetry-smoke-data:/data", a.image,
        )  # fmt: skip
    try:
        for _ in range(90):
            try:
                status, body = call(base, "GET", "/health", key=None)
                if status == 200:
                    break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(2)
        else:
            check(False, "service answered /health within 3 minutes")
        check(body.get("ok") is True, f"/health ok (version {body.get('version')})")
        if docker:
            check(inside("id", "-u") == "10001", "service runs as the non-root kinetry user")
        elif a.expect_user:
            procs = sh("ps", "-eo", "user:32,args")
            ok = any(ln.split(None, 1)[0] == a.expect_user and "kinetry serve" in ln for ln in procs.splitlines())
            check(ok, f"service runs as the {a.expect_user} user")
        for lang, script in (
            ("ja", "Japanese"),
            ("zh", "Chinese"),
            ("ko", "Korean"),
            ("hi", "Hindi"),
            ("ar", "Arabic"),
        ):
            fonts = inside("fc-list", f":lang={lang}", "family")
            check(bool(fonts.strip()), f"a font for {script} text is installed")
        status, _ = call(base, "GET", "/v1/catalog", key=None)
        check(status == 401, f"requests without the API key are refused ({status})")
        status, cat = call(base, "GET", "/v1/catalog")
        check(status == 200 and len(cat.get("components", [])) > 0, "catalog served with the key")

        plan = json.loads((HERE / "smoke-plan.json").read_text())
        t0 = time.monotonic()
        status, job = call(base, "POST", "/v1/videos", {"plan": plan, "voice": "kokoro:af_heart"})
        check(status == 202 and "job_id" in job, f"video job accepted ({status})")
        jid = job["job_id"]
        last = None
        while time.monotonic() - t0 < a.timeout:
            status, job = call(base, "GET", f"/v1/videos/{jid}")
            if job.get("step") != last:
                last = job.get("step")
                print(f"      step: {last} ({time.monotonic() - t0:.0f}s)", flush=True)
            if job.get("status") not in ("queued", "running"):
                break
            time.sleep(5)
        (out / "job.json").write_text(json.dumps(job, indent=2))
        check(job.get("status") == "done", f"render finished: {job.get('status')} {job.get('error') or ''}".strip())
        print(f"      rendered in {time.monotonic() - t0:.0f}s", flush=True)

        status, mp4 = call(base, "GET", f"/v1/videos/{jid}/video")
        check(status == 200 and isinstance(mp4, bytes) and mp4[4:8] == b"ftyp", f"MP4 downloaded ({len(mp4)} bytes)")
        (out / "smoke.mp4").write_bytes(mp4)
        target = f"/data/jobs/{jid}/video.mp4" if docker else str((out / "smoke.mp4").resolve())
        probe = json.loads(
            inside(
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", target
            )
        )
        kinds = sorted(s["codec_type"] for s in probe["streams"])
        dur = float(probe["format"]["duration"])
        check(kinds == ["audio", "video"], f"video and audio streams ({kinds})")
        check(8 < dur < 60, f"duration {dur:.1f}s")
        status, png = call(base, "GET", f"/v1/videos/{jid}/frames/0")
        check(status == 200 and isinstance(png, bytes) and png[:4] == b"\x89PNG", "QA frame served")
        (out / "frame-0.png").write_bytes(png)
        check(KEY not in json.dumps(job), "job record doesn't contain the API key")
        print("\nall checks passed")
        return 0
    except BaseException:
        if docker:
            print("\n--- container logs ---")
            print(sh("docker", "logs", "--tail", "200", NAME, check=False))
            print(subprocess.run(["docker", "logs", "--tail", "200", NAME], capture_output=True, text=True).stderr)
        else:
            print("\n--- service logs ---")
            print(sh("journalctl", "-u", "kinetry", "-n", "200", "--no-pager", check=False))
        raise
    finally:
        if docker:
            sh("docker", "rm", "-f", NAME, check=False)


if __name__ == "__main__":
    sys.exit(main())
