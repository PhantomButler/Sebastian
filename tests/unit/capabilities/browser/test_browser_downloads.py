from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sebastian.capabilities.tools.browser.downloads import list_downloads
from sebastian.capabilities.tools.browser.manager import (
    BrowserScreenshotResult,
    BrowserSessionManager,
)
from sebastian.config import Settings
from sebastian.core.tool_context import _current_tool_ctx
from sebastian.permissions.types import ToolCallContext


class _FakeDownload:
    def __init__(self, suggested_filename: str = "../Quarterly Report.pdf") -> None:
        self.suggested_filename = suggested_filename
        self.url = "https://example.com/report.pdf?token=secret"

    async def save_as(self, path: str) -> None:
        Path(path).write_bytes(b"%PDF-1.7\nreport")


class _DownloadClickPage:
    url = "https://example.com/download"

    def __init__(self, manager: BrowserSessionManager) -> None:
        self.manager = manager

    async def click(self, target: str, *, timeout: int) -> object:
        await self.manager.save_download(_FakeDownload("clicked.pdf"))
        return object()

    async def close(self) -> None:
        return None

    async def title(self) -> str:
        return "Download"


class _Upload:
    id = "att-1"
    size_bytes = 15


class _Record:
    id = "att-1"


class _FakeAttachmentStore:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.marked: list[dict[str, str]] = []

    async def upload_bytes(
        self,
        *,
        filename: str,
        content_type: str,
        kind: str,
        data: bytes,
    ) -> _Upload:
        self.uploads.append(
            {
                "filename": filename,
                "content_type": content_type,
                "kind": kind,
                "data": data,
            }
        )
        return _Upload()

    async def mark_agent_sent(
        self, *, attachment_id: str, agent_type: str, session_id: str
    ) -> _Record:
        self.marked.append(
            {
                "attachment_id": attachment_id,
                "agent_type": agent_type,
                "session_id": session_id,
            }
        )
        return _Record()


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(sebastian_data_dir=str(tmp_path))
    settings.browser_downloads_dir.mkdir(parents=True, exist_ok=True)
    settings.browser_screenshots_dir.mkdir(parents=True, exist_ok=True)
    return settings


@pytest.fixture
def tool_ctx() -> Any:
    token = _current_tool_ctx.set(
        ToolCallContext(
            task_goal="send artifact",
            session_id="s1",
            task_id="t1",
            agent_type="sebastian",
        )
    )
    try:
        yield
    finally:
        _current_tool_ctx.reset(token)


