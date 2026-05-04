from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from sebastian.capabilities.tools.browser.network import BrowserDNSResolver
from sebastian.capabilities.tools.browser.proxy import FilteringProxy


class _ConnectionRecorder:
    def __init__(self) -> None:
        self.connections = 0
        self.requests: list[bytes] = []
        self.server: asyncio.AbstractServer | None = None

    @property
    def port(self) -> int:
        sockets = self.server.sockets if self.server is not None else None
        assert sockets
        return int(sockets[0].getsockname()[1])

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    async def aclose(self) -> None:
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=0.5)
            self.requests.append(data)
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.fixture
async def upstream() -> _ConnectionRecorder:
    recorder = _ConnectionRecorder()
    await recorder.start()
    try:
        yield recorder
    finally:
        await recorder.aclose()


@pytest.fixture
async def proxy() -> FilteringProxy:
    resolver = BrowserDNSResolver(resolve=lambda host: ["127.0.0.1"])
    filtering_proxy = FilteringProxy(resolver=resolver)
    await filtering_proxy.start()
    try:
        yield filtering_proxy
    finally:
        await asyncio.wait_for(filtering_proxy.aclose(), timeout=2)


async def _send_raw_proxy_request(proxy: FilteringProxy, request: bytes) -> bytes:
    config = proxy.config
    reader, writer = await asyncio.open_connection(config.host, config.port)
    try:
        writer.write(request)
        await writer.drain()
        return await asyncio.wait_for(reader.read(4096), timeout=1)
    finally:
        writer.close()
        await writer.wait_closed()


async def _assert_blocked_before_upstream(
    proxy: FilteringProxy,
    upstream: _ConnectionRecorder,
    request_factory: Callable[[int], bytes],
) -> bytes:
    response = await _send_raw_proxy_request(proxy, request_factory(upstream.port))

    assert b"403" in response
    assert b"Sebastian browser proxy blocked" in response
    await asyncio.sleep(0.05)
    assert upstream.connections == 0
    assert upstream.requests == []
    return response


class _RedirectServer:
    def __init__(self, location: str) -> None:
        self.location = location
        self.connections = 0
        self.server: asyncio.AbstractServer | None = None

    @property
    def port(self) -> int:
        sockets = self.server.sockets if self.server is not None else None
        assert sockets
        return int(sockets[0].getsockname()[1])

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    async def aclose(self) -> None:
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        await reader.readuntil(b"\r\n\r\n")
        body = b"redirecting\n"
        response = (
            b"HTTP/1.1 302 Found\r\n"
            + f"Location: {self.location}\r\n".encode()
            + b"Connection: close\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"\r\n"
            + body
        )
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()


async def _read_proxy_response_headers(proxy: FilteringProxy, request: bytes) -> dict[str, str]:
    config = proxy.config
    reader, writer = await asyncio.open_connection(config.host, config.port)
    try:
        writer.write(request)
        await writer.drain()
        raw_header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=1)
    finally:
        writer.close()
        await writer.wait_closed()

    headers: dict[str, str] = {}
    for line in raw_header.decode("iso-8859-1").split("\r\n")[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.lower()] = value.strip()
    return headers


@pytest.mark.asyncio
async def test_http_absolute_form_request_to_forbidden_upstream_is_blocked(
    proxy: FilteringProxy,
    upstream: _ConnectionRecorder,
) -> None:
    await _assert_blocked_before_upstream(
        proxy,
        upstream,
        lambda port: (
            f"GET http://evil.test:{port}/secret HTTP/1.1\r\nHost: evil.test:{port}\r\n\r\n"
        ).encode(),
    )


@pytest.mark.asyncio
async def test_subresource_absolute_form_request_uses_same_blocking_path(
    proxy: FilteringProxy,
    upstream: _ConnectionRecorder,
) -> None:
    await _assert_blocked_before_upstream(
        proxy,
        upstream,
        lambda port: (
            f"GET http://evil.test:{port}/pixel.png HTTP/1.1\r\n"
            f"Host: evil.test:{port}\r\n"
            "Referer: https://public.example/\r\n"
            "\r\n"
        ).encode(),
    )


@pytest.mark.asyncio
async def test_connect_request_to_forbidden_upstream_is_blocked(
    proxy: FilteringProxy,
    upstream: _ConnectionRecorder,
) -> None:
    await _assert_blocked_before_upstream(
        proxy,
        upstream,
        lambda port: (
            f"CONNECT evil.test:{port} HTTP/1.1\r\nHost: evil.test:{port}\r\n\r\n"
        ).encode(),
    )


@pytest.mark.asyncio
async def test_websocket_upgrade_request_to_forbidden_upstream_is_blocked(
    proxy: FilteringProxy,
    upstream: _ConnectionRecorder,
) -> None:
    await _assert_blocked_before_upstream(
        proxy,
        upstream,
        lambda port: (
            f"GET ws://evil.test:{port}/socket HTTP/1.1\r\n"
            f"Host: evil.test:{port}\r\n"
            "Connection: Upgrade\r\n"
            "Upgrade: websocket\r\n"
            "\r\n"
        ).encode(),
    )


@pytest.mark.asyncio
async def test_check_connect_blocks_rebinding_at_connection_time() -> None:
    proxy = FilteringProxy(resolver=BrowserDNSResolver(resolve=lambda host: ["127.0.0.1"]))

    decision = await proxy.check_connect("evil.test", 443)

    assert decision.allowed is False
    assert decision.host == "evil.test"
    assert decision.port == 443
    assert decision.resolved_ips == []
    assert "blocked" in decision.reason.lower()


@pytest.mark.asyncio
async def test_redirect_to_forbidden_upstream_is_blocked_before_forbidden_connection(
    upstream: _ConnectionRecorder,
) -> None:
    redirect_server = _RedirectServer(f"http://evil.test:{upstream.port}/secret")
    await redirect_server.start()

    async def open_connection(
        host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if host == "93.184.216.34" and port == redirect_server.port:
            return await asyncio.open_connection("127.0.0.1", redirect_server.port)
        return await asyncio.open_connection(host, port)

    resolver = BrowserDNSResolver(
        resolve=lambda host: ["93.184.216.34"] if host == "public.test" else ["127.0.0.1"]
    )
    filtering_proxy = FilteringProxy(resolver=resolver, open_connection=open_connection)
    await filtering_proxy.start()
    try:
        headers = await _read_proxy_response_headers(
            filtering_proxy,
            (
                f"GET http://public.test:{redirect_server.port}/redirect HTTP/1.1\r\n"
                f"Host: public.test:{redirect_server.port}\r\n"
                "\r\n"
            ).encode(),
        )

        assert headers["location"] == f"http://evil.test:{upstream.port}/secret"
        response = await _send_raw_proxy_request(
            filtering_proxy,
            (
                f"GET {headers['location']} HTTP/1.1\r\nHost: evil.test:{upstream.port}\r\n\r\n"
            ).encode(),
        )

        assert b"403" in response
        assert b"Sebastian browser proxy blocked" in response
        await asyncio.sleep(0.05)
        assert redirect_server.connections == 1
        assert upstream.connections == 0
        assert upstream.requests == []
    finally:
        await filtering_proxy.aclose()
        await redirect_server.aclose()
