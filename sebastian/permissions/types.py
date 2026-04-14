# sebastian/permissions/types.py
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class PermissionTier(StrEnum):
    LOW = "low"
    MODEL_DECIDES = "model_decides"
    HIGH_RISK = "high_risk"


@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None
    agent_type: str = ""
    depth: int = 1
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]] | None = field(
        default=None, repr=False
    )


@dataclass
class ReviewDecision:
    decision: Literal["proceed", "escalate"]
    explanation: str
