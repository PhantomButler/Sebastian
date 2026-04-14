# sebastian/core/protocols.py
from __future__ import annotations

from typing import Any, Protocol


class ApprovalManagerProtocol(Protocol):
    """Protocol satisfied by ConversationManager without explicit inheritance."""

    async def request_approval(
        self,
        approval_id: str,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        session_id: str = "",
        agent_type: str = "",
    ) -> bool: ...


class ToolSpecProvider(Protocol):
    """Protocol for any object that can provide tool specs. Satisfied by both
    CapabilityRegistry (tests/legacy) and PolicyGate (production)."""

    def get_all_tool_specs(self) -> list[dict[str, Any]]: ...
