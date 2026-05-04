from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sebastian.capabilities.tools.browser.network import BrowserDNSResolver
from sebastian.capabilities.tools.browser.safety import BrowserSafetyError, validate_public_http_url

logger = logging.getLogger(__name__)

OpenConnectionFn = Callable[
    [str, int],
    Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]],
]

_MAX_HEADER_BYTES = 64 * 1024
_BLOCKED_RESPONSE = (
    b"HTTP/1.1 403 Forbidden\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"X-Sebastian-Proxy-Blocked: 1\r\n"
    b"Connection: close\r\n"
    b"Content-Length: 46\r\n"
    b"\r\n"
    b"Sebastian browser proxy blocked this request.\n"
)
_BAD_REQUEST_RESPONSE = (
    b"HTTP/1.1 400 Bad Request\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"Connection: close\r\n"
    b"Content-Length: 25\r\n"
    b"\r\n"
    b"Malformed proxy request.\n"
)
_BAD_GATEWAY_RESPONSE = (
    b"HTTP/1.1 502 Bad Gateway\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"Connection: close\r\n"
    b"Content-Length: 35\r\n"
    b"\r\n"
    b"Unable to connect upstream safely.\n"
)


@dataclass(frozen=True)
class ProxyConfig:
    host: str
    port: int
    bypass: tuple[str, ...] = field(default_factory=tuple)

    @property
    def server(self) -> str:
        return f"http://{self.host}:{self.port}"

    def playwright_proxy_config(self) -> dict[str, str]:
        return {"server": self.server, "bypass": ",".join(self.bypass)}


@dataclass(frozen=True)
class ProxyDecision:
    allowed: bool
    host: str
    port: int
    resolved_ips: list[str]
    reason: str

    @property
    def upstream_ip(self) -> str | None:
        return self.resolved_ips[0] if self.resolved_ips else None


class FilteringProxy:
    def __init__(
        self,
        resolver: BrowserDNSResolver | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        open_connection: OpenConnectionFn | None = None,
    ) -> None:
        self._resolver = resolver or BrowserDNSResolver()
        self._host = host
        self._port = port
        self._open_connection = open_connection or asyncio.open_connection
        self._server: asyncio.AbstractServer | None = None
        self._config: ProxyConfig | None = None
        self._active_writers: set[asyncio.StreamWriter] = set()
        self._active_tasks: set[asyncio.Task[None]] = set()

    @property
    def config(self) -> ProxyConfig:
        if self._config is None:
            raise RuntimeError("FilteringProxy has not been started")
        return self._config

    async def start(self) -> ProxyConfig:
        if self._server is not None:
            return self.config
        self._server = await asyncio.start_server(self._handle_client, self._host, self._port)
        sockets = self._server.sockets
        if not sockets:
            raise RuntimeError("FilteringProxy failed to bind a listening socket")
        bound_host, bound_port = sockets[0].getsockname()[:2]
        self._config = ProxyConfig(host=str(bound_host), port=int(bound_port))
        return self._config

    async def aclose(self) -> None:
        server = self._server
        self._server = None
        self._config = None
        if server is not None:
            server.close()
            await server.wait_closed()
        for writer in list(self._active_writers):
            _close_writer(writer)
        for task in list(self._active_tasks):
            task.cancel()
        for writer in list(self._active_writers):
            await _wait_writer_closed(writer)
        if self._active_tasks:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*self._active_tasks, return_exceptions=True),
                    timeout=1,
                )

    async def check_connect(self, host: str, port: int) -> ProxyDecision:
        if port < 1 or port > 65535:
            return ProxyDecision(
                allowed=False,
                host=host,
                port=port,
                resolved_ips=[],
                reason="Browser proxy blocked invalid upstream port",
            )
        try:
            resolved_ips = await self._resolver.resolve_public(host)
        except BrowserSafetyError as exc:
            return ProxyDecision(
                allowed=False,
                host=host,
                port=port,
                resolved_ips=[],
                reason=f"Browser proxy blocked upstream: {exc}",
            )
        return ProxyDecision(
            allowed=True,
            host=host,
            port=port,
            resolved_ips=resolved_ips,
            reason="Browser proxy allowed upstream",
        )

    def playwright_proxy_config(self) -> dict[str, str]:
        return self.config.playwright_proxy_config()

    async def _handle_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._active_tasks.add(task)
        self._active_writers.add(client_writer)
        try:
            header = await self._read_header(client_reader)
            request = _ProxyRequest.parse(header)
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser proxy rejected malformed request: %s", exc)
            await _write_response(client_writer, _BAD_REQUEST_RESPONSE)
            return
        try:
            decision = await self.check_connect(request.host, request.port)
            if not decision.allowed or decision.upstream_ip is None:
                await _write_response(client_writer, _BLOCKED_RESPONSE)
                return

            if request.method == "CONNECT":
                await self._forward_connect(client_reader, client_writer, request, decision)
                return
            await self._forward_http(client_reader, client_writer, request, decision)
        finally:
            self._active_writers.discard(client_writer)
            if task is not None:
                self._active_tasks.discard(task)

    async def _read_header(self, reader: asyncio.StreamReader) -> bytes:
        data = await reader.readuntil(b"\r\n\r\n")
        if len(data) > _MAX_HEADER_BYTES:
            raise ValueError("proxy request header too large")
        return data

    async def _forward_connect(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        request: _ProxyRequest,
        decision: ProxyDecision,
    ) -> None:
        upstream = decision.upstream_ip
        if upstream is None:
            await _write_response(client_writer, _BLOCKED_RESPONSE)
            return
        try:
            upstream_reader, upstream_writer = await self._open_connection(upstream, request.port)
        except OSError:
            await _write_response(client_writer, _BAD_GATEWAY_RESPONSE)
            return

        self._active_writers.add(upstream_writer)
        try:
            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()
            await _pipe_bidirectional(
                client_reader, client_writer, upstream_reader, upstream_writer
            )
        finally:
            self._active_writers.discard(upstream_writer)
            _close_writer(upstream_writer)
            _close_writer(client_writer)
            await _wait_writer_closed(upstream_writer)
            await _wait_writer_closed(client_writer)

    async def _forward_http(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        request: _ProxyRequest,
        decision: ProxyDecision,
    ) -> None:
        upstream = decision.upstream_ip
        if upstream is None:
            await _write_response(client_writer, _BLOCKED_RESPONSE)
            return
        try:
            upstream_reader, upstream_writer = await self._open_connection(upstream, request.port)
        except OSError:
            await _write_response(client_writer, _BAD_GATEWAY_RESPONSE)
            return

        self._active_writers.add(upstream_writer)
        try:
            upstream_writer.write(request.to_origin_form_header())
            await upstream_writer.drain()
            await _pipe_bidirectional(
                client_reader, client_writer, upstream_reader, upstream_writer
            )
        finally:
            self._active_writers.discard(upstream_writer)
            _close_writer(upstream_writer)
            _close_writer(client_writer)
            await _wait_writer_closed(upstream_writer)
            await _wait_writer_closed(client_writer)


