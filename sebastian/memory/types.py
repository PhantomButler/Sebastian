from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    EPISODE = "episode"
    SUMMARY = "summary"
    ENTITY = "entity"
    RELATION = "relation"


class MemoryScope(StrEnum):
    USER = "user"
    SESSION = "session"
    PROJECT = "project"
    AGENT = "agent"


class MemorySource(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    OBSERVED = "observed"
    IMPORTED = "imported"
    SYSTEM_DERIVED = "system_derived"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DELETED = "deleted"


class MemoryDecisionType(StrEnum):
    ADD = "add"
    SUPERSEDE = "supersede"
    MERGE = "merge"
    EXPIRE = "expire"
    DISCARD = "discard"


class Cardinality(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


class ResolutionPolicy(StrEnum):
    SUPERSEDE = "supersede"
    MERGE = "merge"
    APPEND_ONLY = "append_only"
    TIME_BOUND = "time_bound"


class SlotDefinition(BaseModel):
    slot_id: str
    scope: str
    subject_kind: str
    cardinality: Cardinality
    resolution_policy: ResolutionPolicy
    kind_constraints: list[MemoryKind]
    description: str


class CandidateArtifact(BaseModel):
    kind: MemoryKind
    content: str
    structured_payload: dict[str, Any]
    subject_hint: str | None
    scope: str
    slot_id: str | None
    cardinality: Cardinality | None
    resolution_policy: ResolutionPolicy | None
    confidence: float = Field(ge=0.0, le=1.0)
    source: MemorySource
    evidence: list[dict[str, Any]]
    valid_from: datetime | None
    valid_until: datetime | None
    policy_tags: list[str]
    needs_review: bool


class MemoryArtifact(BaseModel):
    id: str
    kind: MemoryKind
    scope: str
    subject_id: str
    slot_id: str | None
    cardinality: Cardinality | None
    resolution_policy: ResolutionPolicy | None
    content: str
    structured_payload: dict[str, Any]
    source: MemorySource
    confidence: float = Field(ge=0.0, le=1.0)
    status: MemoryStatus
    valid_from: datetime | None
    valid_until: datetime | None
    recorded_at: datetime
    last_accessed_at: datetime | None
    access_count: int
    provenance: dict[str, Any]
    links: list[str]
    embedding_ref: str | None
    dedupe_key: str | None
    policy_tags: list[str]


class ResolveDecision(BaseModel):
    decision: MemoryDecisionType
    reason: str
    old_memory_ids: list[str]
    new_memory: MemoryArtifact | None
    candidate: CandidateArtifact
    subject_id: str
    scope: str
    slot_id: str | None
