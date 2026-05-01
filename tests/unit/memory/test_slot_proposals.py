from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.errors import InvalidSlotProposalError
from sebastian.memory.stores.slot_definition_store import SlotDefinitionStore
from sebastian.memory.slot_proposals import SlotProposalHandler, validate_proposed_slot
from sebastian.memory.slots import SlotRegistry
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ProposedSlot,
    ResolutionPolicy,
)
from sebastian.store.models import Base

_SENTINEL: list[MemoryKind] = []


def _make(
    *,
    slot_id: str = "user.profile.hobby",
    scope: MemoryScope = MemoryScope.USER,
    cardinality: Cardinality = Cardinality.MULTI,
    resolution_policy: ResolutionPolicy = ResolutionPolicy.APPEND_ONLY,
    kind_constraints: list[MemoryKind] | None = None,
) -> ProposedSlot:
    # kind_constraints=None → 默认 [PREFERENCE]；kind_constraints=[] → 真正空列表
    if kind_constraints is None:
        resolved_constraints = [MemoryKind.PREFERENCE]
    else:
        resolved_constraints = kind_constraints
    return ProposedSlot(
        slot_id=slot_id,
        scope=scope,
        subject_kind="user",
        cardinality=cardinality,
        resolution_policy=resolution_policy,
        kind_constraints=resolved_constraints,
        description="x",
    )


def test_valid_slot_passes() -> None:
    validate_proposed_slot(_make())


@pytest.mark.parametrize(
    "bad_id",
    [
        "user.profile",  # 段数不对
        "user.profile.like.book",  # 段数太多
        "User.profile.hobby",  # 大写
        "user.profile.like-book",  # 连字符
        "other.profile.hobby",  # 首段非合法 scope
        "a" * 70 + ".x.y",  # 超长
        ".profile.hobby",  # 空段
        "user..hobby",  # 空段
        "user.profile.",  # 尾空
    ],
)
def test_invalid_naming_rejected(bad_id: str) -> None:
    with pytest.raises(InvalidSlotProposalError, match="命名规则"):
        validate_proposed_slot(_make(slot_id=bad_id))


def test_scope_prefix_must_match_slot_id() -> None:
    with pytest.raises(InvalidSlotProposalError, match="scope"):
        validate_proposed_slot(_make(slot_id="user.profile.hobby", scope=MemoryScope.PROJECT))


def test_single_with_append_only_rejected() -> None:
    with pytest.raises(InvalidSlotProposalError, match="组合"):
        validate_proposed_slot(
            _make(cardinality=Cardinality.SINGLE, resolution_policy=ResolutionPolicy.APPEND_ONLY)
        )


def test_time_bound_requires_fact_or_preference() -> None:
    with pytest.raises(InvalidSlotProposalError, match="time_bound"):
        validate_proposed_slot(
            _make(
                resolution_policy=ResolutionPolicy.TIME_BOUND,
                kind_constraints=[MemoryKind.EPISODE],
            )
        )


def test_empty_kind_constraints_rejected() -> None:
    # Pydantic 允许 list 为空，校验器要把关
    with pytest.raises(InvalidSlotProposalError, match="kind_constraints"):
        validate_proposed_slot(_make(kind_constraints=[]))


# ---------------------------------------------------------------------------
# SlotProposalHandler tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_register_new_slot_writes_db_and_registry(db) -> None:
    registry = SlotRegistry(slots=[])
    async with db() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        schema = await handler.register_or_reuse(
            _make(),
            proposed_by="extractor",
            proposed_in_session="sess-1",
        )
        await session.commit()
    assert schema.slot_id == "user.profile.hobby"
    assert registry.get("user.profile.hobby") is not None


@pytest.mark.asyncio
async def test_existing_slot_reused_not_overwritten(db) -> None:
    registry = SlotRegistry(slots=[])
    async with db() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        await handler.register_or_reuse(_make(), proposed_by="extractor", proposed_in_session=None)
        await session.commit()

    async with db() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        # 第二次提议同 id（registry 已有，直接 reuse）
        schema = await handler.register_or_reuse(
            _make(),  # description="x"
            proposed_by="consolidator",
            proposed_in_session="sess-2",
        )
        await session.commit()

    # 返回的是已存在的 schema（description 仍是原 "x"，未覆盖）
    assert schema.description == "x"


@pytest.mark.asyncio
async def test_invalid_proposal_raises(db) -> None:
    registry = SlotRegistry(slots=[])
    async with db() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        # cardinality=single + resolution_policy=append_only 是非法组合
        bad_raw = ProposedSlot(
            slot_id="user.profile.hobby",
            scope=MemoryScope.USER,
            subject_kind="user",
            cardinality=Cardinality.SINGLE,
            resolution_policy=ResolutionPolicy.APPEND_ONLY,  # invalid combo
            kind_constraints=[MemoryKind.PREFERENCE],
            description="x",
        )
        with pytest.raises(InvalidSlotProposalError):
            await handler.register_or_reuse(
                bad_raw, proposed_by="extractor", proposed_in_session=None
            )


@pytest.mark.asyncio
async def test_concurrent_race_reuses_winner(db) -> None:
    """模拟两个 session 几乎同时 insert 同一 slot_id，第二个撞 IntegrityError 后读赢家。"""
    registry = SlotRegistry(slots=[])
    # Worker A 先写入
    async with db() as session_a:
        store = SlotDefinitionStore(session_a)
        handler_a = SlotProposalHandler(store=store, registry=registry)
        await handler_a.register_or_reuse(
            _make(), proposed_by="extractor", proposed_in_session="sess-A"
        )
        await session_a.commit()

    # Worker B 清空内存 registry 后再跑，模拟"未感知已写入"
    registry_b = SlotRegistry(slots=[])
    async with db() as session_b:
        store = SlotDefinitionStore(session_b)
        handler_b = SlotProposalHandler(store=store, registry=registry_b)
        schema = await handler_b.register_or_reuse(
            _make(),  # 同 slot_id
            proposed_by="consolidator",
            proposed_in_session="sess-B",
        )
        await session_b.commit()
    # 复用赢家：拿到的是 A 写入的那行
    assert schema.slot_id == "user.profile.hobby"
    # registry_b 内存也同步了
    assert registry_b.get("user.profile.hobby") is not None
