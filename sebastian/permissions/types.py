# sebastian/permissions/types.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class PermissionTier(StrEnum):
    LOW = "low"
    MODEL_DECIDES = "model_decides"
    HIGH_RISK = "high_risk"


@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None


@dataclass
class ReviewDecision:
    decision: Literal["proceed", "escalate"]
    explanation: str
