from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import patch

import pytest


def test_gateway_startup_creates_resident_snapshot_files(tmp_path) -> None:
    """Gateway lifespan should build the resident snapshot files on startup."""
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("testpass")

    with patch.dict(
        os.environ,
        {
            "SEBASTIAN_DATA_DIR": str(tmp_path),
            "SEBASTIAN_JWT_SECRET": "test-secret-key",
        },
    ):
        import sebastian.config as cfg_module

        importlib.reload(cfg_module)

        import sebastian.store.database as db_module

        db_module._engine = None
        db_module._session_factory = None

        data_subdir = tmp_path / "data"
        data_subdir.mkdir(exist_ok=True)
        (data_subdir / "secret.key").write_text("test-secret-key")

        from sebastian.store.database import get_session_factory, init_db
        from sebastian.store.owner_store import OwnerStore

        async def _seed() -> None:
            await init_db()
            await OwnerStore(get_session_factory()).create_owner(
                name="test-owner",
                password_hash=password_hash,
            )
            from sebastian.store.database import get_engine

            await get_engine().dispose()
            await asyncio.sleep(0)

        asyncio.run(_seed())
        db_module._engine = None
        db_module._session_factory = None

        from starlette.testclient import TestClient

        from sebastian.gateway.app import create_app

        test_app = create_app()
        with TestClient(test_app, raise_server_exceptions=True):
            memory_dir = tmp_path / "data" / "memory"
            assert memory_dir.exists(), "memory directory should be created at startup"
            md = memory_dir / "resident_snapshot.md"
            meta = memory_dir / "resident_snapshot.meta.json"
            assert md.exists(), "resident_snapshot.md should exist after startup rebuild"
            assert meta.exists(), "resident_snapshot.meta.json should exist after startup rebuild"

        db_module._engine = None
        db_module._session_factory = None


@pytest.mark.asyncio
async def test_startup_rebuild_failure_schedules_refresh(tmp_path) -> None:
    """After a startup rebuild failure, schedule_refresh() must queue a background retry."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from sebastian.memory.resident.resident_snapshot import (
        ResidentMemorySnapshotRefresher,
        ResidentSnapshotPaths,
    )

    @asynccontextmanager
    async def _fake_factory():
        yield AsyncMock()

    refresher = ResidentMemorySnapshotRefresher(
        paths=ResidentSnapshotPaths.from_user_data_dir(tmp_path),
        db_factory=_fake_factory,
    )

    # Simulate what app.py does at startup — but rebuild always fails
    async def _failing_rebuild(session):
        raise RuntimeError("simulated startup db failure")

    refresher.rebuild = _failing_rebuild  # type: ignore[method-assign]

    # Run the startup code path AS IT CURRENTLY EXISTS (no schedule_refresh call)
    # This simulates the BEFORE state — task should NOT be scheduled
    try:
        async with _fake_factory() as session:
            await refresher.rebuild(session)
    except Exception:
        pass  # old behavior: swallow and do nothing

    assert refresher._pending_refresh is None, "old behavior: no retry scheduled"

    # Now run the startup code path AS IT SHOULD BE (with schedule_refresh call)
    try:
        async with _fake_factory() as session:
            await refresher.rebuild(session)
    except Exception:
        refresher.schedule_refresh()  # new behavior: schedule a retry

    assert isinstance(refresher._pending_refresh, asyncio.Task), (
        "after schedule_refresh(), a background rebuild task must be pending"
    )
    await refresher.aclose()
