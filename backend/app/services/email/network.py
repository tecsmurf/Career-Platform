"""
SSRF-safe host handling for user-supplied mail server names.
============================================================

Rules:
1. Only DNS host names are accepted — IP literals, single-label names and
   internal-looking suffixes (.local, .internal, localhost, ...) are rejected
   before any lookup.
2. The name is resolved ONCE. Every returned address must be globally routable;
   if any address is private/loopback/link-local/reserved/multicast, the host is
   rejected (defeats mixed public/private answers).
3. The caller connects to the exact IP returned here (IP pinning) and verifies
   the TLS certificate against the host name. A second, independent lookup
   never happens, which closes the DNS-rebinding window between "check" and
   "connect".
4. The port is fixed by the provider (993); users cannot choose it.
"""
import ipaddress
import re
import socket

from app.services.email.errors import (
    HostResolutionError, InvalidAccountDetails, UnsafeHostError,
)

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_NAMES = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata", "metadata.google.internal", "instance-data",
}
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".localdomain", ".internal", ".intranet", ".lan",
    ".home", ".home.arpa", ".corp", ".private", ".test", ".invalid", ".example",
    ".onion", ".arpa",
)
# IPv6 transition ranges that embed IPv4 addresses (could smuggle private v4).
_V6_TUNNEL_NETS = (
    ipaddress.ip_network("2002::/16"),       # 6to4
    ipaddress.ip_network("2001::/32"),       # Teredo
    ipaddress.ip_network("64:ff9b::/96"),    # NAT64 well-known prefix
    ipaddress.ip_network("64:ff9b:1::/48"),  # NAT64 local-use
)


def normalize_hostname(host: str) -> str:
    """Validate a user-supplied mail host name. Returns the normalized name."""
    h = (host or "").strip().lower().rstrip(".")
    if not h or len(h) > 253:
        raise InvalidAccountDetails("Enter the IMAP host name, for example imap.example.com.")

    # Reject IP literals outright (incl. bracketed IPv6) — users should give a
    # provider host name, and names are required for TLS verification anyway.
    try:
        ipaddress.ip_address(h.strip("[]"))
        raise UnsafeHostError()
    except ValueError:
        pass

    if h in _BLOCKED_NAMES or h.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeHostError()

    labels = h.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise InvalidAccountDetails("Enter a valid IMAP host name, for example imap.example.com.")
    # A numeric final label ("127.1", "10.0.0.1"-style shorthands) is never a
    # real TLD, and some resolvers treat such names as IPv4 addresses.
    if labels[-1].isdigit():
        raise UnsafeHostError()
    return h


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if any(ip in net for net in _V6_TUNNEL_NETS):
            return False
    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def resolve_public_address(host: str, port: int) -> str:
    """Resolve `host` once and return a single public IP to pin the connection to.

    Raises UnsafeHostError if ANY resolved address is non-public.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        raise HostResolutionError() from None
    if not infos:
        raise HostResolutionError()

    ipv4: list[str] = []
    ipv6: list[str] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        raw = str(sockaddr[0]).split("%", 1)[0]   # drop IPv6 zone id
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            raise UnsafeHostError() from None
        if not is_public_ip(ip):
            raise UnsafeHostError()
        (ipv4 if ip.version == 4 else ipv6).append(str(ip))

    return (ipv4 or ipv6)[0]
