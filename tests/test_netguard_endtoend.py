"""End-to-end netguard coverage: full redirect chains through the real opener.

Hermetic by construction: a fake transport handler replaces HTTP(S) at the
opener layer, so no socket is opened and no DNS is queried for the public
IP-literal hosts used here. The fake records every URL it is asked to
"connect" to, which is what proves a blocked hop is refused *before*
connecting: the blocked URL never appears in the record.

Threat: a guard that validates only the initial URL, or only in unit
isolation, can still be walked past by a redirect chain served by a feed.
Mechanism: run guarded_urlopen / fetch_url_with_meta against scripted
redirect chains and assert both the refusal and the connection record.
"""
from __future__ import annotations

import io
from http.client import HTTPMessage
from unittest.mock import patch
from urllib.request import HTTPHandler, HTTPSHandler, ProxyHandler, Request
from urllib.request import build_opener as real_build_opener
from urllib.response import addinfourl

import pytest

from porcupine.netguard import NetGuardError, guarded_urlopen
from porcupine.radar import fetch_url_with_meta

PUBLIC = "93.184.216.34"


def _make_transport(routes, seen):
    """Fake HTTP(S) handlers serving `routes`: url -> (status, location, body)."""

    def serve(req):
        seen.append(req.full_url)
        status, location, body = routes[req.full_url]
        headers = HTTPMessage()
        if location is not None:
            headers["Location"] = location
        response = addinfourl(io.BytesIO(body), headers, req.full_url, status)
        response.msg = ""
        return response

    class FakeHTTPHandler(HTTPHandler):
        def http_open(self, req):
            return serve(req)

    class FakeHTTPSHandler(HTTPSHandler):
        def https_open(self, req):
            return serve(req)

    return FakeHTTPHandler(), FakeHTTPSHandler()


def _install_transport(routes, seen):
    """Patch netguard's build_opener to add the fake transport to the real opener."""

    def factory(*handlers):
        return real_build_opener(*handlers, *_make_transport(routes, seen))

    return patch("porcupine.netguard.build_opener", factory)


def test_public_redirect_chain_is_followed_and_recorded():
    start = f"http://{PUBLIC}/a"
    middle = f"http://{PUBLIC}/b"
    final = f"http://{PUBLIC}/c"
    routes = {
        start: (302, middle, b""),
        middle: (302, final, b""),
        final: (200, None, b"final-body"),
    }
    seen = []
    with _install_transport(routes, seen):
        response = guarded_urlopen(Request(start), 1)
        body = response.read()
    assert body == b"final-body"
    assert response.hop_chain == [start, middle, final]
    assert seen == [start, middle, final]


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "ftp://93.184.216.34/x",
        "http://user@93.184.216.34/x",
        "http://user:secret@93.184.216.34/x",
    ],
)
def test_redirect_to_blocked_target_is_refused_before_connecting(target):
    start = f"http://{PUBLIC}/start"
    seen = []
    with _install_transport({start: (302, target, b"")}, seen):
        with pytest.raises(NetGuardError):
            guarded_urlopen(Request(start), 1)
    assert seen == [start]


def test_redirect_to_file_scheme_is_refused_before_connecting():
    # urllib's own scheme gate in http_error_302 refuses non-http(s)/ftp
    # redirect targets with HTTPError before our handler is consulted —
    # a second, independent layer. The property that matters is identical:
    # refusal happens before any connection to the target.
    from urllib.error import HTTPError

    start = f"http://{PUBLIC}/start"
    seen = []
    with _install_transport({start: (302, "file:///etc/passwd", b"")}, seen):
        with pytest.raises(HTTPError):
            guarded_urlopen(Request(start), 1)
    assert seen == [start]


def test_private_hop_mid_chain_is_refused_before_connecting():
    start = f"http://{PUBLIC}/a"
    middle = f"http://{PUBLIC}/b"
    blocked = "http://127.0.0.1/admin"
    routes = {start: (302, middle, b""), middle: (302, blocked, b"")}
    seen = []
    with _install_transport(routes, seen):
        with pytest.raises(NetGuardError) as caught:
            guarded_urlopen(Request(start), 1)
    assert caught.value.hop_chain[-1] == blocked
    assert seen == [start, middle]


