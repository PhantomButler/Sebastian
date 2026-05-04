from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sebastian.capabilities.tools.browser.network import BrowserDNSResolver
from sebastian.capabilities.tools.browser.proxy import FilteringProxy, ProxyConfig
from sebastian.capabilities.tools.browser.safety import BrowserSafetyError, validate_public_http_url
from sebastian.config import Settings

logger = logging.getLogger(__name__)


class _Closable(Protocol):
    async def close(self) -> None: ...


class _GotoPage(_Closable, Protocol):
    @property
    def url(self) -> str: ...

    async def title(self) -> str: ...

    async def goto(self, url: str, *, timeout: int) -> object: ...

    async def click(self, target: str, *, timeout: int) -> object: ...

    async def fill(self, target: str, value: str, *, timeout: int) -> object: ...

    async def press(self, target: str, key: str, *, timeout: int) -> object: ...

    async def select_option(self, target: str, value: str, *, timeout: int) -> object: ...

    async def wait_for_selector(self, target: str, *, timeout: int) -> object: ...

    async def go_back(self, *, timeout: int) -> object: ...

    async def go_forward(self, *, timeout: int) -> object: ...

    async def reload(self, *, timeout: int) -> object: ...

    async def screenshot(self, *, path: str, full_page: bool) -> object: ...


class _EventedPage(_GotoPage, Protocol):
    def on(self, event: str, callback: Any) -> object: ...


class _Stoppable(Protocol):
    async def stop(self) -> None: ...


class _BrowserContext(_Closable, Protocol):
    async def new_page(self) -> _GotoPage: ...


class _Chromium(Protocol):
    async def launch_persistent_context(self, *args: Any, **kwargs: Any) -> _BrowserContext: ...


class _Playwright(_Stoppable, Protocol):
    chromium: _Chromium


class _PlaywrightStarter(Protocol):
    async def start(self) -> _Playwright: ...


class _PlaywrightFactory(Protocol):
    def __call__(self) -> _PlaywrightStarter: ...


class _FilteringProxyHandle(Protocol):
    async def start(self) -> ProxyConfig: ...

    async def aclose(self) -> None: ...

    def playwright_proxy_config(self) -> dict[str, str]: ...


class _PageObserver(Protocol):
    async def __call__(self, page: Any, *, max_chars: int) -> dict[str, Any]: ...


@dataclass(frozen=True)
class BrowserPageMetadata:
    url: str
    title: str | None
    opened_by_browser_tool: bool


@dataclass(frozen=True)
class BrowserDownloadRecord:
    filename: str
    path: Path
    mime: str
    size: int
    mtime: float
    original: str
    source_url: str
    created_at: str


@dataclass(frozen=True)
class BrowserOpenResult:
    ok: bool
    url: str | None = None
    title: str | None = None
    error: str = ""


@dataclass(frozen=True)
class BrowserScreenshotResult:
    path: Path
    url: str


