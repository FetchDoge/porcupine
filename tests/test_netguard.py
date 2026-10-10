from __future__ import annotations

import io
from unittest.mock import patch
from urllib.request import Request

import pytest

from porcupine.netguard import NetGuardError, guarded_urlopen
from porcupine.radar import fetch_url_with_meta


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "10.1.2.3", "192.168.2.3", "169.254.169.254", "[::1]", "0.0.0.0"],
)
def test_private_ip_literals_are_blocked_without_network(host):
    with patch("porcupine.netguard.build_opener") as build:
        with pytest.raises(NetGuardError):
            guarded_urlopen(Request(f"http://{host}/"), 1)
        build.assert_not_called()


def test_public_ip_literal_is_allowed():
    response = io.BytesIO(b"ok")
    response.headers = {}
    response.status = 200
    response.url = "http://93.184.216.34/"
    response.geturl = lambda: response.url
    with patch("porcupine.netguard.build_opener") as build:
        build.return_value.open.return_value = response
        result = guarded_urlopen(Request(response.url), 1)
    assert result.hop_chain == [response.url]


def test_localhost_is_blocked_by_resolution():
    with patch("porcupine.netguard.socket.getaddrinfo") as resolve:
        resolve.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
        with pytest.raises(NetGuardError):
            guarded_urlopen(Request("http://localhost/"), 1)


@pytest.mark.parametrize("url", ["ftp://93.184.216.34/x", "http://user@93.184.216.34/"])
def test_scheme_and_userinfo_are_rejected(url):
    with pytest.raises(NetGuardError):
        guarded_urlopen(Request(url), 1)


def test_redirect_to_private_host_is_rejected_before_following():
    from porcupine.netguard import _GuardedRedirectHandler

    handler = _GuardedRedirectHandler(["http://93.184.216.34/"])
    with pytest.raises(NetGuardError) as caught:
        handler.redirect_request(
            Request("http://93.184.216.34/"), None, 302, "Found", {}, "http://127.0.0.1/x"
        )
    assert caught.value.hop_chain[-1] == "http://127.0.0.1/x"


def test_fetch_url_with_meta_refuses_loopback_without_network(tmp_path):
    with patch("porcupine.netguard.build_opener") as build:
        with pytest.raises(NetGuardError):
            fetch_url_with_meta("http://127.0.0.1:9/", tmp_path, timeout=1)
        build.assert_not_called()
