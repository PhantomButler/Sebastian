# mypy: disable-error-code=import-untyped

from __future__ import annotations

import asyncio
import json
import os
import weakref
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

if TYPE_CHECKING:
    from sebastian.store.session_store import SessionStore

import aiofiles

from sebastian.core.types import Session

INDEX_FILE = "index.json"
# WeakValueDictionary lets unreferenced locks be GC'd, preventing unbounded growth (m2).
_LOCKS_BY_PATH: weakref.WeakValueDictionary[Path, asyncio.Lock] = weakref.WeakValueDictionary()


class IndexStore:
    """Read and write the top-level session listing index.

    DEPRECATED: IndexStore is no longer used at runtime.  All session metadata
    is now persisted via SessionRecordsStore (SQLite).  This class is kept only
    for potential migration tooling and will be removed in a future release.
    """

    def __init__(self, sessions_dir: Path, session_store: SessionStore | None = None) -> None:
        self._path = sessions_dir / INDEX_FILE
        resolved = self._path.resolve()
        lock = _LOCKS_BY_PATH.get(resolved)
        if lock is None:
            lock = asyncio.Lock()
            _LOCKS_BY_PATH[resolved] = lock
        self._lock = lock
        self._session_store = session_store

    async def _read(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        async with aiofiles.open(self._path) as file:
            raw = await file.read()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return []
        sessions = data.get("sessions")
        if not isinstance(sessions, list):
            return []
        return [cast(dict[str, Any], session) for session in sessions if isinstance(session, dict)]

    async def _write(self, sessions: list[dict[str, Any]]) -> None:
        payload = json.dumps({"version": 1, "sessions": sessions}, default=str)
        temp_path = self._path.with_name(f"{self._path.name}.{uuid4().hex}.tmp")
        async with aiofiles.open(temp_path, "w") as file:
            await file.write(payload)
        os.replace(temp_path, self._path)

    async def upsert(self, session: Session) -> None:
        async with self._lock:
            sessions = await self._read()
            entry = {
                "id": session.id,
                "agent_type": session.agent_type,
                "title": session.title,
                "goal": session.goal,
                "status": session.status.value,
                "depth": session.depth,
                "parent_session_id": session.parent_session_id,
                "last_activity_at": session.last_activity_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "task_count": session.task_count,
                "active_task_count": session.active_task_count,
            }
            sessions = [existing for existing in sessions if existing["id"] != session.id]
            sessions.insert(0, entry)
            await self._write(sessions)

    async def list_all(self) -> list[dict[str, Any]]:
        return await self._read()

    async def list_by_agent_type(self, agent_type: str) -> list[dict[str, Any]]:
        return [
            session for session in await self._read() if session.get("agent_type") == agent_type
        ]

    async def list_active_children(
        self,
        agent_type: str,
        parent_session_id: str,
    ) -> list[dict[str, Any]]:
        """List active/stalled/waiting child sessions for a given parent session.

        All three statuses occupy max_children slots per spec §3.3.
        """
        return [
            s
            for s in await self._read()
            if s.get("agent_type") == agent_type
            and s.get("parent_session_id") == parent_session_id
            and s.get("status") in ("active", "stalled", "waiting")
        ]

    async def update_activity(self, session_id: str) -> None:
        """Update last_activity_at for a session.

        Also transitions stalled sessions back to active — if a stalled session
        receives a tool call it means it's no longer stuck.
        Syncs the change to meta.json via injected session_store (if present).
        """
        agent_type: str | None = None
        async with self._lock:
            sessions = await self._read()
            now = datetime.now(UTC).isoformat()
            for entry in sessions:
                if entry["id"] == session_id:
                    entry["last_activity_at"] = now
                    if entry.get("status") == "stalled":
                        entry["status"] = "active"
                    agent_type = entry.get("agent_type")
                    break
            await self._write(sessions)

        if self._session_store is not None and agent_type is not None:
            await self._session_store.update_activity(session_id, agent_type)

    async def prune_orphans(self, sessions_dir: Path) -> list[dict[str, Any]]:
        """剔除磁盘目录不存在的索引条目，返回被剔除条目列表。

        启动时调用：sub-agent 重命名或目录被人为删除后，index 里残留的死引用
        会让 UI 列表显示出点不开的会话。这里一次性对齐磁盘真实状态。
        """
        async with self._lock:
            sessions = await self._read()
            kept: list[dict[str, Any]] = []
            dropped: list[dict[str, Any]] = []
            for entry in sessions:
                disk_dir = sessions_dir / entry["agent_type"] / entry["id"]
                (kept if disk_dir.exists() else dropped).append(entry)
            if dropped:
                await self._write(kept)
            return dropped

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            sessions = await self._read()
            sessions = [session for session in sessions if session["id"] != session_id]
            await self._write(sessions)
