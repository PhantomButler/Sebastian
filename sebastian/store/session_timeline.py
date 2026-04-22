from __future__ import annotations

import asyncio
import logging
import weakref
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.store.models import SessionItemRecord, SessionRecord

logger = logging.getLogger(__name__)

# kind 值不进入"上下文窗口"投影的黑名单
_CONTEXT_EXCLUDED_KINDS = frozenset({"thinking", "raw_block"})

# role → kind 转换规则（无 blocks 时）
_ROLE_TO_KIND: dict[str, str] = {
    "user": "user_message",
    "system": "system_event",
    "assistant": "assistant_message",
}

# block type → kind
_BLOCK_TYPE_TO_KIND: dict[str, str] = {
    "thinking": "thinking",
    "text": "assistant_message",
    "tool": "tool_call",
    "tool_use": "tool_call",
    "tool_result": "tool_result",
}

# Per-session asyncio locks for seq allocation serialization.
# WeakValueDictionary lets unreferenced locks be GC'd.
_SESSION_SEQ_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def _get_session_lock(session_id: str, agent_type: str) -> asyncio.Lock:
    key = f"{agent_type}:{session_id}"
    lock = _SESSION_SEQ_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_SEQ_LOCKS[key] = lock
    return lock


class TimelineItemInput(dict[str, Any]):
    """Dict subclass for timeline item input (supports TypedDict-like usage)."""


