from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    """Enumeration of task statuses throughout their lifecycle."""

    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolResult(BaseModel):
    """Result of a tool execution."""

    ok: bool
    output: Any = None
    error: str | None = None


class Checkpoint(BaseModel):
    """Checkpoint representing a state snapshot during task execution."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    step: int
    data: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResourceBudget(BaseModel):
    """Resource budget constraints for task execution."""

    max_parallel_tasks: int = 3
    max_llm_calls_per_minute: int = 20
    max_cost_usd: float | None = None


class TaskPlan(BaseModel):
    """Execution plan for a task."""

    subtasks: list[str] = Field(default_factory=list)
    dag: dict[str, list[str]] = Field(default_factory=dict)


class Task(BaseModel):
    """Core task representation in the Sebastian system."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    plan: TaskPlan | None = None
    status: TaskStatus = TaskStatus.CREATED
    assigned_agent: str = "sebastian"
    parent_task_id: str | None = None
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
