"""Guard outbound HTTP fetches against unsafe destinations and redirects.

This reduces SSRF exposure by validating the initial URL and every redirect
target.  It does not eliminate DNS TOCTOU risk: validation-time resolution and
the HTTP client's connect-time resolution are separate and may return different
addresses.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_REDIRECT_HOPS = 5


class NetGuardError(Exception):
    """A URL failed outbound-network safety validation."""

    def __init__(self, message: str, hop_chain: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.hop_chain = list(hop_chain or [])


def _blocked_address(address: ipaddress._BaseAddress) -> bool:
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _validate_url(url: str, hop_chain: list[str]) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise NetGuardError(f"invalid URL: {exc}", hop_chain) from exc
    if parsed.scheme.lower() not in ("http", "https"):
        raise NetGuardError("URL scheme must be http or https", hop_chain)
    if parsed.username is not None or parsed.password is not None:
        raise NetGuardError("URL userinfo is not allowed", hop_chain)
    hostname = parsed.hostname
    if not hostname:
        raise NetGuardError("URL requires a hostname", hop_chain)

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise NetGuardError(f"hostname resolution failed for {hostname}: {exc}", hop_chain) from exc
        addresses = set()
        for item in resolved:
            try:
                addresses.add(ipaddress.ip_address(item[4][0]))
            except ValueError as exc:
                raise NetGuardError(f"invalid resolved address for {hostname}", hop_chain) from exc
        if not addresses:
            raise NetGuardError(f"hostname resolution returned no addresses for {hostname}", hop_chain)
    else:
        addresses = {literal}

    for address in addresses:
        if _blocked_address(address):
            raise NetGuardError(f"blocked destination address: {address}", hop_chain)


class _GuardedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, hop_chain: list[str]) -> None:
        super().__init__()
        self.hop_chain = hop_chain

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        candidate_chain = self.hop_chain + [target]
        if len(candidate_chain) - 1 > MAX_REDIRECT_HOPS:
            raise NetGuardError(
                f"redirect limit exceeded ({MAX_REDIRECT_HOPS})", candidate_chain
            )
        _validate_url(target, candidate_chain)
        redirected = super().redirect_request(req, fp, code, msg, headers, target)
        if redirected is not None:
            self.hop_chain.append(target)
        return redirected


def guarded_urlopen(request: Request, timeout: float):
    """Open a request after validating its URL and every redirect target."""
    initial_url = request.full_url
    hop_chain = [initial_url]
    _validate_url(initial_url, hop_chain)
    opener = build_opener(_GuardedRedirectHandler(hop_chain))
    try:
        response = opener.open(request, timeout=timeout)
    except NetGuardError:
        raise
    except Exception as exc:
        try:
            exc.hop_chain = list(hop_chain)
        except (AttributeError, TypeError):
            pass
        raise
    response.hop_chain = list(hop_chain)
    return response
