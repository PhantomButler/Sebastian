# mypy: disable-error-code=import-untyped

from __future__ import annotations

import asyncio
import json
import os
import shutil
import weakref
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import aiofiles

from sebastian.core.types import (
    Checkpoint,
    ResourceBudget,
    Session,
    Task,
    TaskPlan,
    TaskStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# WeakValueDictionary lets unreferenced locks be GC'd, preventing unbounded growth (m2).
_SESSION_LOCKS_BY_PATH: weakref.WeakValueDictionary[Path, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def _session_dir(sessions_dir: Path, session: Session) -> Path:
    """Return the session directory, creating the required structure."""
    directory = sessions_dir / session.agent_type / session.id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tasks").mkdir(exist_ok=True)
    return directory


def _session_dir_by_id(
    sessions_dir: Path,
    session_id: str,
    agent_type: str,
) -> Path:
    return sessions_dir / agent_type / session_id


class SessionStore:
    """Storage for sessions, messages, tasks, and checkpoints.

    When ``db_factory`` is provided, session metadata CRUD is delegated to
    ``SessionRecordsStore`` (SQLite).  The legacy file-based path remains as
    fallback for backward compatibility.
    """

    def __init__(
        self,
        sessions_dir: Path | None = None,
        db_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._dir = sessions_dir or Path("/tmp/sebastian-sessions-legacy")
        self._db_factory = db_factory
        if db_factory is not None:
            from sebastian.store.session_records import SessionRecordsStore
            from sebastian.store.session_timeline import SessionTimelineStore

            self._records: SessionRecordsStore | None = SessionRecordsStore(db_factory)
            self._timeline: SessionTimelineStore | None = SessionTimelineStore(db_factory)
        else:
            self._records = None
            self._timeline = None

    async def create_session(self, session: Session) -> Session:
        if self._records is not None:
            return await self._records.create(session)
        _session_dir(self._dir, session)
        async with self._session_lock(session.id, session.agent_type):
            await self._write_session_meta(session)
        return session

    async def get_session(
        self,
        session_id: str,
        agent_type: str = "sebastian",
    ) -> Session | None:
        if self._records is not None:
            return await self._records.get(session_id, agent_type)
        directory = _session_dir_by_id(self._dir, session_id, agent_type)
        meta_path = directory / "meta.json"
        if not meta_path.exists():
            return None
        async with aiofiles.open(meta_path) as file:
            raw = await file.read()
        return Session(**json.loads(raw))

    async def get_session_for_agent_type(
        self,
        session_id: str,
        agent_type: str,
    ) -> Session | None:
        """Look up a session by id and agent_type."""
        return await self.get_session(session_id, agent_type)

    async def update_session(self, session: Session) -> None:
        if self._records is not None:
            await self._records.update(session)
            return
        async with self._session_lock(session.id, session.agent_type):
            await self._write_session_meta(session)

    async def update_activity(self, session_id: str, agent_type: str) -> None:
        """Lightweight update: set last_activity_at=now, transition stalled→active."""
        if self._records is not None:
            await self._records.update_activity(session_id, agent_type)
            return
        async with self._session_lock(session_id, agent_type):
            directory = _session_dir_by_id(self._dir, session_id, agent_type)
            meta_path = directory / "meta.json"
            if not meta_path.exists():
                return
            async with aiofiles.open(meta_path) as f:
                data = json.loads(await f.read())
            data["last_activity_at"] = datetime.now(UTC).isoformat()
            if data.get("status") == "stalled":
                data["status"] = "active"
            await self._atomic_write_text(meta_path, json.dumps(data))

    async def delete_session(self, session: Session) -> None:
        if self._records is not None:
            await self._records.delete(session)
            return
        directory = _session_dir_by_id(self._dir, session.id, session.agent_type)
        if directory.exists():
            await asyncio.to_thread(shutil.rmtree, directory)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return metadata dicts for all sessions, ordered by last_activity_at desc."""
        if self._records is not None:
            return await self._records.list_all()
        sessions: list[dict[str, Any]] = []
        if not self._dir.exists():
            return sessions
        for agent_dir in self._dir.iterdir():
            if not agent_dir.is_dir():
                continue
            for session_dir in agent_dir.iterdir():
                meta_path = session_dir / "meta.json"
                if not meta_path.exists():
                    continue
                async with aiofiles.open(meta_path) as f:
                    data = json.loads(await f.read())
                sessions.append(data)
        return sorted(sessions, key=lambda s: s.get("last_activity_at", ""), reverse=True)

    async def list_sessions_by_agent_type(self, agent_type: str) -> list[dict[str, Any]]:
        """Return metadata dicts for sessions of the given agent_type."""
        if self._records is not None:
            return await self._records.list_by_agent_type(agent_type)
        sessions: list[dict[str, Any]] = []
        agent_dir = self._dir / agent_type
        if not agent_dir.exists():
            return sessions
        for session_dir in agent_dir.iterdir():
            meta_path = session_dir / "meta.json"
            if not meta_path.exists():
                continue
            async with aiofiles.open(meta_path) as f:
                data = json.loads(await f.read())
            sessions.append(data)
        return sorted(sessions, key=lambda s: s.get("last_activity_at", ""), reverse=True)

    async def list_active_children(
        self,
        agent_type: str,
        parent_session_id: str,
    ) -> list[dict[str, Any]]:
        """Return metadata dicts for active child sessions of the given parent."""
        if self._records is not None:
            return await self._records.list_active_children(agent_type, parent_session_id)
        active_statuses = {"active", "stalled", "waiting"}
        sessions: list[dict[str, Any]] = []
        agent_dir = self._dir / agent_type
        if not agent_dir.exists():
            return sessions
        for session_dir in agent_dir.iterdir():
            meta_path = session_dir / "meta.json"
            if not meta_path.exists():
                continue
            async with aiofiles.open(meta_path) as f:
                data = json.loads(await f.read())
            if (
                data.get("parent_session_id") == parent_session_id
                and data.get("status") in active_statuses
            ):
                sessions.append(data)
        return sessions

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_type: str = "sebastian",
        blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        if self._timeline is not None:
            await self._timeline.append_message_compat(
                session_id, role, content, agent_type, blocks
            )
            return
        directory = _session_dir_by_id(
            self._dir,
            session_id,
            agent_type,
        )
        entry: dict[str, Any] = {
            "role": role,
            "content": content,
            "ts": datetime.now(UTC).isoformat(),
        }
        if blocks:
            entry["blocks"] = blocks
        message = json.dumps(entry)
        async with aiofiles.open(directory / "messages.jsonl", "a") as file:
            await file.write(message + "\n")

    async def get_messages(
        self,
        session_id: str,
        agent_type: str = "sebastian",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if self._timeline is not None:
            return await self._timeline.get_recent_items(session_id, agent_type, limit=limit)
        directory = _session_dir_by_id(self._dir, session_id, agent_type)
        path = directory / "messages.jsonl"
        if not path.exists():
            return []
        async with aiofiles.open(path) as file:
            lines = await file.readlines()
        messages = [json.loads(line) for line in lines if line.strip()]
        return messages[-limit:]

    # ------------------------------------------------------------------
    # Timeline facade methods (SQLite-backed only)
    # ------------------------------------------------------------------

    async def append_timeline_items(
        self,
        session_id: str,
        agent_type: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Append timeline items atomically. Requires db_factory."""
        if self._timeline is None:
            raise RuntimeError("append_timeline_items requires db_factory")
        return await self._timeline.append_items(session_id, agent_type, items)

    async def get_context_timeline_items(
        self,
        session_id: str,
        agent_type: str = "sebastian",
    ) -> list[dict[str, Any]]:
        """Return non-archived items for LLM context window. Requires db_factory."""
        if self._timeline is None:
            raise RuntimeError("get_context_timeline_items requires db_factory")
        return await self._timeline.get_context_items(session_id, agent_type)

    async def get_timeline_items(
        self,
        session_id: str,
        agent_type: str = "sebastian",
        include_archived: bool = True,
    ) -> list[dict[str, Any]]:
        """Return all timeline items. Requires db_factory."""
        if self._timeline is None:
            raise RuntimeError("get_timeline_items requires db_factory")
        return await self._timeline.get_items(session_id, agent_type, include_archived=include_archived)

    async def get_recent_timeline_items(
        self,
        session_id: str,
        agent_type: str = "sebastian",
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return most recent non-archived timeline items in ascending seq order. Requires db_factory."""
        if self._timeline is None:
            raise RuntimeError("get_recent_timeline_items requires db_factory")
        return await self._timeline.get_recent_items(session_id, agent_type, limit=limit)

    async def get_messages_since(
        self,
        session_id: str,
        agent_type: str = "sebastian",
        after_seq: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return items with seq > after_seq, excluding thinking/raw_block. Requires db_factory."""
        if self._timeline is None:
            raise RuntimeError("get_messages_since requires db_factory")
        items = await self._timeline.get_items_since(session_id, agent_type, after_seq)
        if limit is not None:
            items = items[:limit]
        return items

    async def create_task(
        self,
        task: Task,
        agent_type: str = "sebastian",
    ) -> Task:
        async with self._session_lock(task.session_id, agent_type):
            directory = _session_dir_by_id(self._dir, task.session_id, agent_type)
            tasks_dir = directory / "tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)
            await self._atomic_write_text(
                tasks_dir / f"{task.id}.json",
                task.model_dump_json(),
            )
            await self._refresh_session_counts_locked(task.session_id, agent_type)
        return task

    async def get_task(
        self,
        session_id: str,
        task_id: str,
        agent_type: str = "sebastian",
    ) -> Task | None:
        directory = _session_dir_by_id(
            self._dir,
            session_id,
            agent_type,
        )
        path = directory / "tasks" / f"{task_id}.json"
        if not path.exists():
            return None
        async with aiofiles.open(path) as file:
            raw = await file.read()
        return _task_from_dict(json.loads(raw))

    async def list_tasks(
        self,
        session_id: str,
        agent_type: str = "sebastian",
    ) -> list[Task]:
        directory = _session_dir_by_id(
            self._dir,
            session_id,
            agent_type,
        )
        tasks_dir = directory / "tasks"
        if not tasks_dir.exists():
            return []
        tasks: list[Task] = []
        for path in sorted(tasks_dir.glob("*.json")):
            async with aiofiles.open(path) as file:
                raw = await file.read()
            tasks.append(_task_from_dict(json.loads(raw)))
        return tasks

    async def update_task_status(
        self,
        session_id: str,
        task_id: str,
        status: TaskStatus,
        agent_type: str = "sebastian",
    ) -> None:
        async with self._session_lock(session_id, agent_type):
            task = await self.get_task(session_id, task_id, agent_type)
            if task is None:
                return
            task.status = status
            task.updated_at = datetime.now(UTC)
            if status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                task.completed_at = datetime.now(UTC)
            directory = _session_dir_by_id(
                self._dir,
                session_id,
                agent_type,
            )
            await self._atomic_write_text(
                directory / "tasks" / f"{task_id}.json",
                task.model_dump_json(),
            )
            await self._refresh_session_counts_locked(
                session_id,
                agent_type,
            )

    async def append_checkpoint(
        self,
        session_id: str,
        checkpoint: Checkpoint,
        agent_type: str = "sebastian",
    ) -> None:
        directory = _session_dir_by_id(
            self._dir,
            session_id,
            agent_type,
        )
        path = directory / "tasks" / f"{checkpoint.task_id}.jsonl"
        line = json.dumps(checkpoint.model_dump(mode="json"))
        async with aiofiles.open(path, "a") as file:
            await file.write(line + "\n")

    async def get_checkpoints(
        self,
        session_id: str,
        task_id: str,
        agent_type: str = "sebastian",
    ) -> list[Checkpoint]:
        directory = _session_dir_by_id(
            self._dir,
            session_id,
            agent_type,
        )
        path = directory / "tasks" / f"{task_id}.jsonl"
        if not path.exists():
            return []
        async with aiofiles.open(path) as file:
            lines = await file.readlines()
        return [Checkpoint(**json.loads(line)) for line in lines if line.strip()]

    async def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        async with aiofiles.open(temp_path, "w") as file:
            await file.write(content)
        os.replace(temp_path, path)

    def _session_lock(
        self,
        session_id: str,
        agent_type: str,
    ) -> asyncio.Lock:
        meta_path = (_session_dir_by_id(self._dir, session_id, agent_type) / "meta.json").resolve()
        lock = _SESSION_LOCKS_BY_PATH.get(meta_path)
        if lock is None:
            lock = asyncio.Lock()
            _SESSION_LOCKS_BY_PATH[meta_path] = lock
        return lock

    async def _write_session_meta(self, session: Session) -> None:
        directory = _session_dir_by_id(
            self._dir,
            session.id,
            session.agent_type,
        )
        await self._atomic_write_text(directory / "meta.json", session.model_dump_json())

    async def _refresh_session_counts_locked(
        self,
        session_id: str,
        agent_type: str,
    ) -> None:
        session = await self.get_session(session_id, agent_type)
        if session is None:
            return
        tasks = await self.list_tasks(session_id, agent_type)
        terminal_statuses = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
        session.task_count = len(tasks)
        session.active_task_count = sum(1 for task in tasks if task.status not in terminal_statuses)
        session.updated_at = datetime.now(UTC)
        await self._write_session_meta(session)


def _task_from_dict(data: dict[str, Any]) -> Task:
    return Task(
        id=data["id"],
        session_id=data["session_id"],
        goal=data["goal"],
        status=TaskStatus(data["status"]),
        assigned_agent=data.get("assigned_agent", "sebastian"),
        parent_task_id=data.get("parent_task_id"),
        plan=TaskPlan(**data["plan"]) if data.get("plan") else None,
        resource_budget=ResourceBudget(**data.get("resource_budget", {})),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        completed_at=(
            datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
        ),
    )
