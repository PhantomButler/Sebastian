from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sebastian.memory.entity_registry import EntityRegistry


@pytest.mark.asyncio
async def test_upsert_new_entity_triggers_reload(db_session) -> None:
    planner = AsyncMock()
    registry = EntityRegistry(db_session, planner=planner)
    await registry.upsert_entity(
        canonical_name="王总",
        entity_type="person",
        aliases=["王先生"],
    )
    planner.reload_entity_triggers.assert_awaited_once_with(registry)


@pytest.mark.asyncio
async def test_upsert_existing_entity_merging_aliases_triggers_reload(
    db_session,
) -> None:
    planner = AsyncMock()
    registry = EntityRegistry(db_session, planner=planner)
    await registry.upsert_entity(canonical_name="小美", entity_type="person")
    await registry.upsert_entity(canonical_name="小美", entity_type="person", aliases=["美美"])
    assert planner.reload_entity_triggers.await_count == 2


@pytest.mark.asyncio
async def test_none_planner_skips_reload(db_session) -> None:
    registry = EntityRegistry(db_session, planner=None)
    record = await registry.upsert_entity(canonical_name="独行者", entity_type="person")
    assert record.canonical_name == "独行者"


@pytest.mark.asyncio
async def test_list_all_names_and_aliases_flat_order(db_session) -> None:
    registry = EntityRegistry(db_session)
    await registry.upsert_entity(canonical_name="小美", entity_type="person", aliases=["美美"])
    await registry.upsert_entity(canonical_name="王总", entity_type="person", aliases=[])
    names = await registry.list_all_names_and_aliases()
    assert "小美" in names
    assert "美美" in names
    assert "王总" in names


@pytest.mark.asyncio
async def test_sync_jieba_terms_still_works(db_session, monkeypatch) -> None:
    """重构后 sync_jieba_terms 应复用 list_all_names_and_aliases，行为不变。"""
    from sebastian.memory import entity_registry as er_mod

    captured: list[list[str]] = []

    def _fake_add(terms: list[str]) -> None:
        captured.append(list(terms))

    monkeypatch.setattr(er_mod, "add_entity_terms", _fake_add)

    registry = EntityRegistry(db_session)
    await registry.upsert_entity(canonical_name="小美", entity_type="person", aliases=["美美"])
    await registry.sync_jieba_terms()
    assert captured and "小美" in captured[-1] and "美美" in captured[-1]
