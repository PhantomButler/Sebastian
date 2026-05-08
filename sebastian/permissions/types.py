# sebastian/permissions/types.py
from __future__ import annotations

from collections.abc import Awaitable, Callable, Set
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class PermissionTier(StrEnum):
    LOW = "low"
    MODEL_DECIDES = "model_decides"
    HIGH_RISK = "high_risk"


class AllToolsSentinel:
    """Explicit marker for unrestricted capability tool access."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "ALL_TOOLS"


ALL_TOOLS = AllToolsSentinel()
ToolAllowlist = Set[str] | AllToolsSentinel | None


@dataclass(frozen=True)
class ToolReviewPreflight:
    ok: bool
    review_input: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None
    agent_type: str = ""
    depth: int = 1
    allowed_tools: ToolAllowlist = None
    supports_image_input: bool = False
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]] | None = field(
        default=None, repr=False
    )


@dataclass
class ReviewDecision:
    decision: Literal["proceed", "escalate"]
    explanation: str
