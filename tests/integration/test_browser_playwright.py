from __future__ import annotations

import os
from pathlib import Path

import pytest

from sebastian.config import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("SEBASTIAN_RUN_PLAYWRIGHT_TESTS") != "1",
    reason="Set SEBASTIAN_RUN_PLAYWRIGHT_TESTS=1 to run real Playwright browser tests.",
)


@pytest.mark.asyncio
async def test_browser_manager_can_open_public_page_with_playwright(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

    manager = BrowserSessionManager(Settings(sebastian_data_dir=str(tmp_path)))
    try:
        result = await manager.open("https://example.com/")
        assert result.ok is True, result.error

        metadata = await manager.current_page_metadata()
        assert metadata is not None
        assert metadata.url.startswith("https://example.com")
        assert metadata.title
    finally:
        await manager.aclose()