class BrowserSessionManager:
    def __init__(
        self,
        settings: Settings,
        *,
        playwright_factory: _PlaywrightFactory | None = None,
        filtering_proxy: _FilteringProxyHandle | None = None,
        dns_resolver: BrowserDNSResolver | None = None,
    ) -> None:
        self.lock = asyncio.Lock()
        self.settings = settings
        self.profile_dir: Path = settings.browser_profile_dir
        self.downloads_dir: Path = settings.browser_downloads_dir
        self.screenshots_dir: Path = settings.browser_screenshots_dir
        self._playwright_factory = playwright_factory or _default_playwright_factory
        self._filtering_proxy = filtering_proxy or FilteringProxy()
        self._dns_resolver = dns_resolver or BrowserDNSResolver()
        self._startup_lock = asyncio.Lock()
        self._navigation_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._download_lock = asyncio.Lock()
        self._playwright: _Playwright | None = None
        self._context: _BrowserContext | None = None
        self._page: _GotoPage | None = None
        self._download_tasks: set[asyncio.Task[BrowserDownloadRecord | None]] = set()
        self._proxy_started = False
        self._current_page_owned_by_browser_tool = False

    async def open(self, url: str) -> BrowserOpenResult:
        try:
            requested = validate_public_http_url(url)
        except BrowserSafetyError as exc:
            return BrowserOpenResult(ok=False, error=str(exc))

        async with self._operation_lock:
            async with self._navigation_lock:
                page: _GotoPage | None = None
                try:
                    await self._dns_resolver.resolve_public(requested.hostname)
                    page = await self.page()
                    response = await page.goto(
                        requested.url,
                        timeout=self.settings.sebastian_browser_timeout_ms,
                    )
                    if _is_proxy_block_response(response):
                        raise BrowserSafetyError(
                            "Browser URL blocked: proxy rejected the main navigation"
                        )
                    final = validate_public_http_url(str(page.url))
                    await self._dns_resolver.resolve_public(final.hostname)
                except BrowserSafetyError as exc:
                    async with self.lock:
                        if page is not None and self._page is page:
                            self._page = None
                        self._current_page_owned_by_browser_tool = False
                    if page is not None:
                        await self._close_page_after_block(page)
                    return BrowserOpenResult(ok=False, error=str(exc))
                except Exception as exc:  # noqa: BLE001
                    message = _playwright_error_message(exc)
                    if message is None:
                        message = f"Browser open failed: {exc}"
                    return BrowserOpenResult(ok=False, error=message)

                async with self.lock:
                    self._page = page
                    self._current_page_owned_by_browser_tool = True
                return BrowserOpenResult(ok=True, url=final.url, title=await self._safe_title(page))

    async def page(self) -> _GotoPage:
        async with self._startup_lock:
            async with self.lock:
                if self._page is not None:
                    return self._page

            context = await self._ensure_context()
            page = await context.new_page()
            self._attach_download_recorder(page)

            async with self.lock:
                if self._page is None:
                    self._page = page
                    return page
                await page.close()
                return self._page

    async def aclose(self) -> None:
        async with self._operation_lock:
            await self._close_runtime_resources()

    async def current_page_metadata(self) -> BrowserPageMetadata | None:
        async with self._operation_lock:
            async with self.lock:
                if self._page is None:
                    return None
                page = self._page
                opened_by_browser_tool = self._current_page_owned_by_browser_tool

            url = str(getattr(page, "url", ""))
            title: str | None
            try:
                title = await page.title()
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser page title lookup failed: %s", exc)
                title = None
            return BrowserPageMetadata(
                url=url,
                title=title,
                opened_by_browser_tool=opened_by_browser_tool,
            )

    async def current_page(self, *, require_browser_tool: bool = True) -> Any | None:
        async with self.lock:
            if self._page is None:
                return None
            if require_browser_tool and not self._current_page_owned_by_browser_tool:
                return None
            return self._page

    async def observe_current_page(
        self,
        observer: _PageObserver,
        *,
        max_chars: int,
    ) -> dict[str, Any]:
        async with self._operation_lock:
            page = await self.current_page()
            if page is None:
                raise RuntimeError("No browser-tool-owned page is currently open")
            return await observer(page, max_chars=max_chars)

    async def act(
        self,
        *,
        action: str,
        target: str | None = None,
        value: str | None = None,
        is_blocked: Callable[[dict[str, str] | None], bool] | None = None,
    ) -> dict[str, Any]:
        async with self._operation_lock:
            page = await self.current_page()
            if page is None:
                raise RuntimeError("No browser-tool-owned page is currently open")
            metadata = await self._target_metadata_for_page(page, target)
            if is_blocked is not None and is_blocked(metadata):
                raise BrowserSafetyError(
                    "Browser action blocked because the target looks sensitive or high-impact"
                )
            timeout = self.settings.sebastian_browser_timeout_ms
            previous_downloads = await self.list_download_records()
            previous_tasks = set(self._download_tasks)
            if action == "click":
                if not target:
                    raise ValueError("click requires target")
                await page.click(target, timeout=timeout)
            elif action == "type":
                if not target:
                    raise ValueError("type requires target")
                await page.fill(target, value or "", timeout=timeout)
            elif action == "press":
                if not value:
                    raise ValueError("press requires value")
                await page.press(target or "body", value, timeout=timeout)
            elif action == "select":
                if not target:
                    raise ValueError("select requires target")
                await page.select_option(target, value or "", timeout=timeout)
            elif action == "wait_for_text":
                if not target:
                    raise ValueError("wait_for_text requires target")
                locator = page.get_by_text(target) if hasattr(page, "get_by_text") else None
                if locator is None:
                    raise RuntimeError("Current browser page does not support text waiting")
                await locator.wait_for(timeout=timeout)
            elif action == "wait_for_selector":
                if not target:
                    raise ValueError("wait_for_selector requires target")
                await page.wait_for_selector(target, timeout=timeout)
            elif action == "back":
                await page.go_back(timeout=timeout)
            elif action == "forward":
                await page.go_forward(timeout=timeout)
            elif action == "reload":
                await page.reload(timeout=timeout)
            else:
                raise ValueError(f"Unknown browser action: {action}")
            downloads = await self._collect_downloads_after_action(
                previous_tasks,
                previous_downloads,
            )
        return {"action": action, "download": downloads[0] if downloads else None}

    async def target_metadata(self, target: str) -> dict[str, str]:
        async with self._operation_lock:
            page = await self.current_page()
            if page is None:
                raise RuntimeError("No browser-tool-owned page is currently open")
            return await self._target_metadata_for_page(page, target) or {"target": target}

    async def capture_screenshot(self, *, full_page: bool = True) -> BrowserScreenshotResult:
        async with self._operation_lock:
            page = await self.current_page()
            if page is None:
                raise RuntimeError("No browser-tool-owned page is currently open")
            url = _sanitize_url(str(getattr(page, "url", "") or ""))
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            path = self.screenshots_dir / f"browser-screenshot-{uuid4().hex}.png"
            await page.screenshot(path=str(path), full_page=full_page)
            return BrowserScreenshotResult(path=path, url=url)

    async def save_download(self, download: Any) -> BrowserDownloadRecord:
        async with self._download_lock:
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
            original = str(getattr(download, "suggested_filename", "") or "download")
            filename = self._unique_download_filename(_sanitize_filename(original))
            path = self.downloads_dir / filename
            await download.save_as(str(path))

            stat = path.stat()
            record = BrowserDownloadRecord(
                filename=filename,
                path=path,
                mime=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                size=stat.st_size,
                mtime=stat.st_mtime,
                original=original,
                source_url=_sanitize_url(str(getattr(download, "url", "") or "")),
                created_at=datetime.now(UTC).isoformat(),
            )
            self._append_download_manifest(record)
            return record

    async def list_download_records(self) -> list[BrowserDownloadRecord]:
        manifest = self.downloads_dir / "downloads.jsonl"
        if not manifest.exists():
            return []
        records: list[BrowserDownloadRecord] = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                records.append(
                    BrowserDownloadRecord(
                        filename=str(data["filename"]),
                        path=Path(str(data["path"])),
                        mime=str(data.get("mime") or "application/octet-stream"),
                        size=int(data.get("size") or 0),
                        mtime=float(data.get("mtime") or 0),
                        original=str(data.get("original") or ""),
                        source_url=str(data.get("source_url") or ""),
                        created_at=str(data.get("created_at") or ""),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Skipping malformed browser download manifest row: %s", exc)
        return records

    async def resolve_download(self, filename: str) -> BrowserDownloadRecord:
        safe = _sanitize_filename(filename)
        if safe != filename:
            raise ValueError(
                "Download filename must be a plain filename from browser_downloads list"
            )
        path = (self.downloads_dir / safe).resolve()
        root = self.downloads_dir.resolve()
        if not path.is_relative_to(root):
            raise ValueError("Download filename must stay inside browser downloads")
        records = await self.list_download_records()
        for record in reversed(records):
            record_path = Path(record.path).resolve()
            if record.filename == safe and record_path == path and path.exists():
                return record
        if not path.exists() or not path.is_file():
            raise FileNotFoundError("Download not found")
        stat = path.stat()
        return BrowserDownloadRecord(
            filename=safe,
            path=path,
            mime=mimetypes.guess_type(safe)[0] or "application/octet-stream",
            size=stat.st_size,
            mtime=stat.st_mtime,
            original=safe,
            source_url="",
            created_at="",
        )

    def parse_viewport(self) -> dict[str, int]:
        raw = self.settings.sebastian_browser_viewport.strip().lower()
        try:
            width_text, height_text = raw.split("x", maxsplit=1)
            width = int(width_text)
            height = int(height_text)
        except ValueError as exc:
            raise ValueError(
                f"Invalid browser viewport {self.settings.sebastian_browser_viewport!r}; "
                "expected WIDTHxHEIGHT"
            ) from exc
        if width <= 0 or height <= 0:
            raise ValueError(
                f"Invalid browser viewport {self.settings.sebastian_browser_viewport!r}; "
                "width and height must be positive"
            )
        return {"width": width, "height": height}

    async def _ensure_context(self) -> _BrowserContext:
        async with self.lock:
            if self._context is not None:
                return self._context

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        proxy_config = await self._start_proxy_fail_closed()
        try:
            playwright = await self._playwright_factory().start()
            async with self.lock:
                self._playwright = playwright
            context = await playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.settings.sebastian_browser_headless,
                viewport=self.parse_viewport(),
                accept_downloads=True,
                downloads_path=str(self.downloads_dir),
                timeout=self.settings.sebastian_browser_timeout_ms,
                proxy=proxy_config,
            )
            self._attach_context_page_recorder(context)
        except Exception:
            await self._close_runtime_resources()
            raise

        async with self.lock:
            self._context = context
            return context

    async def _close_page_after_block(self, page: _GotoPage) -> None:
        try:
            await page.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser page close failed after blocked navigation: %s", exc)

    async def _target_metadata_for_page(
        self,
        page: Any,
        target: str | None,
    ) -> dict[str, str] | None:
        if not target:
            return None
        locator_method = getattr(page, "locator", None)
        if not callable(locator_method):
            return {"target": target}
        locator = locator_method(target)
        count_method = getattr(locator, "count", None)
        if callable(count_method):
            count = await count_method()
            if count == 0:
                raise ValueError("Browser action target was not found")
            if count > 1:
                raise ValueError("Browser action target is ambiguous")
        first_method = getattr(locator, "first", None)
        element = first_method() if callable(first_method) else locator
        evaluate = getattr(element, "evaluate", None)
        if not callable(evaluate):
            return {"target": target}
        data = await evaluate(
            """el => ({
                tag: (el.tagName || '').toLowerCase(),
                type: (el.getAttribute('type') || '').toLowerCase(),
                role: el.getAttribute('role') || '',
                name: el.getAttribute('name') || '',
                id: el.id || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                text: (el.innerText || el.textContent || '').trim().slice(0, 120),
                formAction: el.form ? (el.form.getAttribute('action') || '') : '',
                formMethod: el.form ? (el.form.getAttribute('method') || '') : '',
                buttonType: (el.getAttribute('type') || '').toLowerCase(),
                isSubmitControl: !!el.form && (
                    (el.tagName || '').toLowerCase() === 'button'
                        ? ((el.getAttribute('type') || 'submit').toLowerCase() === 'submit')
                        : ((el.getAttribute('type') || '').toLowerCase() === 'submit')
                ),
                formInputTypes: el.form
                    ? Array.from(el.form.querySelectorAll('input, textarea, select'))
                        .map(input => (
                            input.getAttribute('type') || input.tagName || ''
                        ).toLowerCase())
                        .join(' ')
                    : '',
                formInputNames: el.form
                    ? Array.from(el.form.querySelectorAll('input, textarea, select'))
                        .map(input => [
                            input.getAttribute('name') || '',
                            input.id || '',
                            input.getAttribute('autocomplete') || '',
                            input.getAttribute('aria-label') || '',
                            input.getAttribute('placeholder') || '',
                        ].join(' '))
                        .join(' ')
                    : '',
                formHasFields: el.form
                    ? String(el.form.querySelectorAll('input, textarea, select').length > 0)
                    : '',
            })"""
        )
        if not isinstance(data, dict):
            return {"target": target}
        return {str(key): str(value) for key, value in data.items() if value is not None}

    async def _close_runtime_resources(self) -> None:
        async with self.lock:
            page = self._page
            context = self._context
            playwright = self._playwright
            proxy = self._filtering_proxy if self._proxy_started else None
            self._page = None
            self._context = None
            self._playwright = None
            self._proxy_started = False
            self._current_page_owned_by_browser_tool = False
            download_tasks = set(self._download_tasks)
            self._download_tasks.clear()

        for task in download_tasks:
            task.cancel()
        if page is not None:
            try:
                await page.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser page close failed during shutdown: %s", exc)
        if context is not None:
            try:
                await context.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser context close failed during shutdown: %s", exc)
        if proxy is not None:
            try:
                await proxy.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser proxy close failed during shutdown: %s", exc)
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("playwright stop failed during shutdown: %s", exc)
        if download_tasks:
            await asyncio.gather(*download_tasks, return_exceptions=True)

    async def _collect_downloads_after_action(
        self,
        previous_tasks: set[asyncio.Task[BrowserDownloadRecord | None]],
        previous_downloads: list[BrowserDownloadRecord],
    ) -> list[dict[str, object]]:
        await asyncio.sleep(0)
        new_tasks = set(self._download_tasks) - previous_tasks
        if new_tasks:
            await asyncio.gather(*new_tasks, return_exceptions=True)
        previous_names = {record.filename for record in previous_downloads}
        records = await self.list_download_records()
        downloads = [record for record in records if record.filename not in previous_names]
        return [_public_download(record) for record in downloads]

    async def _start_proxy_fail_closed(self) -> dict[str, str]:
        try:
            await self._filtering_proxy.start()
            proxy_config = self._filtering_proxy.playwright_proxy_config()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Browser proxy failed to start; refusing direct network fallback: "
                f"{exc}"
            ) from exc

        server = proxy_config.get("server", "")
        if not server:
            raise RuntimeError(
                "Browser proxy config is unavailable; refusing direct network fallback"
            )
        proxy_config = {**proxy_config, "bypass": ""}
        async with self.lock:
            self._proxy_started = True
        return proxy_config

    async def _safe_title(self, page: _GotoPage) -> str | None:
        try:
            return await page.title()
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser page title lookup failed: %s", exc)
            return None

    def _attach_context_page_recorder(self, context: _BrowserContext) -> None:
        on_event = getattr(context, "on", None)
        if not callable(on_event):
            return

        def _attach(page: Any) -> None:
            self._attach_download_recorder(page)

        try:
            on_event("page", _attach)
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser page listener registration failed: %s", exc)

    def _attach_download_recorder(self, page: Any) -> None:
        on_event = getattr(page, "on", None)
        if not callable(on_event):
            return

        def _record(download: Any) -> None:
            task = asyncio.create_task(self._save_download_safely(download))
            self._download_tasks.add(task)
            task.add_done_callback(self._download_tasks.discard)

        try:
            on_event("download", _record)
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser download listener registration failed: %s", exc)

    async def _save_download_safely(self, download: Any) -> BrowserDownloadRecord | None:
        try:
            return await self.save_download(download)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser download save failed: %s", exc)
            return None

    def _unique_download_filename(self, filename: str) -> str:
        candidate = filename
        stem = Path(filename).stem or "download"
        suffix = Path(filename).suffix
        index = 1
        while (self.downloads_dir / candidate).exists():
            candidate = f"{stem}-{index}{suffix}"
            index += 1
        return candidate

    def _append_download_manifest(self, record: BrowserDownloadRecord) -> None:
        manifest = self.downloads_dir / "downloads.jsonl"
        payload = {
            "filename": record.filename,
            "path": str(record.path),
            "mime": record.mime,
            "size": record.size,
            "mtime": record.mtime,
            "original": record.original,
            "source_url": record.source_url,
            "created_at": record.created_at,
        }
        with manifest.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _default_playwright_factory() -> _PlaywrightStarter:
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Ask the user to run: "
            "python -m playwright install chromium"
        ) from exc
    return cast(_PlaywrightStarter, async_playwright())


