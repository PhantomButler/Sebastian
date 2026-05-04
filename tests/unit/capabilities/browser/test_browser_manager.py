from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from sebastian.capabilities.tools.browser.proxy import ProxyConfig
from sebastian.config import Settings


class _FakeFilteringProxy:
    def __init__(self, calls: list[str], *, fail_start: bool = False) -> None:
        self.calls = calls
        self.fail_start = fail_start
        self.config = ProxyConfig(host="127.0.0.1", port=43123)

    async def start(self) -> ProxyConfig:
        self.calls.append("proxy_start")
        if self.fail_start:
            raise RuntimeError("proxy failed")
        return self.config

    async def aclose(self) -> None:
        self.calls.append("proxy_close")

    def playwright_proxy_config(self) -> dict[str, str]:
        return self.config.playwright_proxy_config()


class _FakeDNSResolver:
    def __init__(
        self,
        blocked_hosts: set[str] | None = None,
        *,
        answer: str = "93.184.216.34",
    ) -> None:
        self.blocked_hosts = blocked_hosts or set()
        self.answer = answer
        self.hosts: list[str] = []

    async def resolve_public(self, host: str) -> list[str]:
        from sebastian.capabilities.tools.browser.safety import BrowserSafetyError

        self.hosts.append(host)
        if host in self.blocked_hosts or host in {"localhost", "127.0.0.1", "169.254.169.254"}:
            raise BrowserSafetyError(
                f"Browser destination blocked: {host} resolves to forbidden IP 127.0.0.1"
            )
        return [self.answer]


class _FakeResponse:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}


class _FakePage:
    def __init__(
        self,
        calls: list[str],
        *,
        final_url: str = "https://example.com/",
        goto_response: object | None = None,
    ) -> None:
        self.calls = calls
        self.url = "about:blank"
        self.final_url = final_url
        self.goto_response = goto_response
        self.closed = False
        self.handlers: dict[str, Any] = {}

    async def goto(self, url: str, *, timeout: int) -> object:
        self.calls.append(f"goto:{url}:{timeout}")
        self.url = self.final_url
        return self.goto_response or object()

    async def click(self, target: str, *, timeout: int) -> object:
        self.calls.append(f"click:{target}:{timeout}")
        return object()

    async def fill(self, target: str, value: str, *, timeout: int) -> object:
        self.calls.append(f"fill:{target}:{value}:{timeout}")
        return object()

    async def press(self, target: str, key: str, *, timeout: int) -> object:
        self.calls.append(f"press:{target}:{key}:{timeout}")
        return object()

    async def select_option(self, target: str, value: str, *, timeout: int) -> object:
        self.calls.append(f"select:{target}:{value}:{timeout}")
        return object()

    async def wait_for_selector(self, target: str, *, timeout: int) -> object:
        self.calls.append(f"wait_for_selector:{target}:{timeout}")
        return object()

    async def go_back(self, *, timeout: int) -> object:
        self.calls.append(f"go_back:{timeout}")
        return object()

    async def go_forward(self, *, timeout: int) -> object:
        self.calls.append(f"go_forward:{timeout}")
        return object()

    async def reload(self, *, timeout: int) -> object:
        self.calls.append(f"reload:{timeout}")
        return object()

    async def screenshot(self, *, path: str, full_page: bool) -> object:
        self.calls.append(f"screenshot:{path}:{full_page}")
        return object()

    async def close(self) -> None:
        self.calls.append("page_close")
        self.closed = True

    async def title(self) -> str:
        return "Example Page"

    def locator(self, target: str) -> Any:
        return _FakeLocator()

    def on(self, event: str, callback: Any) -> None:
        self.calls.append(f"page_on:{event}")
        self.handlers[event] = callback


class _FakeLocator:
    async def count(self) -> int:
        return 1

    def first(self) -> _FakeLocator:
        return self

    async def evaluate(self, _script: str) -> dict[str, str]:
        return {"tag": "button", "text": "Open menu"}