def test_https_to_http_redirect_downgrade_is_refused_before_connecting():
    start = f"https://{PUBLIC}/a"
    target = f"http://{PUBLIC}/b"
    seen = []
    with _install_transport({start: (302, target, b"")}, seen):
        with pytest.raises(NetGuardError) as caught:
            guarded_urlopen(Request(start), 1)
    assert "downgrade" in str(caught.value)
    assert seen == [start]


def test_https_to_https_redirect_is_allowed():
    start = f"https://{PUBLIC}/a"
    final = f"https://{PUBLIC}/b"
    routes = {start: (302, final, b""), final: (200, None, b"secure-body")}
    seen = []
    with _install_transport(routes, seen):
        response = guarded_urlopen(Request(start), 1)
    assert response.read() == b"secure-body"
    assert seen == [start, final]


def test_redirect_limit_is_enforced_before_connecting():
    hops = [f"http://{PUBLIC}/hop{i}" for i in range(7)]
    routes = {hops[i]: (302, hops[i + 1], b"") for i in range(6)}
    seen = []
    with _install_transport(routes, seen):
        with pytest.raises(NetGuardError) as caught:
            guarded_urlopen(Request(hops[0]), 1)
    assert "redirect limit" in str(caught.value)
    assert seen == hops[:6]


def test_obfuscated_loopback_hostname_is_blocked_by_resolution():
    # 2130706433 is 127.0.0.1 in decimal form. The guard validates the
    # resolved address, not the string form, so obfuscation gains nothing.
    with patch("porcupine.netguard.socket.getaddrinfo") as resolve:
        resolve.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
        with patch("porcupine.netguard.build_opener") as build:
            with pytest.raises(NetGuardError):
                guarded_urlopen(Request("http://2130706433/"), 1)
            build.assert_not_called()


def test_environment_proxy_variables_do_not_reroute_fetches(monkeypatch):
    # With http_proxy set, urllib's default ProxyHandler would hand the
    # connection to the proxy, which resolves the host itself — voiding
    # destination validation. The guarded opener must carry an explicit
    # empty ProxyHandler so environment proxies are never consulted.
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    captured = {}

    class StubOpener:
        def open(self, request, timeout=None):
            response = io.BytesIO(b"ok")
            response.headers = {}
            response.status = 200
            response.url = request.full_url
            return response

    def factory(*handlers):
        captured["handlers"] = handlers
        return StubOpener()

    with patch("porcupine.netguard.build_opener", factory):
        guarded_urlopen(Request(f"http://{PUBLIC}/"), 1)
    proxy_handlers = [h for h in captured["handlers"] if isinstance(h, ProxyHandler)]
    assert proxy_handlers, "guarded opener must install an explicit ProxyHandler"
    assert all(h.proxies == {} for h in proxy_handlers)


def test_fetch_url_with_meta_follows_public_chain(tmp_path):
    start = f"http://{PUBLIC}/feed"
    final = f"http://{PUBLIC}/feed-final"
    routes = {start: (302, final, b""), final: (200, None, b"feed-body")}
    seen = []
    with _install_transport(routes, seen):
        meta = fetch_url_with_meta(start, tmp_path, timeout=1)
    assert meta["body"] == "feed-body"
    assert meta["how"] == "fetched"
    assert seen == [start, final]


def test_fetch_url_with_meta_refuses_redirect_to_loopback(tmp_path):
    start = f"http://{PUBLIC}/feed"
    blocked = "http://169.254.169.254/latest/meta-data"
    seen = []
    with _install_transport({start: (302, blocked, b"")}, seen):
        with pytest.raises(NetGuardError):
            fetch_url_with_meta(start, tmp_path, timeout=1)
    assert seen == [start]
