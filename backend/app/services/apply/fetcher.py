"""
SSRF-safe HTTP fetcher for job postings, company homepages and job-board APIs.

A user can make the server fetch a URL (posting intake by link), so every
fetch is treated as hostile input:

* ``https`` only, default port only, no credentials in the URL, no IP-literal
  hosts, no single-label or internal-looking names;
* the host is resolved once and EVERY returned address must be public
  (same rules as the mailbox connector: app/services/email/network.py);
* the connection is pinned to the vetted address — the URL is rewritten to the
  IP while TLS SNI and certificate verification still use the host name — so
  a DNS answer that changes between check and connect cannot redirect it;
* redirects are followed manually (max 3) and every hop is re-validated;
* response size and time are capped, the content type is allow-listed, and
  proxy environment variables are ignored.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import zlib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.config import settings
from app.services.email.network import is_public_ip as _is_public_ip_obj

Resolver = Callable[[str], Awaitable[list[str]]]

_BLOCKED_NAMES = {"localhost", "localhost.localdomain", "metadata", "metadata.google.internal", "instance-data"}
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".localdomain", ".internal", ".intranet", ".lan", ".home",
    ".home.arpa", ".corp", ".private", ".test", ".invalid", ".example", ".onion", ".arpa",
)
_REDIRECT_CODES = {301, 302, 303, 307, 308}
HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
JSON_TYPES = ("application/json",)
_USER_AGENT = "CareerPlatform/1.0 (job-application assistant; fetches only pages a user submits)"


class FetchError(Exception):
    """User-safe description of why a URL was not fetched."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return _is_public_ip_obj(ip)


def validate_url(url: str, allowed_hosts: Iterable[str] | None = None) -> tuple[str, str]:
    """Return ``(normalized_url, hostname)`` or raise FetchError."""
    if not isinstance(url, str) or not url.strip() or len(url) > 2000:
        raise FetchError("Enter a link (up to 2000 characters).")
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise FetchError("That link could not be read.") from exc
    if parts.scheme.lower() != "https":
        raise FetchError("Only https:// links can be fetched.")
    if parts.username or parts.password:
        raise FetchError("Links with a username or password in them are not allowed.")
    try:
        port = parts.port
    except ValueError as exc:
        raise FetchError("That link has an invalid port.") from exc
    if port not in (None, 443):
        raise FetchError("Only links on the standard https port are allowed.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise FetchError("That link has no host name.")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise FetchError("Links to raw IP addresses are not allowed.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise FetchError("That link has an invalid host name.") from exc
    labels = host.split(".")
    if len(labels) < 2 or labels[-1].isdigit() or host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise FetchError("That host is not allowed.")
    if allowed_hosts is not None and host not in set(allowed_hosts):
        raise FetchError("That host is not allowed for this request.")
    normalized = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
    return normalized, host


def _decoder(encoding: str):
    enc = encoding.strip().lower()
    if enc in ("", "identity"):
        return None
    if enc in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if enc == "deflate":
        return zlib.decompressobj()
    raise FetchError(f"Unsupported content encoding '{enc}'.")


class SafeFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float | None = None,
        max_bytes: int | None = None,
        max_redirects: int = 3,
    ) -> None:
        self._resolver = resolver or system_resolver
        self._transport = transport
        self._timeout = timeout or settings.APPLY_FETCH_TIMEOUT_SECONDS
        self._max_bytes = max_bytes or settings.APPLY_FETCH_MAX_BYTES
        self._max_redirects = max_redirects

    async def _vetted_ip(self, host: str) -> str:
        try:
            addresses = await asyncio.wait_for(self._resolver(host), timeout=5)
        except (asyncio.TimeoutError, OSError, UnicodeError) as exc:  # asyncio.TimeoutError: Python 3.10
            raise FetchError("Could not find that website (DNS lookup failed).", retryable=True) from exc
        if not addresses:
            raise FetchError("Could not find that website (DNS lookup failed).", retryable=True)
        if any(not is_public_ip(a) for a in addresses):
            raise FetchError("That link points to a private or reserved network address.")
        v4 = [a for a in addresses if ":" not in a]
        return (v4 or addresses)[0]

    async def _hop(self, client: httpx.AsyncClient, request: httpx.Request, accept_types: tuple[str, ...]):
        """Send one request; return a redirect location (str) or (status, content type, text)."""
        response = await client.send(request, stream=True)
        try:
            if response.status_code in _REDIRECT_CODES:
                location = response.headers.get("location")
                if not location:
                    raise FetchError("The site sent a redirect without a destination.")
                return location
            if response.status_code >= 400:
                raise FetchError(
                    f"The site answered with HTTP {response.status_code}.",
                    retryable=response.status_code in {429, 500, 502, 503, 504},
                )
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype not in accept_types:
                raise FetchError(f"Unsupported content type '{ctype or 'unknown'}'.")
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self._max_bytes:
                raise FetchError("The page is too large.")
            body = bytearray()
            if response.is_stream_consumed:
                # Only in-memory responses (test transports) arrive already read.
                body.extend(response.content)
                if len(body) > self._max_bytes:
                    raise FetchError("The page is too large.")
            else:
                decoder = _decoder(response.headers.get("content-encoding", ""))
                # Raw bytes + our own bounded decompression: a small compressed
                # body can never expand past max_bytes in memory.
                async for chunk in response.aiter_raw():
                    if decoder is not None:
                        chunk = decoder.decompress(chunk, self._max_bytes + 1 - len(body))
                    body.extend(chunk)
                    if len(body) > self._max_bytes or (decoder is not None and decoder.unconsumed_tail):
                        raise FetchError("The page is too large.")
            encoding = response.encoding or "utf-8"
            try:
                text = body.decode(encoding, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return response.status_code, ctype, text
        finally:
            await response.aclose()

    async def get(
        self,
        url: str,
        *,
        allowed_hosts: Iterable[str] | None = None,
        accept_types: tuple[str, ...] = HTML_TYPES,
    ) -> FetchResult:
        allowed = set(allowed_hosts) if allowed_hosts is not None else None
        current, host = validate_url(url, allowed)
        original = current

        async with httpx.AsyncClient(
            transport=self._transport,
            trust_env=False,  # never route through env-configured proxies
            follow_redirects=False,
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 10.0)),
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": ", ".join(accept_types),
                # Ask for an uncompressed body; anything compressed anyway is
                # decompressed below with a hard output cap.
                "Accept-Encoding": "identity",
            },
        ) as client:
            for _hop in range(self._max_redirects + 1):
                ip = await self._vetted_ip(host)
                parts = urlsplit(current)
                ip_host = f"[{ip}]" if ":" in ip else ip
                pinned = urlunsplit(("https", ip_host, parts.path or "/", parts.query, ""))
                request = client.build_request(
                    "GET", pinned, headers={"Host": host}, extensions={"sni_hostname": host}
                )
                try:
                    # One deadline for the whole hop — headers AND body — so a
                    # server trickling bytes cannot hold the request open.
                    outcome = await asyncio.wait_for(self._hop(client, request, accept_types), self._timeout)
                except asyncio.TimeoutError:  # (is TimeoutError on 3.11+)
                    raise FetchError("The page took too long to load.", retryable=True) from None
                except httpx.HTTPError as exc:
                    raise FetchError("The page could not be fetched (network error or timeout).", retryable=True) from exc
                if isinstance(outcome, str):  # redirect target
                    current, host = validate_url(urljoin(current, outcome), allowed)
                    continue
                status_code, ctype, text = outcome
                return FetchResult(url=original, final_url=current, status_code=status_code, content_type=ctype, text=text)
        raise FetchError("Too many redirects.")