class _BlockingPage(_FakePage):
    def __init__(self, calls: list[str]) -> None:
        super().__init__(calls)
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.active_gotos = 0
        self.max_active_gotos = 0
        self._goto_count = 0

    async def goto(self, url: str, *, timeout: int) -> object:
        self.active_gotos += 1
        self.max_active_gotos = max(self.max_active_gotos, self.active_gotos)
        self._goto_count += 1
        self.calls.append(f"goto:{url}:{timeout}")
        try:
            if self._goto_count == 1:
                self.first_started.set()
                await self.release_first.wait()
            self.url = url
            return object()
        finally:
            self.active_gotos -= 1


class _FakeContext:
    def __init__(self, calls: list[str], page: _FakePage | None = None) -> None:
        self.calls = calls
        self.page = page or _FakePage(calls)
        self.launch_kwargs: dict[str, Any] | None = None
        self.handlers: dict[str, Any] = {}

    async def new_page(self) -> _FakePage:
        self.calls.append("new_page")
        return self.page

    async def close(self) -> None:
        self.calls.append("context_close")

    def on(self, event: str, callback: Any) -> None:
        self.calls.append(f"context_on:{event}")
        self.handlers[event] = callback


class _FakeChromium:
    def __init__(self, calls: list[str], context: _FakeContext) -> None:
        self.calls = calls
        self.context = context

    async def launch_persistent_context(self, *args: Any, **kwargs: Any) -> _FakeContext:
        self.calls.append("launch_persistent_context")
        self.context.launch_kwargs = {"args": args, **kwargs}
        return self.context


class _FakePlaywright:
    def __init__(self, calls: list[str], context: _FakeContext) -> None:
        self.calls = calls
        self.chromium = _FakeChromium(calls, context)

    async def stop(self) -> None:
        self.calls.append("playwright_stop")


class _FakePlaywrightFactory:
    def __init__(self, calls: list[str], context: _FakeContext) -> None:
        self.calls = calls
        self.playwright = _FakePlaywright(calls, context)

    def __call__(self) -> Any:
        self.calls.append("playwright_factory")
        return self

    async def start(self) -> _FakePlaywright:
        self.calls.append("playwright_start")
        return self.playwright


