from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import patch


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
