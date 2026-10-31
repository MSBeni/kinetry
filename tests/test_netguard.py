"""Caller-supplied URLs stay on the public internet: checked once, connected to exactly what was checked."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kinetry import netguard


@pytest.fixture
def local_server():
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            body = b"internal secret " * 1000
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], hits
    srv.shutdown()


def fake_dns(monkeypatch, answers):
    """getaddrinfo that returns `answers` in turn (a public address first, then an internal one: rebinding)."""
    seq = iter(answers)
    real = socket.getaddrinfo

    def gai(host, port, *a, **k):
        if host != "rebind.example":
            return real(host, port, *a, **k)
        ip = next(seq, answers[-1])
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(netguard.socket, "getaddrinfo", gai)


def test_rebinding_host_is_never_connected_to(monkeypatch, local_server):
    port, hits = local_server
    # checks see a public address; the moment of connecting sees 127.0.0.1
    fake_dns(monkeypatch, ["93.184.216.34", "93.184.216.34", "127.0.0.1"])
    netguard.check_public_url(f"http://rebind.example:{port}/x")  # passes: the first answer is public
    with netguard.public_client(trust_env=False, timeout=5) as c:
        with pytest.raises(Exception, match="non-public"):
            c.get(f"http://rebind.example:{port}/latest/meta-data/")
    assert hits == []


def test_plain_client_would_have_been_fooled(monkeypatch, local_server):
    """The same trick against a check-then-connect client (what the guard used to be) reaches the internal host."""
    import httpx

    port, hits = local_server
    fake_dns(monkeypatch, ["93.184.216.34", "127.0.0.1"])
    with httpx.Client(trust_env=False, timeout=5, event_hooks={"request": [netguard.guard_hook]}) as c:
        assert c.get(f"http://rebind.example:{port}/x").status_code == 200
    assert hits == ["/x"]


def test_capped_reads_stop_at_the_cap(local_server):
    port, _ = local_server
    import httpx

    with httpx.Client(trust_env=False, timeout=5) as c:
        body, _r = netguard.get_capped(c, f"http://127.0.0.1:{port}/big", 100)
        assert len(body) == 100
        with pytest.raises(ValueError, match="too big"):
            netguard.get_capped(c, f"http://127.0.0.1:{port}/big", 100, too_big="too big")


def test_private_and_odd_addresses_are_refused():
    for ip in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:127.0.0.1", "64:ff9b::a9fe:a9fe", "fd00::1"):
        assert not netguard.is_public_ip(ip), ip
    assert netguard.is_public_ip("93.184.216.34")


def test_url_sources_never_read_local_files(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from kinetry import service
    from kinetry.jobs import JobManager
    from kinetry.sources import read_markdown

    secret = tmp_path / "secret.md"
    secret.write_text("# do not leak")
    with pytest.raises(ValueError, match="http"):
        read_markdown(str(secret), public_only=True)
    service.set_job_manager(JobManager(data_dir=tmp_path / "data"))
    monkeypatch.setenv("KINETRY_API_KEY", "k")
    c = TestClient(service.app)
    for url in (str(secret), "/etc/passwd", "/proc/self/environ", "file:///etc/passwd", "../../etc/passwd"):
        r = c.post("/v1/sources/url", json={"url": url}, headers={"Authorization": "Bearer k"})
        assert r.status_code == 400 and "leak" not in r.text and "root:" not in r.text, (url, r.text[:200])


def test_tls_still_checks_the_host_name_when_connecting_by_address(tmp_path, monkeypatch):
    import http.server
    import shutil
    import ssl
    import subprocess

    if not shutil.which("openssl"):
        pytest.skip("openssl needed to make a test certificate")
    key, cert = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "1",
         "-subj", "/CN=pinned.example", "-addext", "subjectAltName=DNS:pinned.example"],
        check=True, capture_output=True,
    )  # fmt: skip

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"hello over tls")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cert, key)
    srv.socket = sctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    real = socket.getaddrinfo
    names = ("pinned.example", "other.example")
    monkeypatch.setattr(
        netguard.socket,
        "getaddrinfo",
        lambda h, p, *a, **k: (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", p))] if h in names else real(h, p, *a, **k)
        ),
    )
    monkeypatch.setattr(netguard, "is_public_ip", lambda ip: True)  # loopback stands in for a public server
    try:
        trusted = ssl.create_default_context(cafile=str(cert))
        with netguard.public_client(trust_env=False, verify=trusted, timeout=5) as c:
            assert c.get(f"https://pinned.example:{port}/").text == "hello over tls"
            with pytest.raises(Exception, match="(?i)hostname"):  # same address, wrong name
                c.get(f"https://other.example:{port}/")
        with netguard.public_client(trust_env=False, timeout=5) as c, pytest.raises(Exception, match="(?i)verify"):
            c.get(f"https://pinned.example:{port}/")  # verification is on by default
    finally:
        srv.shutdown()
