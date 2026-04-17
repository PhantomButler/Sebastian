from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_sqlite_foreign_keys_pragma_is_on() -> None:
    """sebastian.store.database.get_engine() 创建的 engine 必须启用 foreign_keys。"""
    import sebastian.store.database as db_mod

    # Reset module state so get_engine builds a fresh engine for this test
    db_mod._engine = None
    db_mod._session_factory = None

    # Use tmp in-memory db
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    try:
        # Apply the pragma listener by touching the helper that installs it
        db_mod._install_sqlite_fk_pragma(engine)
        async with engine.begin() as conn:
            result = await conn.exec_driver_sql("PRAGMA foreign_keys")
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1, f"PRAGMA foreign_keys expected 1, got {row[0]}"
    finally:
        await engine.dispose()
        # Restore module state
        db_mod._engine = None
        db_mod._session_factory = None