@dataclass(frozen=True)
class _ProxyRequest:
    method: str
    target: str
    version: str
    host: str
    port: int
    header_lines: list[bytes]
    origin_target: str

    @classmethod
    def parse(cls, header: bytes) -> _ProxyRequest:
        lines = header.split(b"\r\n")
        if not lines or lines[0] == b"":
            raise ValueError("missing request line")
        request_line = lines[0].decode("ascii", errors="strict")
        parts = request_line.split()
        if len(parts) != 3:
            raise ValueError("invalid request line")
        method, target, version = parts
        if not version.startswith("HTTP/"):
            raise ValueError("invalid HTTP version")
        if method.upper() == "CONNECT":
            host, port = _split_host_port(target, default_port=443)
            return cls(
                method="CONNECT",
                target=target,
                version=version,
                host=host,
                port=port,
                header_lines=lines,
                origin_target=target,
            )

        parsed = urlparse(target)
        if parsed.scheme == "ws":
            validated = validate_public_http_url("http://" + target[len("ws://") :])
            port = validated.port or 80
        elif parsed.scheme == "http":
            validated = validate_public_http_url(target)
            port = validated.port or 80
        else:
            raise ValueError("only absolute-form http/ws proxy requests are supported")

        path = parsed.path or "/"
        if parsed.params:
            path = f"{path};{parsed.params}"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return cls(
            method=method.upper(),
            target=target,
            version=version,
            host=validated.hostname,
            port=port,
            header_lines=lines,
            origin_target=path,
        )

    def to_origin_form_header(self) -> bytes:
        lines = [f"{self.method} {self.origin_target} {self.version}".encode("ascii")]
        lines.extend(self.header_lines[1:])
        return b"\r\n".join(lines)


def _split_host_port(target: str, *, default_port: int) -> tuple[str, int]:
    if target.startswith("["):
        closing = target.find("]")
        if closing == -1:
            raise ValueError("invalid IPv6 target")
        host = target[1:closing]
        remainder = target[closing + 1 :]
        port = int(remainder[1:]) if remainder.startswith(":") else default_port
        return host, port
    if ":" not in target:
        return target, default_port
    host, port_text = target.rsplit(":", 1)
    return host, int(port_text)


async def _write_response(writer: asyncio.StreamWriter, response: bytes) -> None:
    writer.write(response)
    with contextlib.suppress(ConnectionError):
        await writer.drain()
    _close_writer(writer)
    await _wait_writer_closed(writer)


async def _pipe_bidirectional(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while data := await reader.read(64 * 1024):
                writer.write(data)
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            _close_writer(writer)

    tasks = [
        asyncio.create_task(pipe(client_reader, upstream_writer)),
        asyncio.create_task(pipe(upstream_reader, client_writer)),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        with contextlib.suppress(ConnectionError, asyncio.CancelledError):
            await task
    await _wait_writer_closed(upstream_writer)
    await _wait_writer_closed(client_writer)


def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()


async def _wait_writer_closed(writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(ConnectionError, asyncio.TimeoutError):
        await asyncio.wait_for(writer.wait_closed(), timeout=1)