@pytest.mark.asyncio
async def test_manager_save_download_sanitizes_name_and_writes_manifest(tmp_path: Path) -> None:
    manager = BrowserSessionManager(_settings(tmp_path))

    record = await manager.save_download(_FakeDownload())

    assert record.filename == "Quarterly Report.pdf"
    assert record.path.is_relative_to(manager.downloads_dir)
    assert record.path.read_bytes() == b"%PDF-1.7\nreport"
    assert record.source_url == "https://example.com/report.pdf"

    manifest_lines = (
        (manager.downloads_dir / "downloads.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    manifest = json.loads(manifest_lines[-1])
    assert manifest["filename"] == "Quarterly Report.pdf"
    assert manifest["original"] == "../Quarterly Report.pdf"
    assert manifest["path"] == str(record.path)
    assert manifest["source_url"] == "https://example.com/report.pdf"
    assert "token=secret" not in json.dumps(manifest)


@pytest.mark.asyncio
async def test_manager_concurrent_downloads_do_not_overwrite(tmp_path: Path) -> None:
    manager = BrowserSessionManager(_settings(tmp_path))

    first, second = await asyncio.gather(
        manager.save_download(_FakeDownload("report.pdf")),
        manager.save_download(_FakeDownload("report.pdf")),
    )

    assert first.filename == "report.pdf"
    assert second.filename == "report-1.pdf"
    assert first.path != second.path
    assert first.path.exists()
    assert second.path.exists()


@pytest.mark.asyncio
async def test_browser_downloads_list_omits_local_paths(tmp_path: Path) -> None:
    manager = BrowserSessionManager(_settings(tmp_path))
    await manager.save_download(_FakeDownload())

    result = await list_downloads(manager)

    assert result
    assert result[0]["filename"] == "Quarterly Report.pdf"
    assert "path" not in result[0]


@pytest.mark.asyncio
async def test_manager_act_reports_download_triggered_by_action(tmp_path: Path) -> None:
    manager = BrowserSessionManager(_settings(tmp_path))
    manager._page = _DownloadClickPage(manager)  # type: ignore[assignment]
    manager._current_page_owned_by_browser_tool = True

    result = await manager.act(action="click", target="a.download")

    assert result["download"] == {
        "filename": "clicked.pdf",
        "mime": "application/pdf",
        "size": 15,
        "mtime": result["download"]["mtime"],
        "original": "clicked.pdf",
        "source_url": "https://example.com/report.pdf",
        "created_at": result["download"]["created_at"],
    }


@pytest.mark.asyncio
async def test_browser_downloads_send_rejects_traversal(tmp_path: Path, tool_ctx: Any) -> None:
    from sebastian.capabilities.tools.browser import browser_downloads

    manager = BrowserSessionManager(_settings(tmp_path))
    fake_state = MagicMock(browser_manager=manager, attachment_store=_FakeAttachmentStore())

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_downloads(action="send", filename="../secret.pdf")

    assert result.ok is False
    assert "Do not retry automatically" in (result.error or "")
    assert "/secret.pdf" not in (result.error or "")


@pytest.mark.asyncio
async def test_resolve_download_ignores_manifest_path_outside_downloads(
    tmp_path: Path,
) -> None:
    manager = BrowserSessionManager(_settings(tmp_path))
    await manager.save_download(_FakeDownload())
    manifest = manager.downloads_dir / "downloads.jsonl"
    row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[-1])
    row["path"] = str(tmp_path / "outside.pdf")
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    record = await manager.resolve_download("Quarterly Report.pdf")

    assert record.path == (manager.downloads_dir / "Quarterly Report.pdf").resolve()


@pytest.mark.asyncio
async def test_browser_downloads_send_uploads_download_artifact(
    tmp_path: Path, tool_ctx: Any
) -> None:
    from sebastian.capabilities.tools.browser import browser_downloads

    manager = BrowserSessionManager(_settings(tmp_path))
    await manager.save_download(_FakeDownload())
    store = _FakeAttachmentStore()
    fake_state = MagicMock(browser_manager=manager, attachment_store=store)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_downloads(action="send", filename="Quarterly Report.pdf")

    assert result.ok is True
    assert result.output["artifact"]["kind"] == "download"
    assert result.output["artifact"]["filename"] == "Quarterly Report.pdf"
    assert result.output["artifact"]["download_url"] == "/api/v1/attachments/att-1"
    assert store.uploads[0]["kind"] == "download"
    assert store.uploads[0]["content_type"] == "application/pdf"
    assert store.marked == [
        {"attachment_id": "att-1", "agent_type": "sebastian", "session_id": "s1"}
    ]


@pytest.mark.asyncio
async def test_browser_capture_uploads_image_artifact_and_removes_temp(
    tmp_path: Path, tool_ctx: Any
) -> None:
    from sebastian.capabilities.tools.browser import browser_capture

    screenshot_path = tmp_path / "data" / "browser" / "screenshots" / "shot.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\nbytes")
    manager = MagicMock()
    manager.capture_screenshot = MagicMock(
        return_value=BrowserScreenshotResult(
            path=screenshot_path,
            url="https://example.com/report",
        )
    )
    store = _FakeAttachmentStore()
    fake_state = MagicMock(browser_manager=manager, attachment_store=store)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_capture()

    assert result.ok is True
    assert result.output["artifact"]["kind"] == "image"
    assert result.output["artifact"]["filename"] == "shot.png"
    assert store.uploads[0]["kind"] == "image"
    assert screenshot_path.exists() is False
