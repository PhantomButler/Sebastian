from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.types import Session
from sebastian.store.session_store import SessionStore


@pytest.fixture
async def sqlite_session_factory():
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import Base, _apply_idempotent_migrations

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


@pytest.fixture
async def store(sqlite_session_factory):
    return SessionStore(db_factory=sqlite_session_factory)


@pytest.fixture
async def session_in_db(store):
    s = Session(agent_type="sebastian", title="Test")
    await store.create_session(s)
    return s


@pytest.mark.asyncio
async def test_tool_result_artifact_persisted_in_timeline_payload(store, session_in_db) -> None:
    """tool_result block の artifact フィールドは payload に保存されること。"""
    artifact = {"kind": "image", "attachment_id": "att-1", "filename": "photo.png"}
    blocks = [
        {
            "type": "tool",
            "tool_call_id": "toolu_1",
            "tool_name": "send_file",
            "input": {"attachment_id": "att-1"},
            "status": "done",
            "assistant_turn_id": "turn-1",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "type": "tool_result",
            "tool_call_id": "toolu_1",
            "tool_name": "send_file",
            "model_content": "已向用户发送图片 photo.png",
            "display": "已向用户发送图片 photo.png",
            "ok": True,
            "artifact": artifact,
            "assistant_turn_id": "turn-1",
            "provider_call_index": 0,
            "block_index": 1,
        },
    ]
    await store.append_message(
        session_in_db.id,
        "assistant",
        "",
        agent_type="sebastian",
        blocks=blocks,
    )
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    result_items = [i for i in items if i["kind"] == "tool_result"]
    assert len(result_items) == 1
    payload = result_items[0]["payload"]
    assert "artifact" in payload, f"artifact missing from payload: {payload}"
    assert payload["artifact"]["attachment_id"] == "att-1"
    assert payload["artifact"]["kind"] == "image"
    assert payload["artifact"]["filename"] == "photo.png"


@pytest.mark.asyncio
async def test_download_artifact_persisted_in_timeline_payload_unchanged(
    store, session_in_db
) -> None:
    artifact = {
        "kind": "download",
        "attachment_id": "att-download",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1234,
        "download_url": "/api/v1/attachments/att-download",
    }
    blocks = [
        {
            "type": "tool_result",
            "tool_call_id": "toolu_download",
            "tool_name": "browser_download",
            "model_content": "已向用户发送文件 report.pdf",
            "display": "已向用户发送文件 report.pdf",
            "ok": True,
            "artifact": artifact,
            "assistant_turn_id": "turn-download",
            "provider_call_index": 0,
            "block_index": 0,
        },
    ]

    await store.append_message(
        session_in_db.id,
        "assistant",
        "",
        agent_type="sebastian",
        blocks=blocks,
    )

    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    result_items = [i for i in items if i["kind"] == "tool_result"]
    assert len(result_items) == 1
    assert result_items[0]["payload"]["artifact"] == artifact


@pytest.mark.asyncio
async def test_tool_result_without_artifact_has_no_artifact_in_payload(
    store, session_in_db
) -> None:
    """artifact なしの tool_result は payload に artifact キーを持たないこと。"""
    blocks = [
        {
            "type": "tool_result",
            "tool_call_id": "toolu_2",
            "tool_name": "list_files",
            "model_content": "3 files found",
            "display": "3 files found",
            "ok": True,
            "assistant_turn_id": "turn-2",
            "provider_call_index": 0,
            "block_index": 0,
        },
    ]
    await store.append_message(
        session_in_db.id,
        "assistant",
        "",
        agent_type="sebastian",
        blocks=blocks,
    )
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    result_items = [i for i in items if i["kind"] == "tool_result"]
    assert len(result_items) == 1
    payload = result_items[0]["payload"]
    assert "artifact" not in payload, f"artifact should not be in payload: {payload}"
