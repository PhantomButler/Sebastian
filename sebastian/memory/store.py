from __future__ import annotations

from sebastian.memory.episodic_memory import EpisodicMemory
from sebastian.memory.working_memory import WorkingMemory


class MemoryStore:
    """Unified access point for all memory layers.
    working: task-scoped in-process dict.
    episodic: persistent conversation history (SQLite)."""

    def __init__(self, episodic: EpisodicMemory) -> None:
        self.working = WorkingMemory()
        self.episodic = episodic
