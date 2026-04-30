from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sebastian.memory.consolidation import SessionConsolidationWorker
from sebastian.memory.services.memory_service import MemoryService
from sebastian.memory.services.writing import MemoryWriteService
from sebastian.store.models import (
    Base,
    EpisodeMemoryRecord,
    ProfileMemoryRecord,
    SessionConsolidationRecord,
)
from tests.integration.test_memory_consolidation import (
    FakeConsolidator,
    FakeExtractor,
    FakeSessionStore,
)

# ---------------------------------------------------------------------------
# Fixtures
#
# NOTE: concurrent idempotency cannot be exercised on the default
# ``sqlite+aiosqlite:///:memory:`` engine — SQLAlchemy uses ``StaticPool``
# for in-memory SQLite, which forces every session to share the single
# underlying connection.  Two tasks then interleave inside one real SQLite
# transaction and ``IntegrityError`` is never raised.  We use a temporary
# file DB here so the default ``NullPool`` hands out independent
# connections and the ``SessionConsolidationRecord`` primary-key collision
# path is actually taken.
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="sebastian-memory-concurrency-")
    os.close(fd)
    eng = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    try:
        yield eng
    finally:
        await eng.dispose()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


@pytest.fixture
def db_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_consolidations_produce_one_marker(db_factory):
    """并发沉淀必须幂等：后到者撞 PK 时应回滚自己的写入，不抛异常。

    两个 worker 共享同一个 ``db_factory``，各自通过 ``async with``
    开独立的 AsyncSession。``SessionConsolidationRecord`` 的主键
    ``(session_id, agent_type)`` 在两次并发提交中只能落地一行，失败者
    命中 ``IntegrityError`` 被 ``consolidate_session`` 捕获并回滚，整个
    事务中的 summary / preference / decision log 写入一并撤销。
    """

    def build_worker() -> SessionConsolidationWorker:
        return SessionConsolidationWorker(
            db_factory=db_factory,
            consolidator=FakeConsolidator(),
            extractor=FakeExtractor(),
            session_store=FakeSessionStore(),
            memory_settings_fn=lambda: True,
            memory_service=MemoryService(
                db_factory=db_factory,
                writing=MemoryWriteService(db_factory=db_factory),
            ),
        )

    worker_a = build_worker()
    worker_b = build_worker()

    results = await asyncio.gather(
        worker_a.consolidate_session("s1", "default"),
        worker_b.consolidate_session("s1", "default"),
        return_exceptions=True,
    )

    # 两个协程都必须正常完成——IntegrityError 必须在 worker 内部被吞掉。
    assert all(not isinstance(r, Exception) for r in results), results

    async with db_factory() as session:
        # 标记行只能有一行
        marker_result = await session.scalars(
            select(SessionConsolidationRecord).where(
                SessionConsolidationRecord.session_id == "s1",
                SessionConsolidationRecord.agent_type == "default",
            )
        )
        markers = list(marker_result.all())
        assert len(markers) == 1

        # 不能出现重复 summary episode
        ep_result = await session.scalars(
            select(EpisodeMemoryRecord).where(EpisodeMemoryRecord.content == "会话摘要")
        )
        episodes = list(ep_result.all())
        assert len(episodes) == 1

        # 也不能出现重复 preference profile
        pr_result = await session.scalars(
            select(ProfileMemoryRecord).where(ProfileMemoryRecord.content == "用户喜欢简洁回复")
        )
        profiles = list(pr_result.all())
        assert len(profiles) == 1
