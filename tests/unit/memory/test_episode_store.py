from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.episode_store import EpisodeMemoryStore
from sebastian.memory.segmentation import segment_for_fts
from sebastian.memory.types import (
    MemoryArtifact,
    MemoryKind,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base
from sebastian.store.models import EpisodeMemoryRecord


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_artifact(**overrides: object) -> MemoryArtifact:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": "episode-response-style",
        "kind": MemoryKind.EPISODE,
        "scope": MemoryScope.USER,
        "subject_id": "owner",
        "slot_id": None,
        "cardinality": None,
        "resolution_policy": None,
        "content": "用户偏好简洁中文回复",
        "structured_payload": {"topic": "response_style"},
        "source": MemorySource.OBSERVED,
        "confidence": 0.91,
        "status": MemoryStatus.ACTIVE,
        "valid_from": None,
        "valid_until": None,
        "recorded_at": now,
        "last_accessed_at": None,
        "access_count": 0,
        "provenance": {"session_id": "sess-1"},
        "links": [],
        "embedding_ref": None,
        "dedupe_key": None,
        "policy_tags": [],
    }
    defaults.update(overrides)
    return MemoryArtifact(**defaults)  # type: ignore[arg-type]


async def test_add_episode_stores_content_and_segmented_content(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    artifact = _make_artifact()

    record = await store.add_episode(artifact)

    assert record.id == artifact.id
    assert record.content == "用户偏好简洁中文回复"
    assert record.content_segmented == segment_for_fts("用户偏好简洁中文回复")


async def test_search_matches_chinese_terms(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    await store.add_episode(_make_artifact(id="match-cn", content="用户偏好简洁中文回复"))
    await store.add_episode(_make_artifact(id="other", content="今天讨论了天气"))

    records = await store.search(subject_id="owner", query="用户", limit=8)

    assert [record.id for record in records] == ["match-cn"]


async def test_search_matches_registered_entity_term(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    await store.add_episode(_make_artifact(id="pet", content="小橘今天需要补充猫粮"))
    await store.add_episode(_make_artifact(id="other", content="项目计划明天继续"))

    records = await store.search(subject_id="owner", query="小橘", limit=8)

    assert [record.id for record in records] == ["pet"]


async def test_search_matches_english_terms(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    await store.add_episode(_make_artifact(id="english", content="Memory Artifact design reviewed"))
    await store.add_episode(_make_artifact(id="other", content="Gateway settings updated"))

    records = await store.search(subject_id="owner", query="Memory Artifact", limit=8)

    assert [record.id for record in records] == ["english"]


async def test_search_single_char_query_returns_empty(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    await store.add_episode(_make_artifact(id="cat", content="猫今天很安静"))

    records = await store.search(subject_id="owner", query="猫", limit=8)

    assert records == []


async def test_touch_increments_access_count_and_sets_last_accessed_at(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    await store.add_episode(_make_artifact(id="touch-1", access_count=2))
    await store.add_episode(_make_artifact(id="touch-2", access_count=0))

    await store.touch(["touch-1", "touch-2"])

    records = (
        await db_session.scalars(
            select(EpisodeMemoryRecord).where(EpisodeMemoryRecord.id.in_(["touch-1", "touch-2"]))
        )
    ).all()
    counts = {record.id: record.access_count for record in records}
    assert counts == {"touch-1": 3, "touch-2": 1}
    assert all(record.last_accessed_at is not None for record in records)


async def test_add_summary_stores_summary_kind(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    record = await store.add_summary(
        _make_artifact(
            id="summary-1",
            kind=MemoryKind.SUMMARY,
            content="本周完成 Memory Phase B 方案确认",
            recorded_at=datetime.now(UTC) + timedelta(minutes=1),
        )
    )

    assert record.kind == MemoryKind.SUMMARY.value
    assert record.content == "本周完成 Memory Phase B 方案确认"


async def test_search_summaries_returns_summaries_only(db_session) -> None:
    """search_summaries must only return SUMMARY-kind records, newest first."""
    store = EpisodeMemoryStore(db_session)
    base = datetime.now(UTC)

    # Two summaries, one regular episode
    await store.add_summary(
        _make_artifact(
            id="sum-old",
            kind=MemoryKind.SUMMARY,
            content="旧摘要",
            recorded_at=base - timedelta(hours=2),
        )
    )
    await store.add_episode(
        _make_artifact(
            id="episode-noise",
            kind=MemoryKind.EPISODE,
            content="不应被返回的普通 episode",
            recorded_at=base - timedelta(hours=1),
        )
    )
    await store.add_summary(
        _make_artifact(
            id="sum-new",
            kind=MemoryKind.SUMMARY,
            content="新摘要",
            recorded_at=base,
        )
    )

    results = await store.search_summaries(subject_id="owner", limit=8)

    assert [r.id for r in results] == ["sum-new", "sum-old"]
    assert all(r.kind == MemoryKind.SUMMARY.value for r in results)


async def test_search_summaries_respects_subject_filter(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    await store.add_summary(
        _make_artifact(id="owner-sum", kind=MemoryKind.SUMMARY, content="主人摘要")
    )
    await store.add_summary(
        _make_artifact(
            id="other-sum",
            kind=MemoryKind.SUMMARY,
            content="别人摘要",
            subject_id="agent:foo",
        )
    )

    results = await store.search_summaries(subject_id="owner", limit=8)

    assert [r.id for r in results] == ["owner-sum"]


async def test_search_summaries_respects_limit(db_session) -> None:
    store = EpisodeMemoryStore(db_session)
    base = datetime.now(UTC)
    for i in range(5):
        await store.add_summary(
            _make_artifact(
                id=f"sum-{i}",
                kind=MemoryKind.SUMMARY,
                content=f"摘要{i}",
                recorded_at=base + timedelta(seconds=i),
            )
        )

    results = await store.search_summaries(subject_id="owner", limit=2)

    assert len(results) == 2