class _CloseRecorder:
    def __init__(self, name: str, calls: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.fail = fail
        self.url = ""

    async def close(self) -> None:
        self.calls.append(self.name)
        if self.fail:
            raise RuntimeError(f"{self.name} close failed")

    async def title(self) -> str:
        return ""


class _StopRecorder:
    def __init__(self, name: str, calls: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.fail = fail

    async def stop(self) -> None:
        self.calls.append(self.name)
        if self.fail:
            raise RuntimeError(f"{self.name} stop failed")


def _settings(tmp_path: Path) -> Settings:
    return Settings(sebastian_data_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_aclose_closes_page_context_and_playwright_in_order(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    manager = BrowserSessionManager(_settings(tmp_path))
    manager._page = cast(Any, _CloseRecorder("page", calls))
    manager._context = cast(Any, _CloseRecorder("context", calls))
    manager._playwright = cast(Any, _StopRecorder("playwright", calls))

    await manager.aclose()

    assert calls == ["page", "context", "playwright"]
    assert manager._page is None
    assert manager._context is None
    assert manager._playwright is None


@pytest.mark.asyncio
async def test_aclose_is_idempotent_and_continues_after_close_errors(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    manager = BrowserSessionManager(_settings(tmp_path))
    manager._page = cast(Any, _CloseRecorder("page", calls, fail=True))
    manager._context = cast(Any, _CloseRecorder("context", calls, fail=True))
    manager._playwright = cast(Any, _StopRecorder("playwright", calls, fail=True))

    await manager.aclose()
    await manager.aclose()

    assert calls == ["page", "context", "playwright"]
    assert manager._page is None
    assert manager._context is None
    assert manager._playwright is None


@pytest.mark.asyncio
async def test_current_page_metadata_returns_none_without_page(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    manager = BrowserSessionManager(_settings(tmp_path))

    assert await manager.current_page_metadata() is None


class _MetadataPage:
    def __init__(self) -> None:
        self.url = "https://example.test/path"

    async def close(self) -> None:
        return None

    async def title(self) -> str:
        return "Example Page"


class _BrokenTitlePage:
    def __init__(self) -> None:
        self.url = "https://example.test/broken"

    async def close(self) -> None:
        return None

    async def title(self) -> str:
        raise RuntimeError("title unavailable")


@pytest.mark.asyncio
async def test_current_page_metadata_reads_url_and_title(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    manager = BrowserSessionManager(_settings(tmp_path))
    manager._page = cast(Any, _MetadataPage())

    metadata = await manager.current_page_metadata()

    assert metadata is not None
    assert metadata.url == "https://example.test/path"
    assert metadata.title == "Example Page"


@pytest.mark.asyncio
async def test_current_page_metadata_tolerates_title_errors(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    manager = BrowserSessionManager(_settings(tmp_path))
    manager._page = cast(Any, _BrokenTitlePage())

    metadata = await manager.current_page_metadata()

    assert metadata is not None
    assert metadata.url == "https://example.test/broken"
    assert metadata.title is None


@pytest.mark.asyncio
async def test_open_launches_persistent_context_with_profile_dir_and_proxy(
    tmp_path: Path,
) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    settings = _settings(tmp_path)
    context = _FakeContext(calls)
    manager = BrowserSessionManager(
        settings=settings,
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(),
    )

    result = await manager.open("https://example.com/")

    assert result.ok is True
    assert result.url == "https://example.com/"
    assert calls[:4] == [
        "proxy_start",
        "playwright_factory",
        "playwright_start",
        "launch_persistent_context",
    ]
    assert context.launch_kwargs == {
        "args": (str(settings.browser_profile_dir),),
        "headless": settings.sebastian_browser_headless,
        "viewport": {"width": 1280, "height": 900},
        "accept_downloads": True,
        "downloads_path": str(settings.browser_downloads_dir),
        "timeout": settings.sebastian_browser_timeout_ms,
        "proxy": {"server": "http://127.0.0.1:43123", "bypass": ""},
    }
    assert manager._page is context.page
    assert manager._current_page_owned_by_browser_tool is True
    assert "download" in context.page.handlers
    assert "page" in context.handlers


@pytest.mark.asyncio
async def test_open_uses_shared_resolver_for_requested_and_final_hosts(
    tmp_path: Path,
) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    resolver = _FakeDNSResolver()
    context = _FakeContext(
        calls,
        page=_FakePage(calls, final_url="https://final.example/"),
    )
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=resolver,
    )

    result = await manager.open("https://start.example/")

    assert result.ok is True
    assert resolver.hosts == ["start.example", "final.example"]


@pytest.mark.asyncio
async def test_open_succeeds_when_auto_dns_falls_back_from_fake_ip_to_doh(
    tmp_path: Path,
) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager
    from sebastian.capabilities.tools.browser.network import BrowserDNSResolver

    calls: list[str] = []
    context = _FakeContext(calls)
    resolver = BrowserDNSResolver(
        resolve=lambda host: ["198.18.0.17"],
        doh_resolve=lambda host: ["93.184.216.34"],
        dns_mode="auto",
    )
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=resolver,
    )

    result = await manager.open("https://example.com/")

    assert result.ok is True
    assert result.url == "https://example.com/"


@pytest.mark.asyncio
async def test_aclose_closes_proxy_after_browser_resources(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    context = _FakeContext(calls)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(),
    )
    await manager.open("https://example.com/")

    await manager.aclose()
    await manager.aclose()

    assert calls[-4:] == ["page_close", "context_close", "proxy_close", "playwright_stop"]
    assert manager._page is None
    assert manager._context is None
    assert manager._playwright is None
    assert manager._current_page_owned_by_browser_tool is False


@pytest.mark.asyncio
async def test_open_validates_requested_url_before_launch(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    context = _FakeContext(calls)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(),
    )

    result = await manager.open("http://127.0.0.1:8823/")

    assert result.ok is False
    assert "blocked" in result.error.lower()
    assert calls == []
    assert manager._page is None


@pytest.mark.asyncio
async def test_open_fails_closed_when_proxy_cannot_start(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    context = _FakeContext(calls)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls, fail_start=True),
        dns_resolver=_FakeDNSResolver(),
    )

    result = await manager.open("https://example.com/")

    assert result.ok is False
    assert "refusing direct network fallback" in result.error
    assert calls == ["proxy_start"]
    assert manager._context is None
    assert manager._page is None


@pytest.mark.asyncio
async def test_open_rejects_hostname_that_resolves_to_forbidden_ip(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    context = _FakeContext(calls)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(blocked_hosts={"evil.test"}),
    )

    result = await manager.open("https://evil.test/")

    assert result.ok is False
    assert "blocked" in result.error.lower()
    assert calls == []
    assert manager._page is None


@pytest.mark.asyncio
async def test_open_rejects_proxy_block_response_for_main_navigation(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    page = _FakePage(
        calls,
        goto_response=_FakeResponse(
            403,
            {"x-sebastian-proxy-blocked": "1"},
        ),
    )
    context = _FakeContext(calls, page=page)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(),
    )

    result = await manager.open("https://example.com/")

    assert result.ok is False
    assert "proxy rejected" in result.error
    assert manager._page is None
    assert page.closed is True


@pytest.mark.asyncio
async def test_open_rejects_forbidden_final_url_after_redirect(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    final_page = _FakePage(calls, final_url="http://169.254.169.254/latest/meta-data")
    context = _FakeContext(calls, page=final_page)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(),
    )

    result = await manager.open("https://example.com/redirect")

    assert result.ok is False
    assert "blocked" in result.error.lower()
    assert manager._page is None
    assert manager._current_page_owned_by_browser_tool is False
    assert final_page.closed is True


@pytest.mark.asyncio
async def test_concurrent_open_shares_single_context_and_page(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    context = _FakeContext(calls)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(),
    )

    first, second = await asyncio.gather(
        manager.open("https://example.com/one"),
        manager.open("https://example.com/two"),
    )

    assert first.ok is True
    assert second.ok is True
    assert calls.count("proxy_start") == 1
    assert calls.count("playwright_start") == 1
    assert calls.count("launch_persistent_context") == 1
    assert calls.count("new_page") == 1


@pytest.mark.asyncio
async def test_concurrent_open_serializes_navigation_on_shared_page(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    page = _BlockingPage(calls)
    context = _FakeContext(calls, page=page)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(),
    )

    first_task = asyncio.create_task(manager.open("https://example.com/one"))
    await asyncio.wait_for(page.first_started.wait(), timeout=1)
    second_task = asyncio.create_task(manager.open("https://example.com/two"))
    await asyncio.sleep(0)
    assert page.max_active_gotos == 1
    page.release_first.set()

    first, second = await asyncio.gather(first_task, second_task)

    assert first.ok is True
    assert second.ok is True
    assert page.max_active_gotos == 1
    assert calls.count("new_page") == 1


@pytest.mark.asyncio
async def test_open_returns_deterministic_missing_browser_message(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    class _MissingBrowserChromium:
        async def launch_persistent_context(self, *args: Any, **kwargs: Any) -> object:
            raise RuntimeError("Executable doesn't exist at /ms-playwright/chromium")

    class _MissingBrowserPlaywright:
        chromium = _MissingBrowserChromium()

        async def stop(self) -> None:
            return None

    class _MissingBrowserFactory:
        def __call__(self) -> Any:
            return self

        async def start(self) -> _MissingBrowserPlaywright:
            return _MissingBrowserPlaywright()

    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_MissingBrowserFactory(),
        filtering_proxy=_FakeFilteringProxy([]),
        dns_resolver=_FakeDNSResolver(),
    )

    result = await manager.open("https://example.com/")

    assert result.ok is False
    assert "python -m playwright install chromium" in result.error


@pytest.mark.asyncio
async def test_open_returns_deterministic_missing_deps_message(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    class _MissingDepsChromium:
        async def launch_persistent_context(self, *args: Any, **kwargs: Any) -> object:
            raise RuntimeError("Host system is missing dependencies to run browsers.")

    class _MissingDepsPlaywright:
        chromium = _MissingDepsChromium()

        async def stop(self) -> None:
            return None

    class _MissingDepsFactory:
        def __call__(self) -> Any:
            return self

        async def start(self) -> _MissingDepsPlaywright:
            return _MissingDepsPlaywright()

    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_MissingDepsFactory(),
        filtering_proxy=_FakeFilteringProxy([]),
        dns_resolver=_FakeDNSResolver(),
    )

    result = await manager.open("https://example.com/")

    assert result.ok is False
    assert "python -m playwright install-deps chromium" in result.error


def test_parse_viewport_accepts_valid_setting(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    manager = BrowserSessionManager(
        _settings(tmp_path).model_copy(update={"sebastian_browser_viewport": "375x812"})
    )

    assert manager.parse_viewport() == {"width": 375, "height": 812}


def test_parse_viewport_rejects_invalid_setting(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    manager = BrowserSessionManager(
        _settings(tmp_path).model_copy(update={"sebastian_browser_viewport": "wide"})
    )

    with pytest.raises(ValueError, match="Invalid browser viewport"):
        manager.parse_viewport()


def test_default_manager_wires_upstream_proxy_from_settings(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    manager = BrowserSessionManager(
        _settings(tmp_path).model_copy(
            update={"sebastian_browser_upstream_proxy": "http://127.0.0.1:7890"}
        )
    )

    assert manager._filtering_proxy._upstream_proxy is not None
    assert manager._filtering_proxy._upstream_proxy.url == "http://127.0.0.1:7890"
    assert manager._dns_resolver._doh_proxy == "http://127.0.0.1:7890"


@pytest.mark.asyncio
async def test_open_reports_invalid_upstream_proxy_without_crashing_gateway(
    tmp_path: Path,
) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    manager = BrowserSessionManager(
        _settings(tmp_path).model_copy(
            update={"sebastian_browser_upstream_proxy": "socks5://127.0.0.1:1080"}
        )
    )

    result = await manager.open("https://example.com/")

    assert result.ok is False
    assert "Browser upstream proxy is invalid" in result.error


@pytest.mark.asyncio
async def test_download_recorder_uses_page_download_event(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    context = _FakeContext(calls)
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        playwright_factory=_FakePlaywrightFactory(calls, context),
        filtering_proxy=_FakeFilteringProxy(calls),
        dns_resolver=_FakeDNSResolver(),
    )

    await manager.open("https://example.com/")

    assert "page_on:download" in calls
    assert "context_on:download" not in calls


@pytest.mark.asyncio
async def test_press_requires_target_to_avoid_active_element_submit(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        dns_resolver=_FakeDNSResolver(),
    )
    manager._page = cast(Any, _FakePage(calls))
    manager._current_page_owned_by_browser_tool = True

    with pytest.raises(ValueError, match="press requires target"):
        await manager.act(action="press", value="Enter")

    assert not any(call.startswith("press:") for call in calls)


@pytest.mark.asyncio
async def test_action_rejects_forbidden_final_url_and_clears_page(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    calls: list[str] = []
    page = _FakePage(calls, final_url="https://example.com/")
    manager = BrowserSessionManager(
        settings=_settings(tmp_path),
        dns_resolver=_FakeDNSResolver(blocked_hosts={"evil.test"}),
    )
    manager._page = cast(Any, page)
    manager._current_page_owned_by_browser_tool = True
    page.url = "https://example.com/"

    async def click_and_navigate(target: str, *, timeout: int) -> object:
        calls.append(f"click:{target}:{timeout}")
        page.url = "https://evil.test/private"
        return object()

    page.click = click_and_navigate  # type: ignore[method-assign]

    with pytest.raises(Exception, match="blocked"):
        await manager.act(action="click", target="a.bad")

    assert manager._page is None
    assert manager._current_page_owned_by_browser_tool is False
    assert page.closed is True
