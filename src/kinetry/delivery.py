"""After a job finishes: put the video in object storage and tell the caller.

Object storage (optional, any S3-compatible service: AWS S3, Cloudflare R2, MinIO, ...):
    KINETRY_S3_BUCKET        bucket name (turns uploads on)
    KINETRY_S3_PREFIX        key prefix, default "kinetry/"
    KINETRY_S3_ENDPOINT_URL  for non-AWS services
    KINETRY_S3_REGION        default AWS_REGION
    KINETRY_S3_URL_EXPIRES   seconds a download link stays valid, default 604800 (7 days)
    KINETRY_S3_DELETE_LOCAL  "1" removes the local copy after a successful upload
Credentials come from the usual AWS chain (environment, profile, instance role). Needs boto3
(pip install "kinetry[s3]").

Callbacks: a job started with callback_url gets one POST when it finishes (done, needs_review, check_failed,
error), retried on network errors and 5xx. The body is JSON; the headers carry
    X-Kinetry-Event: video.finished
    X-Kinetry-Timestamp: <unix seconds>
    X-Kinetry-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<body>">
signed with KINETRY_CALLBACK_SECRET (or KINETRY_API_KEY when that isn't set). Verify the signature and
reject old timestamps on your side. Callback URLs must be public unless the server allows private URLs,
and redirects aren't followed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import httpx


# ---------------------------------------------------------------- storage
class S3Storage:
    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "kinetry/",
        endpoint_url: str | None = None,
        region: str | None = None,
        expires: int = 604800,
        delete_local: bool = False,
        client=None,
    ):
        self.bucket, self.prefix, self.expires, self.delete_local = bucket, prefix, expires, delete_local
        if client is None:
            try:
                import boto3
            except ImportError as e:
                raise RuntimeError("uploads need boto3: pip install 'kinetry[s3]'") from e
            client = boto3.client(
                "s3", endpoint_url=endpoint_url or None, region_name=region or os.environ.get("AWS_REGION") or None
            )
        self.client = client

    @classmethod
    def from_env(cls) -> S3Storage | None:
        bucket = os.environ.get("KINETRY_S3_BUCKET")
        if not bucket:
            return None
        return cls(
            bucket,
            prefix=os.environ.get("KINETRY_S3_PREFIX", "kinetry/"),
            endpoint_url=os.environ.get("KINETRY_S3_ENDPOINT_URL"),
            region=os.environ.get("KINETRY_S3_REGION"),
            expires=int(os.environ.get("KINETRY_S3_URL_EXPIRES", "604800")),
            delete_local=os.environ.get("KINETRY_S3_DELETE_LOCAL") == "1",
        )

    def upload(self, job_id: str, video: Path) -> dict:
        key = f"{self.prefix}{job_id}.mp4"
        self.client.upload_file(str(video), self.bucket, key, ExtraArgs={"ContentType": "video/mp4"})
        url = self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=self.expires
        )
        if self.delete_local:
            video.unlink(missing_ok=True)
        return {"uri": f"s3://{self.bucket}/{key}", "url": url, "expires_at": int(time.time()) + self.expires}


# ---------------------------------------------------------------- callbacks
def callback_secret() -> str | None:
    return os.environ.get("KINETRY_CALLBACK_SECRET") or os.environ.get("KINETRY_API_KEY") or None


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, body: bytes, signature: str, max_age: int = 300) -> bool:
    """For receivers (and tests): constant-time check plus a freshness window against replays."""
    try:
        fresh = abs(time.time() - int(timestamp)) <= max_age
    except ValueError:
        return False
    return fresh and hmac.compare_digest(sign(secret, timestamp, body), signature)


def notify(
    url: str,
    payload: dict,
    *,
    allow_private: bool = False,
    secret: str | None = None,
    client: httpx.Client | None = None,
    attempts: int = 3,
    backoff: float = 2.0,
) -> dict:
    """POST the payload; -> {"status": http status or None, "attempts": n, "error": ...}. Never raises."""
    from .netguard import client as make_client

    body = json.dumps(payload, default=str).encode()
    own = client is None
    client = client or make_client(not allow_private, timeout=15, follow_redirects=False)
    result: dict = {"status": None, "attempts": 0, "error": None}
    try:
        for i in range(attempts):
            ts = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                "X-Kinetry-Event": "video.finished",
                "X-Kinetry-Timestamp": ts,
            }
            if secret:
                headers["X-Kinetry-Signature"] = sign(secret, ts, body)
            result["attempts"] = i + 1
            try:
                r = client.post(url, content=body, headers=headers)
                result.update(status=r.status_code, error=None if r.status_code < 400 else r.text[:200])
                if r.status_code < 500:  # success, or a client error retrying won't fix
                    break
            except ValueError as e:  # the address guard: not a public host
                result["error"] = str(e)[:200]
                break
            except httpx.HTTPError as e:
                result["error"] = f"{type(e).__name__}: {str(e)[:160]}"
            if i + 1 < attempts:
                time.sleep(backoff * (4**i))
    finally:
        if own:
            client.close()
    return result
