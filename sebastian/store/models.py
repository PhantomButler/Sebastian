from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from sebastian.store.database import Base  # noqa: F401


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String(100), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True, default="")
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    goal: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(20), index=True)
    assigned_agent: Mapped[str] = mapped_column(String(100))
    parent_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resource_budget: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CheckpointRecord(Base):
    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    step: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class LLMProviderRecord(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key_enc: Mapped[str] = mapped_column(String(600), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    thinking_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    thinking_capability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("llm_providers.id", ondelete="SET NULL"),
        nullable=True,
    )
    thinking_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class MemorySlotRecord(Base):
    __tablename__ = "memory_slots"

    slot_id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String)
    subject_kind: Mapped[str] = mapped_column(String)
    cardinality: Mapped[str] = mapped_column(String)
    resolution_policy: Mapped[str] = mapped_column(String)
    kind_constraints: Mapped[list[str]] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(String)
    is_builtin: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ProfileMemoryRecord(Base):
    __tablename__ = "profile_memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    slot_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    policy_tags: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)


class EpisodeMemoryRecord(Base):
    __tablename__ = "episode_memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    content_segmented: Mapped[str] = mapped_column(String)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    links: Mapped[list[str]] = mapped_column(JSON)
    policy_tags: Mapped[list[str]] = mapped_column(JSON)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)


class EntityRecord(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String, index=True)
    entity_type: Mapped[str] = mapped_column(String, index=True)
    aliases: Mapped[list[str]] = mapped_column(JSON)
    entity_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, name="metadata")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class RelationCandidateRecord(Base):
    __tablename__ = "relation_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    predicate: Mapped[str] = mapped_column(String, index=True)
    source_entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(String)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class MemoryDecisionLogRecord(Base):
    __tablename__ = "memory_decision_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision: Mapped[str] = mapped_column(String, index=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    slot_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    candidate: Mapped[dict[str, Any]] = mapped_column(JSON)
    conflicts: Mapped[list[str]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String)
    old_memory_ids: Mapped[list[str]] = mapped_column(JSON)
    new_memory_id: Mapped[str | None] = mapped_column(String, nullable=True)
    worker: Mapped[str] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    rule_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class SessionConsolidationRecord(Base):
    __tablename__ = "session_consolidations"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_type: Mapped[str] = mapped_column(String, primary_key=True)
    consolidated_at: Mapped[datetime] = mapped_column(DateTime)
    worker_version: Mapped[str] = mapped_column(String, default="phase_c_v1")
