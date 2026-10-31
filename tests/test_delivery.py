"""Job callbacks (signed, retried, public-only) and S3-compatible uploads. No network: mock transports."""

import json
import time
from pathlib import Path

import httpx
import pytest

from kinetry.delivery import S3Storage, notify, sign, verify
from kinetry.jobs import JobManager

PLAN = json.loads((Path(__file__).parent.parent / "examples" / "plans" / "feedback-that-lands.json").read_text())


def recorder(statuses):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(statuses[min(len(seen) - 1, len(statuses) - 1)], text="ok")

    return seen, httpx.Client(transport=httpx.MockTransport(handler))


def test_signed_payload_verifies():
    seen, client = recorder([200])
    r = notify("https://hooks.example/tf", {"job_id": "j1", "status": "done"}, secret="s3cret", client=client)
    assert r == {"status": 200, "attempts": 1, "error": None}
    req = seen[0]
    ts, sig = req.headers["x-kinetry-timestamp"], req.headers["x-kinetry-signature"]
    assert req.headers["x-kinetry-event"] == "video.finished"
    assert verify("s3cret", ts, req.content, sig)
    assert not verify("other", ts, req.content, sig)
    assert not verify(
        "s3cret", str(int(time.time()) - 3600), req.content, sign("s3cret", str(int(time.time()) - 3600), req.content)
    )


def test_retries_server_errors_not_client_errors():
    seen, client = recorder([503, 502, 200])
    r = notify("https://hooks.example/tf", {}, client=client, backoff=0)
    assert r["status"] == 200 and r["attempts"] == 3
    seen, client = recorder([404])
    r = notify("https://hooks.example/tf", {}, client=client, backoff=0)
    assert r["status"] == 404 and r["attempts"] == 1 and "x-kinetry-signature" not in seen[0].headers


def test_private_callback_targets_are_refused():
    r = notify("http://127.0.0.1:9/hook", {}, backoff=0)
    assert r["status"] is None and "non-public" in r["error"]
    with pytest.raises(ValueError, match="callback_url"):
        JobManager().start(plan=PLAN, callback_url="http://169.254.169.254/latest")
    with pytest.raises(ValueError, match="http"):
        JobManager().start(plan=PLAN, callback_url="file:///etc/passwd")


class FakeS3:
    def __init__(self):
        self.uploads = []

    def upload_file(self, path, bucket, key, ExtraArgs=None):  # noqa: N803
        self.uploads.append((Path(path).read_bytes(), bucket, key, ExtraArgs))

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        return f"https://s3.example/{Params['Bucket']}/{Params['Key']}?X-Amz-Expires={ExpiresIn}"


def test_s3_upload_and_link(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"mp4")
    s3 = FakeS3()
    out = S3Storage("videos", prefix="lms/", client=s3, expires=3600, delete_local=True).upload("job1", v)
    assert s3.uploads == [(b"mp4", "videos", "lms/job1.mp4", {"ContentType": "video/mp4"})]
    assert out["uri"] == "s3://videos/lms/job1.mp4" and "X-Amz-Expires=3600" in out["url"] and not v.exists()


def test_finished_job_uploads_then_calls_back(tmp_path, monkeypatch):
    """The whole delivery path inside the job manager, with rendering faked."""
    import kinetry.delivery as D
    from kinetry import Kinetry
    from kinetry.api import Result

    class FakeTF(Kinetry):
        def render(self, plan, *, out, run_dir=None, **kw):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"mp4")
            return Result("done", Path(out), Path(run_dir), 12.0, None, None, [])

    calls = []
    monkeypatch.setattr(
        D,
        "notify",
        lambda url, payload, **kw: calls.append((url, payload, kw)) or {"status": 200, "attempts": 1, "error": None},
    )
    monkeypatch.setenv("KINETRY_PUBLIC_URL", "https://kinetry.example")
    monkeypatch.setenv("KINETRY_CALLBACK_SECRET", "cb-secret")
    monkeypatch.setattr("kinetry.netguard.check_public_url", lambda url, allow_private=False, what="": url)
    monkeypatch.setattr("kinetry.jobs.check_public_url", lambda url, allow_private=False, what="": url)
    jm = JobManager(tf=FakeTF(workdir=tmp_path), data_dir=tmp_path / "data")
    jm.storage = S3Storage("videos", client=FakeS3())
    job = jm.start(plan=PLAN, callback_url="https://hooks.example/tf", metadata={"lesson": 4})
    done = jm.wait(job["job_id"], timeout=20, poll=0.05)
    for _ in range(100):  # delivery runs right after the status turns done
        done = jm.get(job["job_id"])
        if "callback" in done:
            break
        time.sleep(0.05)
    assert done["status"] == "done" and done["storage"]["uri"].endswith(f"{job['job_id']}.mp4")
    url, payload, kw = calls[0]
    assert url == "https://hooks.example/tf" and kw["secret"] == "cb-secret"
    assert payload["video_url"] == f"https://kinetry.example/v1/videos/{job['job_id']}/video"
    assert payload["metadata"] == {"lesson": 4} and payload["storage"]["url"].startswith("https://s3.example/")
    assert done["callback"]["status"] == 200
