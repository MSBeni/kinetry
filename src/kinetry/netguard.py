"""Keep caller-supplied URLs on the public internet.

The service fetches brand websites and talks to caller-chosen model endpoints. Without a guard a caller
could point those at internal hosts (cloud metadata, admin panels). Every check here resolves the host and
rejects any address that isn't globally routable, including IPv4 hidden inside IPv6 (mapped, NAT64, 6to4).
The checks run on the first URL, on every redirect hop (httpx hook) and on every request the brand
probe's browser makes (see js/brand_probe.mjs).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")
_6TO4 = ipaddress.ip_network("2002::/16")


def is_public_ip(ip: str | ipaddress._BaseAddress) -> bool:
    a = ipaddress.ip_address(ip) if isinstance(ip, str) else ip
    if isinstance(a, ipaddress.IPv6Address):
        if a.ipv4_mapped is not None:
            return is_public_ip(a.ipv4_mapped)
        if a in _NAT64 or a in _NAT64_LOCAL:
            return is_public_ip(ipaddress.IPv4Address(int(a) & 0xFFFFFFFF))
        if a in _6TO4:
            return is_public_ip(a.sixtofour)
        if a.teredo is not None:
            return all(is_public_ip(x) for x in a.teredo)
    return a.is_global and not a.is_multicast


def check_public_url(url: str, allow_private: bool = False, what: str = "URL") -> str:
    """http(s) only; unless `allow_private`, every address the host resolves to must be public."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"{what} must be http(s)")
    if allow_private:
        return url
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {u.hostname}") from e
    for info in infos:
        if not is_public_ip(info[4][0]):
            raise ValueError(f"{u.hostname} resolves to a non-public address")
    return url


def guard_hook(request) -> None:
    """httpx `event_hooks={"request": [guard_hook]}`: re-checks every request, redirects included."""
    check_public_url(str(request.url), what="redirect target")


# ---------------------------------------------------------------- connections pinned to checked addresses
# A host can resolve to a public address when it's checked and to an internal one a moment later, when the
# client connects (DNS rebinding). So clients made by `public_client` resolve the name once, check every
# address, and connect to the address they checked. TLS still verifies the certificate for the host name.
# Requests through a configured proxy (HTTP(S)_PROXY) connect to the proxy; there the proxy resolves the host,
# so deployments that need this guarantee should also block private ranges at the network level (DEPLOY.md).


def _backend():
    import httpcore

    class PublicOnlyBackend(httpcore.SyncBackend):
        def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            try:
                infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except socket.gaierror as e:
                raise httpcore.ConnectError(f"cannot resolve {host}") from e
            ips = list(dict.fromkeys(info[4][0] for info in infos))
            if not ips or not all(is_public_ip(ip) for ip in ips):
                raise httpcore.ConnectError(f"{host} resolves to a non-public address")
            last: Exception | None = None
            for ip in ips:
                try:
                    return super().connect_tcp(
                        ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                    )
                except httpcore.ConnectError as e:
                    last = e
            raise last or httpcore.ConnectError(f"cannot connect to {host}")

    return PublicOnlyBackend()


def public_client(**kwargs):
    """An httpx.Client for caller-supplied URLs: every request (redirects included) is checked, and every
    connection goes to the address that was checked."""
    import httpx

    # connection settings belong to the transport, which we build ourselves, so hand them to it
    conn = {k: kwargs.pop(k) for k in ("verify", "cert", "http1", "http2", "limits") if k in kwargs}
    if "trust_env" in kwargs:
        conn["trust_env"] = kwargs["trust_env"]
    transport = httpx.HTTPTransport(**conn)
    transport._pool._network_backend = _backend()  # httpcore's pool takes its backend from here
    hooks = dict(kwargs.pop("event_hooks", None) or {})
    hooks["request"] = [guard_hook, *hooks.get("request", [])]
    return httpx.Client(transport=transport, event_hooks=hooks, **kwargs)


def client(public_only: bool, **kwargs):
    """`public_client` when caller-supplied URLs must stay public, else a plain httpx.Client."""
    import httpx

    return public_client(**kwargs) if public_only else httpx.Client(**kwargs)


def get_capped(c, url: str, max_bytes: int, *, too_big: str = "") -> tuple[bytes, object]:
    """GET `url` with client `c`, reading at most `max_bytes` (after decompression) -> (body, response).
    Over the cap: ValueError(too_big) if given, else the body is cut at the cap."""
    with c.stream("GET", url) as r:
        r.raise_for_status()
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > max_bytes:
                if too_big:
                    raise ValueError(too_big)
                del buf[max_bytes:]
                break
        return bytes(buf), r


def text_of(body: bytes, response) -> str:
    return body.decode(getattr(response, "encoding", None) or "utf-8", errors="replace")