def _record_to_dict(record: SessionItemRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "agent_type": record.agent_type,
        "seq": record.seq,
        "effective_seq": record.effective_seq,
        "kind": record.kind,
        "role": record.role,
        "content": record.content,
        "payload": record.payload if record.payload is not None else {},
        "archived": record.archived,
        "turn_id": record.turn_id,
        "provider_call_index": record.provider_call_index,
        "block_index": record.block_index,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


class SessionTimelineStore:
    """SQLite-backed timeline item reads and writes for a session.

    Seq allocation uses a per-session asyncio.Lock to serialize concurrent
    appends within a process.  This is correct for aiosqlite (single-threaded)
    and is equivalent to SELECT ... FOR UPDATE semantics for in-process concurrency.
    Each append runs in its own committed transaction; the lock prevents two
    coroutines from reading the same next_item_seq before either updates it.
    """

    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db = db_factory

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def append_items(
        self,
        session_id: str,
        agent_type: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Append items atomically; returns the inserted item dicts."""
        if not items:
            return []

        lock = _get_session_lock(session_id, agent_type)
        async with lock:
            return await self._append_items_locked(session_id, agent_type, items)

    async def _append_items_locked(
        self,
        session_id: str,
        agent_type: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute within the per-session lock; no concurrent seq race possible."""
        now = datetime.now(UTC)
        n = len(items)

        async with self._db() as db:
            async with db.begin():
                # Read-modify-write next_item_seq; lock already held above.
                result = await db.execute(
                    select(SessionRecord).where(
                        SessionRecord.id == session_id,
                        SessionRecord.agent_type == agent_type,
                    )
                )
                session_row = result.scalar_one_or_none()
                if session_row is None:
                    raise ValueError(
                        f"Session {session_id!r} (agent={agent_type!r}) not found"
                    )

                start_seq = session_row.next_item_seq
                session_row.next_item_seq = start_seq + n

                inserted: list[dict[str, Any]] = []
                for i, item in enumerate(items):
                    seq = start_seq + i
                    record = SessionItemRecord(
                        id=str(uuid4()),
                        session_id=session_id,
                        agent_type=agent_type,
                        seq=seq,
                        kind=item.get("kind", "raw_block"),
                        role=item.get("role"),
                        content=item.get("content", ""),
                        payload=item.get("payload", {}),
                        archived=item.get("archived", False),
                        turn_id=item.get("turn_id"),
                        provider_call_index=item.get("provider_call_index"),
                        block_index=item.get("block_index"),
                        effective_seq=item.get("effective_seq", seq),
                        created_at=now,
                    )
                    db.add(record)
                    inserted.append(_record_to_dict(record))

        return inserted

    def _message_to_items(
        self,
        role: str,
        content: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Convert a role/content/blocks message into timeline item dicts."""
        if not blocks:
            kind = _ROLE_TO_KIND.get(role, "raw_block")
            return [{"kind": kind, "role": role, "content": content}]

        # role == "assistant" with blocks
        result: list[dict[str, Any]] = []
        for idx, block in enumerate(blocks):
            block_type = block.get("type", "")
            kind = _BLOCK_TYPE_TO_KIND.get(block_type, "raw_block")
            block_content = block.get("text") or block.get("content") or ""
            result.append({
                "kind": kind,
                "role": role,
                "content": block_content,
                "block_index": idx,
                "payload": {k: v for k, v in block.items() if k not in ("text", "content")},
            })
        return result

    async def append_message_compat(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_type: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        """Convert a legacy message call into timeline items and persist."""
        items = self._message_to_items(role, content, blocks)
        await self.append_items(session_id, agent_type, items)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_context_items(
        self,
        session_id: str,
        agent_type: str,
    ) -> list[dict[str, Any]]:
        """Return non-archived items ordered by (effective_seq, seq).

        context_summary items are included; thinking/raw_block are excluded.
        """
        async with self._db() as db:
            result = await db.execute(
                select(SessionItemRecord)
                .where(
                    SessionItemRecord.session_id == session_id,
                    SessionItemRecord.agent_type == agent_type,
                    SessionItemRecord.archived.is_(False),
                    SessionItemRecord.kind.not_in(_CONTEXT_EXCLUDED_KINDS),
                )
                .order_by(
                    SessionItemRecord.effective_seq.asc(),
                    SessionItemRecord.seq.asc(),
                )
            )
            return [_record_to_dict(r) for r in result.scalars()]

    async def get_items(
        self,
        session_id: str,
        agent_type: str,
        include_archived: bool = True,
    ) -> list[dict[str, Any]]:
        """Return items ordered by seq.

        When include_archived=False, only non-archived items are returned.
        """
        async with self._db() as db:
            q = select(SessionItemRecord).where(
                SessionItemRecord.session_id == session_id,
                SessionItemRecord.agent_type == agent_type,
            )
            if not include_archived:
                q = q.where(SessionItemRecord.archived.is_(False))
            q = q.order_by(SessionItemRecord.seq.asc())
            result = await db.execute(q)
            return [_record_to_dict(r) for r in result.scalars()]

    async def get_recent_items(
        self,
        session_id: str,
        agent_type: str,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return the most recent *limit* non-archived items in ascending seq order."""
        async with self._db() as db:
            result = await db.execute(
                select(SessionItemRecord)
                .where(
                    SessionItemRecord.session_id == session_id,
                    SessionItemRecord.agent_type == agent_type,
                    SessionItemRecord.archived.is_(False),
                )
                .order_by(SessionItemRecord.seq.desc())
                .limit(limit)
            )
            rows = list(result.scalars())
        # reverse to get ascending order
        rows.sort(key=lambda r: r.seq)
        return [_record_to_dict(r) for r in rows]

    async def get_items_since(
        self,
        session_id: str,
        agent_type: str,
        after_seq: int,
        include_kinds: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return items with seq > after_seq, excluding thinking/raw_block by default."""
        excluded = _CONTEXT_EXCLUDED_KINDS
        async with self._db() as db:
            q = (
                select(SessionItemRecord)
                .where(
                    SessionItemRecord.session_id == session_id,
                    SessionItemRecord.agent_type == agent_type,
                    SessionItemRecord.seq > after_seq,
                    SessionItemRecord.kind.not_in(excluded),
                )
                .order_by(SessionItemRecord.seq.asc())
            )
            if include_kinds is not None:
                q = q.where(SessionItemRecord.kind.in_(include_kinds))
            result = await db.execute(q)
            return [_record_to_dict(r) for r in result.scalars()]
