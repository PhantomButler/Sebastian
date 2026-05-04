from __future__ import annotations

import asyncio
import inspect
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from sebastian.capabilities.tools.browser.safety import (
    BrowserSafetyError,
    is_forbidden_ip,
    normalize_hostname,
)

ResolverReturn = Iterable[str] | Awaitable[Iterable[str]]
ResolverFn = Callable[[str], ResolverReturn]
DNSMode = Literal["auto", "system", "doh"]

_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class BrowserDNSResolver:
    def __init__(
        self,
        resolve: ResolverFn | None = None,
        *,
        doh_resolve: ResolverFn | None = None,
        dns_mode: str = "auto",
        doh_endpoint: str = "https://dns.alidns.com/resolve",
        doh_proxy: str | None = None,
        timeout_seconds: float = 5.0,
        doh_timeout_seconds: float = 5.0,
    ) -> None:
        self._resolve = resolve
        self._doh_resolve = doh_resolve
        self._dns_mode = _normalize_dns_mode(dns_mode)
        self._doh_endpoint = _validate_doh_endpoint(doh_endpoint)
        self._doh_proxy = doh_proxy
        self._timeout_seconds = timeout_seconds
        self._doh_timeout_seconds = doh_timeout_seconds

    async def resolve_public(
        self,
        host: str,
        *,
        allow_proxy_fake_ip: bool = False,
    ) -> list[str]:
        normalized_host = normalize_hostname(host)
        literal = _ip_literal_or_none(normalized_host)
        if literal is not None:
            if is_forbidden_ip(literal):
                raise BrowserSafetyError(
                    "Browser destination blocked: "
                    f"{normalized_host} resolves to forbidden IP {literal}"
                )
            return [literal]

        if self._dns_mode == "doh":
            return await self._resolve_public_doh(normalized_host)

        try:
            answers = await asyncio.wait_for(
                self._resolve_host(normalized_host),
                timeout=self._timeout_seconds,
            )
        except BrowserSafetyError:
            raise
        except Exception as exc:
            raise BrowserSafetyError(
                f"Browser destination blocked: DNS resolution failed for {normalized_host}"
            ) from exc

        try:
            normalized_answers = self._normalize_answers(normalized_host, answers)
        except _ProxyFakeIPOnly as exc:
            if allow_proxy_fake_ip:
                return []
            if self._dns_mode != "auto":
                raise BrowserSafetyError(
                    f"Browser destination blocked: {normalized_host} resolves to proxy Fake-IP"
                ) from exc
            return await self._resolve_public_doh_after_fake_ip(normalized_host, exc.answers)
        if not normalized_answers:
            raise BrowserSafetyError(
                f"Browser destination blocked: DNS returned no addresses for {normalized_host}"
            )
        return normalized_answers

    async def _resolve_host(self, host: str) -> Iterable[str]:
        if self._resolve is None:
            return await _default_resolve(host)

        result = self._resolve(host)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _resolve_public_doh(self, host: str) -> list[str]:
        try:
            answers = await asyncio.wait_for(
                self._resolve_doh_host(host),
                timeout=self._doh_timeout_seconds,
            )
        except BrowserSafetyError:
            raise
        except Exception as exc:
            raise BrowserSafetyError(
                f"Browser destination blocked: DoH resolution failed for {host}"
            ) from exc

        normalized_answers = self._normalize_answers(host, answers)
        if not normalized_answers:
            raise BrowserSafetyError(
                f"Browser destination blocked: DoH returned no addresses for {host}"
            )
        return normalized_answers

    async def _resolve_public_doh_after_fake_ip(
        self,
        host: str,
        fake_answers: list[str],
    ) -> list[str]:
        try:
            return await self._resolve_public_doh(host)
        except BrowserSafetyError as exc:
            joined = ", ".join(fake_answers)
            raise BrowserSafetyError(
                "Browser destination blocked: system proxy DNS returned Fake-IP "
                f"for {host} ({joined}), and Sebastian browser DoH resolution failed. "
                "Please check Sebastian browser DoH configuration or proxy DNS mode."
            ) from exc

    async def _resolve_doh_host(self, host: str) -> Iterable[str]:
        if self._doh_resolve is not None:
            result = self._doh_resolve(host)
            if inspect.isawaitable(result):
                return await result
            return result
        return await _default_doh_resolve(
            host,
            endpoint=self._doh_endpoint,
            proxy=self._doh_proxy,
            timeout_seconds=self._doh_timeout_seconds,
        )

    def _normalize_answers(self, host: str, answers: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        fake_answers: list[str] = []
        seen: set[str] = set()
        for answer in answers:
            try:
                ip = ipaddress.ip_address(str(answer)).compressed
            except ValueError as exc:
                raise BrowserSafetyError(
                    f"Browser destination blocked: DNS returned non-IP answer for {host}"
                ) from exc
            if _is_proxy_fake_ip(ip):
                fake_answers.append(ip)
                continue
            if is_forbidden_ip(ip):
                raise BrowserSafetyError(
                    f"Browser destination blocked: {host} resolves to forbidden IP {ip}"
                )
            if ip not in seen:
                normalized.append(ip)
                seen.add(ip)
        if fake_answers:
            if normalized:
                raise BrowserSafetyError(
                    f"Browser destination blocked: {host} resolves to proxy Fake-IP "
                    "mixed with public DNS answers"
                )
            raise _ProxyFakeIPOnly(fake_answers)
        return normalized


async def _default_resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(
        host,
        None,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    answers: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip = str(sockaddr[0])
        if ip not in answers:
            answers.append(ip)
    return answers


async def _default_doh_resolve(
    host: str,
    *,
    endpoint: str,
    proxy: str | None,
    timeout_seconds: float,
) -> list[str]:
    answers: list[str] = []
    async with httpx.AsyncClient(timeout=timeout_seconds, proxy=proxy, trust_env=False) as client:
        for record_type in ("A", "AAAA"):
            response = await client.get(
                endpoint,
                params={"name": host, "type": record_type},
                headers={"accept": "application/dns-json"},
            )
            response.raise_for_status()
            data = response.json()
            answers.extend(_answers_from_doh_json(data, record_type))
    return answers


def _answers_from_doh_json(data: Any, record_type: str) -> list[str]:
    if not isinstance(data, dict):
        raise BrowserSafetyError("Browser destination blocked: DoH returned invalid JSON")
    if int(data.get("Status", 1)) != 0:
        return []
    expected_type = 1 if record_type == "A" else 28
    answers = data.get("Answer") or []
    if not isinstance(answers, list):
        raise BrowserSafetyError("Browser destination blocked: DoH returned invalid answers")
    ips: list[str] = []
    for answer in answers:
        if not isinstance(answer, dict) or int(answer.get("type", 0)) != expected_type:
            continue
        answer_data = answer.get("data")
        if answer_data:
            ips.append(str(answer_data))
    return ips


def _ip_literal_or_none(host: str) -> str | None:
    try:
        return ipaddress.ip_address(host).compressed
    except ValueError:
        return None


def _is_proxy_fake_ip(ip: str) -> bool:
    return ipaddress.ip_address(ip) in _FAKE_IP_NETWORK


def _normalize_dns_mode(mode: str) -> DNSMode:
    normalized = mode.strip().lower()
    if normalized not in {"auto", "system", "doh"}:
        raise ValueError("Browser DNS mode must be one of: auto, system, doh")
    return normalized  # type: ignore[return-value]


def _validate_doh_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Browser DoH endpoint must be an https URL")
    return endpoint


class _ProxyFakeIPOnly(BrowserSafetyError):
    def __init__(self, answers: list[str]) -> None:
        super().__init__("Browser destination resolved only to proxy Fake-IP answers")
        self.answers = answers
