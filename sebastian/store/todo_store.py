from __future__ import annotations

from typing import TYPE_CHECKING

from sebastian.core.types import TodoItem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TodoStore:
    """per-session todo 存储（SQLite-backed）。"""

    def __init__(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        from sebastian.store.session_todos import SessionTodoStore

        self._db_todo = SessionTodoStore(db_factory)

    async def read_updated_at(self, agent_type: str, session_id: str) -> str | None:
        """返回该 session todos 的最后写入时间（ISO 8601 字符串），无记录时返回 None。"""
        dt = await self._db_todo.read_updated_at(agent_type, session_id)
        return dt.isoformat() if dt is not None else None

    async def read(self, agent_type: str, session_id: str) -> list[TodoItem]:
        return await self._db_todo.read(agent_type, session_id)

    async def write(
        self,
        agent_type: str,
        session_id: str,
        todos: list[TodoItem],
    ) -> None:
        await self._db_todo.write(agent_type, session_id, todos)
