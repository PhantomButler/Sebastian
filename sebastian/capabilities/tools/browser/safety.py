from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import ParseResult, urlparse, urlunparse


class BrowserSafetyError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedURL:
    url: str
    scheme: str
    hostname: str
    port: int | None
    path: str
    query: str


def is_forbidden_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise BrowserSafetyError(f"Invalid IP address: {ip!r}") from exc

    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return is_forbidden_ip(str(addr.ipv4_mapped))

    metadata_addr = ipaddress.ip_address("169.254.169.254")
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
        or addr == metadata_addr
    )


def validate_public_http_url(url: str) -> ParsedURL:
    parsed = _parse_url(url)
    if parsed.scheme not in {"http", "https"}:
        raise BrowserSafetyError("Browser URL blocked: only http and https URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise BrowserSafetyError("Browser URL blocked: username/password authority is not allowed")

    raw_host = parsed.hostname
    if raw_host is None or raw_host == "":
        raise BrowserSafetyError("Browser URL blocked: host is required")
    port = _read_port(parsed)
    host = normalize_hostname(raw_host)
    _block_forbidden_ip_literal(host)

    normalized_url = _url_with_normalized_host(parsed, host, port)
    return ParsedURL(
        url=normalized_url,
        scheme=parsed.scheme,
        hostname=host,
        port=port,
        path=parsed.path,
        query=parsed.query,
    )


def normalize_hostname(host: str) -> str:
    if not host:
        raise BrowserSafetyError("Browser URL blocked: host is required")
    if any(ch.isspace() for ch in host):
        raise BrowserSafetyError("Browser URL blocked: host contains whitespace")

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            normalized = host.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise BrowserSafetyError("Browser URL blocked: host is not valid IDNA") from exc
        if not normalized:
            raise BrowserSafetyError("Browser URL blocked: host is required")
        return normalized
    return addr.compressed.lower()


def _parse_url(url: str) -> ParseResult:
    try:
        return urlparse(url)
    except ValueError as exc:
        raise BrowserSafetyError("Browser URL blocked: malformed URL") from exc


def _read_port(parsed: ParseResult) -> int | None:
    try:
        return parsed.port
    except ValueError as exc:
        raise BrowserSafetyError("Browser URL blocked: invalid port") from exc


def _block_forbidden_ip_literal(host: str) -> None:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return
    if is_forbidden_ip(host):
        raise BrowserSafetyError(f"Browser URL blocked: destination IP {host} is forbidden")


def _url_with_normalized_host(parsed: ParseResult, host: str, port: int | None) -> str:
    display_host = f"[{host}]" if ":" in host else host
    netloc = display_host if port is None else f"{display_host}:{port}"
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path or "",
            parsed.params or "",
            parsed.query or "",
            parsed.fragment or "",
        )
    )
