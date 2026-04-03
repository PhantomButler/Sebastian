from __future__ import annotations

from typing import Any


class WorkingMemory:
    """In-process task-scoped memory. Holds ephemeral state for the duration
    of a task. All data lives in the process — cleared via clear(task_id)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def set(self, task_id: str, key: str, value: Any) -> None:
        self._store.setdefault(task_id, {})[key] = value

    def get(self, task_id: str, key: str, default: Any = None) -> Any:
        return self._store.get(task_id, {}).get(key, default)

    def get_all(self, task_id: str) -> dict[str, Any]:
        return dict(self._store.get(task_id, {}))

    def clear(self, task_id: str) -> None:
        self._store.pop(task_id, None)
