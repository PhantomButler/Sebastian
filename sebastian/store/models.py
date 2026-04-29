from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    agent_type: Mapped[str] = mapped_column(String(100), default="sebastian", index=True)
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
    session_id: Mapped[str] = mapped_column(String, default="", index=True)
    agent_type: Mapped[str] = mapped_column(String(100), default="sebastian", index=True)
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


class LLMAccountRecord(Base):
    __tablename__ = "llm_accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    catalog_provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(String(600), nullable=False)
    base_url_override: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class LLMCustomModelRecord(Base):
    __tablename__ = "llm_custom_models"
    __table_args__ = (
        UniqueConstraint("account_id", "model_id", name="uq_llm_custom_models_account_model"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("llm_accounts.id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    context_window_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    thinking_capability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    thinking_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supports_image_input: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_text_file_input: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
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
    proposed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_in_session: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ProfileMemoryRecord(Base):
    __tablename__ = "profile_memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    slot_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    cardinality: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(String)
    content_segmented: Mapped[str] = mapped_column(String, default="")
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
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    source: Mapped[str] = mapped_column(String, default="system_derived")
    status: Mapped[str] = mapped_column(String, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    policy_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
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
    input_source: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class SessionConsolidationRecord(Base):
    __tablename__ = "session_consolidations"

    agent_type: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    consolidated_at: Mapped[datetime] = mapped_column(DateTime)
    worker_version: Mapped[str] = mapped_column(String, default="phase_c_v1")
    last_consolidated_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_item_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_consolidated_source_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consolidation_mode: Mapped[str] = mapped_column(String(50), default="full_session")


class AppSettingsRecord(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class SessionRecord(Base):
    __tablename__ = "sessions"

    agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, default="")
    goal: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    parent_session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, default=lambda: datetime.now(UTC)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    active_task_count: Mapped[int] = mapped_column(Integer, default=0)
    next_item_seq: Mapped[int] = mapped_column(Integer, default=1)
    next_exchange_index: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))

    __table_args__ = (
        Index("ix_sessions_agent_type", "agent_type"),
        Index("ix_sessions_agent_parent_status", "agent_type", "parent_session_id", "status"),
        Index("ix_sessions_last_activity", "last_activity_at"),
    )


class SessionItemRecord(Base):
    __tablename__ = "session_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    assistant_turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_call_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange_id: Mapped[str | None] = mapped_column(String, nullable=True)
    exchange_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_type", "session_id", "seq", name="uq_session_items_seq"),
        Index("ix_session_items_ctx", "agent_type", "session_id", "archived", "seq"),
        Index(
            "ix_session_items_eff",
            "agent_type",
            "session_id",
            "archived",
            "effective_seq",
            "seq",
        ),
        Index("ix_session_items_created", "agent_type", "session_id", "created_at"),
        Index("ix_session_items_kind", "agent_type", "session_id", "kind", "seq"),
        Index(
            "ix_session_items_turn",
            "agent_type",
            "session_id",
            "assistant_turn_id",
            "provider_call_index",
            "block_index",
        ),
        Index(
            "ix_session_items_exchange",
            "agent_type",
            "session_id",
            "exchange_index",
            "seq",
        ),
    )


class SessionTodoRecord(Base):
    __tablename__ = "session_todos"

    agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    todos: Mapped[list[Any]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_type", "session_id"],
            ["sessions.agent_type", "sessions.id"],
            ondelete="CASCADE",
        ),
    )


class AttachmentRecord(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    original_filename: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    blob_path: Mapped[str] = mapped_column(String)
    text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    attached_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    orphaned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_attachments_status_created", "status", "created_at"),
        Index("ix_attachments_session", "agent_type", "session_id"),
        Index("ix_attachments_sha256", "sha256"),
    )


class ScheduledJobRunRecord(Base):
    __tablename__ = "scheduled_job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_scheduled_job_runs_job_status_started", "job_id", "status", "started_at"),
    )