def _playwright_error_message(exc: Exception) -> str | None:
    text = str(exc)
    lowered = text.lower()
    if "executable doesn't exist" in lowered or "browserType.launch" in text:
        return (
            "Browser executable is missing. Ask the user to run: "
            "python -m playwright install chromium"
        )
    if (
        "host system is missing dependencies" in lowered
        or "missing dependencies" in lowered
        or "install-deps" in lowered
    ):
        return (
            "Browser system dependencies are missing. Ask the user to run: "
            "python -m playwright install-deps chromium"
        )
    return None


def _is_proxy_block_response(response: object) -> bool:
    if response is None:
        return False
    status = getattr(response, "status", None)
    if callable(status):
        status = status()
    if status != 403:
        return False
    headers = getattr(response, "headers", None)
    if callable(headers):
        headers = headers()
    if not isinstance(headers, dict):
        return False
    return str(headers.get("x-sebastian-proxy-blocked", "")).lower() in {"1", "true", "yes"}


def _public_download(record: BrowserDownloadRecord) -> dict[str, object]:
    return {
        "filename": record.filename,
        "mime": record.mime,
        "size": record.size,
        "mtime": record.mtime,
        "original": record.original,
        "source_url": record.source_url,
        "created_at": record.created_at,
    }


def _sanitize_filename(filename: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    cleaned = "".join(ch for ch in leaf if ch.isprintable() and ch not in {"/", "\\"}).strip()
    cleaned = cleaned.lstrip(".").strip()
    return cleaned or "download"


def _sanitize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
