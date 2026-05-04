from __future__ import annotations

from types import SimpleNamespace

import pytest


class _BrowserManager:
    def __init__(self, calls: list[str], *, fail: bool = False) -> None:
        self._calls = calls
        self._fail = fail

    async def aclose(self) -> None:
        self._calls.append("browser_close")
        if self._fail:
            raise RuntimeError("browser close failed")


class _Engine:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def dispose(self) -> None:
        self._calls.append("db_dispose")


@pytest.mark.asyncio
async def test_browser_manager_shutdown_happens_before_database_dispose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sebastian.gateway.app as app_module

    calls: list[str] = []
    state = SimpleNamespace(
        browser_manager=_BrowserManager(calls),
        context_compaction_scheduler=object(),
        context_compaction_worker=object(),
    )

    monkeypatch.setattr("sebastian.store.database.get_engine", lambda: _Engine(calls))

    await app_module._close_browser_before_database_dispose(state)

    assert calls == ["browser_close", "db_dispose"]
    assert state.browser_manager is None
    assert state.context_compaction_scheduler is None
    assert state.context_compaction_worker is None


@pytest.mark.asyncio
async def test_database_dispose_still_happens_when_browser_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sebastian.gateway.app as app_module

    calls: list[str] = []
    state = SimpleNamespace(
        browser_manager=_BrowserManager(calls, fail=True),
        context_compaction_scheduler=object(),
        context_compaction_worker=object(),
    )

    monkeypatch.setattr("sebastian.store.database.get_engine", lambda: _Engine(calls))

    with pytest.raises(RuntimeError, match="browser close failed"):
        await app_module._close_browser_before_database_dispose(state)

    assert calls == ["browser_close", "db_dispose"]
    assert state.context_compaction_scheduler is None
    assert state.context_compaction_worker is None
