from __future__ import annotations

import pytest


def test_todo_store_requires_db_factory() -> None:
    """TodoStore 不再接受 sessions_dir 参数，必须传 db_factory。"""
    from pathlib import Path

    from sebastian.store.todo_store import TodoStore

    with pytest.raises(TypeError):
        TodoStore(sessions_dir=Path("/tmp/foo"))  # type: ignore[call-arg]
