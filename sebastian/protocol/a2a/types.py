from __future__ import annotations
import uuid
from typing import Any

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    name: str
    content: str
    mime_type: str = "text/plain"


class DelegateTask(BaseModel):
    """Sebastian → Sub-Agent: delegate a task."""
    task_id: str
    goal: str
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    callback_queue_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class EscalateRequest(BaseModel):
    """Sub-Agent → Sebastian: request a decision."""
    task_id: str
    reason: str
    options: list[str] = Field(default_factory=list)
    blocking: bool = True


class TaskResult(BaseModel):
    """Sub-Agent → Sebastian: report completion."""
    task_id: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    new_tools_registered: list[str] = Field(default_factory=list)
    error: str | None = None
