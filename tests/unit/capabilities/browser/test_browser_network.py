from __future__ import annotations

import asyncio
import socket

import pytest

from sebastian.capabilities.tools.browser.network import BrowserDNSResolver
from sebastian.capabilities.tools.browser.proxy import (
    FilteringProxy,
    ProxyDecision,
    UpstreamProxyConfig,
    _ProxyRequest,
)
from sebastian.capabilities.tools.browser.safety import BrowserSafetyError


@pytest.mark.asyncio
async def test_resolver_rejects_private_answer() -> None:
    resolver = BrowserDNSResolver(resolve=lambda host: ["10.0.0.5"])

    with pytest.raises(BrowserSafetyError):
        await resolver.resolve_public("safe-looking.example")


@pytest.mark.asyncio
async def test_resolver_rejects_ipv6_private_answer() -> None:
    resolver = BrowserDNSResolver(resolve=lambda host: ["fc00::1"])

    with pytest.raises(BrowserSafetyError):
        await resolver.resolve_public("safe-looking.example")


@pytest.mark.asyncio
async def test_resolver_rejects_cname_to_private_answer() -> None:
    resolver = BrowserDNSResolver(resolve=lambda host: ["203.0.113.10", "127.0.0.1"])

    with pytest.raises(BrowserSafetyError):
        await resolver.resolve_public("cname-to-private.example")


@pytest.mark.asyncio
async def test_resolver_blocks_empty_answer() -> None:
    resolver = BrowserDNSResolver(resolve=lambda host: [])

    with pytest.raises(BrowserSafetyError):
        await resolver.resolve_public("empty.example")


@pytest.mark.asyncio
async def test_resolver_blocks_nxdomain_and_other_errors() -> None:
    def raise_gaierror(host: str) -> list[str]:
        raise socket.gaierror(socket.EAI_NONAME, "no such host")

    resolver = BrowserDNSResolver(resolve=raise_gaierror)

    with pytest.raises(BrowserSafetyError):
        await resolver.resolve_public("missing.example")


@pytest.mark.asyncio
async def test_resolver_returns_all_public_answers() -> None:
    resolver = BrowserDNSResolver(resolve=lambda host: ["93.184.216.34", "2606:4700:4700::1111"])

    assert await resolver.resolve_public("example.com") == [
        "93.184.216.34",
        "2606:4700:4700::1111",
    ]


@pytest.mark.asyncio
async def test_resolver_supports_async_resolver() -> None:
    async def resolve(host: str) -> list[str]:
        return ["8.8.8.8"]

    resolver = BrowserDNSResolver(resolve=resolve)

    assert await resolver.resolve_public("example.com") == ["8.8.8.8"]


@pytest.mark.asyncio
async def test_auto_resolver_uses_system_dns_when_public() -> None:
    doh_calls: list[str] = []
    resolver = BrowserDNSResolver(
        resolve=lambda host: ["93.184.216.34"],
        doh_resolve=lambda host: doh_calls.append(host) or ["1.1.1.1"],
        dns_mode="auto",
    )

    assert await resolver.resolve_public("example.com") == ["93.184.216.34"]
    assert doh_calls == []


@pytest.mark.asyncio
async def test_auto_resolver_falls_back_to_doh_for_proxy_fake_ip() -> None:
    resolver = BrowserDNSResolver(
        resolve=lambda host: ["198.18.0.17"],
        doh_resolve=lambda host: ["93.184.216.34"],
        dns_mode="auto",
    )

    assert await resolver.resolve_public("www.example.com") == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_auto_resolver_does_not_fallback_for_private_ip() -> None:
    resolver = BrowserDNSResolver(
        resolve=lambda host: ["10.0.0.5"],
        doh_resolve=lambda host: ["93.184.216.34"],
        dns_mode="auto",
    )

    with pytest.raises(BrowserSafetyError) as exc_info:
        await resolver.resolve_public("private.example")

    assert "10.0.0.5" in str(exc_info.value)


@pytest.mark.asyncio
async def test_doh_resolver_rejects_private_answer() -> None:
    resolver = BrowserDNSResolver(
        resolve=lambda host: ["93.184.216.34"],
        doh_resolve=lambda host: ["127.0.0.1"],
        dns_mode="doh",
    )

    with pytest.raises(BrowserSafetyError):
        await resolver.resolve_public("safe-looking.example")


