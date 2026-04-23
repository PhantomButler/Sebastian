from __future__ import annotations

from sebastian.memory.working_memory import WorkingMemory


class MemoryStore:
    """Unified access point for all memory layers.
    working: task-scoped in-process dict.

    DEPRECATED: MemoryStore is no longer used at runtime.  This class will be
    removed in a future release once all callers have migrated to the direct
    SessionStore / SessionTimelineStore APIs.
    """

    def __init__(self) -> None:
        self.working = WorkingMemory()
