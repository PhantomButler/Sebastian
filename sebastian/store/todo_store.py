# mypy: disable-error-code=import-untyped

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import aiofiles

from sebastian.core.types import TodoItem


class TodoStore:
    """JSON-file storage for per-session todo lists.

    Stores a single `todos.json` under each session directory, next to the
    existing `tasks/` subdirectory. Coverage-write semantics: every write
    replaces the file atomically.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self._dir = sessions_dir

    def _todos_path(self, agent_type: str, session_id: str) -> Path:
        return self._dir / agent_type / session_id / "todos.json"

    async def read(self, agent_type: str, session_id: str) -> list[TodoItem]:
        path = self._todos_path(agent_type, session_id)
        if not path.exists():
            return []
        async with aiofiles.open(path) as f:
            raw = await f.read()
        data = json.loads(raw)
        return [TodoItem(**item) for item in data.get("todos", [])]

    async def write(
        self,
        agent_type: str,
        session_id: str,
        todos: list[TodoItem],
    ) -> None:
        path = self._todos_path(agent_type, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "todos": [item.model_dump(mode="json", by_alias=True) for item in todos],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)

        tmp_path = path.with_suffix(".json.tmp")
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(serialized)
        os.replace(tmp_path, path)
