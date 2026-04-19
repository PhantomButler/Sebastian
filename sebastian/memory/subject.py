from __future__ import annotations

from sebastian.memory.types import MemoryScope

OWNER_SUBJECT = "owner"


async def resolve_subject(
    scope: MemoryScope,
    *,
    session_id: str,
    agent_type: str,
) -> str:
    """Resolve the subject_id for a given memory scope.

    Phase B: only ``owner`` exists for USER/PROJECT scopes. AGENT/SESSION
    scopes encode agent_type / session_id directly. Phase 5 will extend
    USER/PROJECT to real multi-user identity.
    """
    if scope == MemoryScope.AGENT:
        return f"agent:{agent_type}"
    if scope == MemoryScope.SESSION:
        return f"session:{session_id}"
    return OWNER_SUBJECT