@pytest.mark.asyncio
async def test_auto_resolver_reports_fake_ip_when_doh_fails() -> None:
    def fail_doh(host: str) -> list[str]:
        raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")

    resolver = BrowserDNSResolver(
        resolve=lambda host: ["198.18.0.17"],
        doh_resolve=fail_doh,
        dns_mode="auto",
    )

    with pytest.raises(BrowserSafetyError) as exc_info:
        await resolver.resolve_public("proxy.example")

    assert "proxy DNS returned Fake-IP" in str(exc_info.value)


class _FakeWriter:
    def __init__(self) -> None:
        self.closed = False
        self.waited = False
        self.writes: list[bytes] = []

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited = True

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None


@pytest.mark.asyncio
async def test_proxy_aclose_closes_active_writers_and_cancels_handlers() -> None:
    proxy = FilteringProxy()
    writer = _FakeWriter()

    async def never_finishes() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(never_finishes())
    proxy._active_writers.add(writer)  # type: ignore[arg-type]
    proxy._active_tasks.add(task)

    await proxy.aclose()

    assert writer.closed is True
    assert writer.waited is True
    assert task.cancelled()


@pytest.mark.asyncio
async def test_proxy_check_connect_uses_auto_dns_fake_ip_fallback() -> None:
    resolver = BrowserDNSResolver(
        resolve=lambda host: ["198.18.0.17"],
        doh_resolve=lambda host: ["93.184.216.34"],
        dns_mode="auto",
    )
    proxy = FilteringProxy(resolver)

    decision = await proxy.check_connect("example.com", 443)

    assert decision.allowed is True
    assert decision.resolved_ips == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_proxy_check_connect_still_blocks_private_destinations() -> None:
    resolver = BrowserDNSResolver(
        resolve=lambda host: ["10.0.0.5"],
        doh_resolve=lambda host: ["93.184.216.34"],
        dns_mode="auto",
    )
    proxy = FilteringProxy(resolver)

    decision = await proxy.check_connect("private.example", 443)

    assert decision.allowed is False
    assert "forbidden IP 10.0.0.5" in decision.reason


def test_upstream_proxy_config_parses_http_url() -> None:
    config = UpstreamProxyConfig.parse("http://127.0.0.1:7890")

    assert config is not None
    assert config.scheme == "http"
    assert config.host == "127.0.0.1"
    assert config.port == 7890
    assert config.url == "http://127.0.0.1:7890"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:7890",
        "http://127.0.0.1",
        "ftp://127.0.0.1:7890",
        "http://user:pass@127.0.0.1:7890",
    ],
)
def test_upstream_proxy_config_rejects_unsupported_urls(url: str) -> None:
    with pytest.raises(ValueError):
        UpstreamProxyConfig.parse(url)


@pytest.mark.asyncio
async def test_filtering_proxy_connects_to_http_upstream_proxy_for_connect() -> None:
    calls: list[tuple[str, int]] = []
    proxy_reader = asyncio.StreamReader()
    proxy_reader.feed_data(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    proxy_writer = _FakeWriter()

    async def open_connection(host: str, port: int) -> tuple[asyncio.StreamReader, _FakeWriter]:
        calls.append((host, port))
        return proxy_reader, proxy_writer

    filtering_proxy = FilteringProxy(
        upstream_proxy="http://127.0.0.1:7890",
        open_connection=open_connection,  # type: ignore[arg-type]
    )
    request = _ProxyRequest.parse(
        b"CONNECT www.google.com:443 HTTP/1.1\r\nHost: www.google.com:443\r\n\r\n"
    )
    decision = ProxyDecision(
        allowed=True,
        host="www.google.com",
        port=443,
        resolved_ips=["142.250.72.196"],
        reason="allowed",
    )

    await filtering_proxy._connect_for_request(request, decision)

    assert calls == [("127.0.0.1", 7890)]
    assert proxy_writer.writes == [
        b"CONNECT www.google.com:443 HTTP/1.1\r\n"
        b"Host: www.google.com:443\r\n"
        b"Proxy-Connection: keep-alive\r\n"
        b"\r\n"
    ]


def test_proxy_request_preserves_absolute_form_for_http_upstream_proxy() -> None:
    request = _ProxyRequest.parse(
        b"GET http://example.com/path?q=1 HTTP/1.1\r\nHost: example.com\r\n\r\n"
    )

    assert request.to_proxy_form_header().startswith(
        b"GET http://example.com/path?q=1 HTTP/1.1\r\n"
    )
    assert request.to_origin_form_header().startswith(b"GET /path?q=1 HTTP/1.1\r\n")
