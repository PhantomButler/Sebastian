from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_PLANNING_STARTED = "task.planning_started"
    TASK_PLANNING_FAILED = "task.planning_failed"
    TASK_STARTED = "task.started"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"

    # Agent coordination
    AGENT_DELEGATED = "agent.delegated"
    AGENT_DELEGATED_FAILED = "agent.delegated.failed"
    AGENT_ESCALATED = "agent.escalated"
    AGENT_RESULT_RECEIVED = "agent.result_received"

    # User interaction
    USER_INTERRUPTED = "user.interrupted"
    USER_INTERVENED = "user.intervened"
    USER_APPROVAL_REQUESTED = "user.approval_requested"
    USER_APPROVAL_GRANTED = "user.approval_granted"
    USER_APPROVAL_DENIED = "user.approval_denied"

    # Approval and turn lifecycle
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    TURN_DELTA = "turn.delta"
    TURN_THINKING_DELTA = "turn.thinking_delta"
    TURN_INTERRUPTED = "turn.interrupted"

    # Block-level conversation events
    THINKING_BLOCK_START = "thinking_block.start"
    THINKING_BLOCK_STOP = "thinking_block.stop"
    TEXT_BLOCK_START = "text_block.start"
    TEXT_BLOCK_STOP = "text_block.stop"
    TOOL_BLOCK_START = "tool_block.start"
    TOOL_BLOCK_STOP = "tool_block.stop"

    # Tool lifecycle
    TOOL_REGISTERED = "tool.registered"
    TOOL_RUNNING = "tool.running"
    TOOL_EXECUTED = "tool.executed"
    TOOL_FAILED = "tool.failed"

    # Session lifecycle (three-tier architecture)
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"
    SESSION_CANCELLED = "session.cancelled"
    SESSION_STALLED = "session.stalled"
    SESSION_WAITING = "session.waiting"

    # Conversation
    TURN_RECEIVED = "turn.received"
    TURN_RESPONSE = "turn.response"
    TURN_CANCELLED = "turn.cancelled"

    # Todo lifecycle
    TODO_UPDATED = "todo.updated"


class Event(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
