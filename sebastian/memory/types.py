from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    ADD = "ADD"
    SUPERSEDE = "SUPERSEDE"
    MERGE = "MERGE"
    EXPIRE = "EXPIRE"
    DISCARD = "DISCARD"


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
    scope: MemoryScope
    subject_kind: str
    cardinality: Cardinality
    resolution_policy: ResolutionPolicy
    kind_constraints: list[MemoryKind]
    description: str


class CandidateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MemoryKind
    content: str
    structured_payload: dict[str, Any]
    subject_hint: str | None
    scope: MemoryScope
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
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: MemoryKind
    scope: MemoryScope
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
    model_config = ConfigDict(extra="forbid")

    decision: MemoryDecisionType
    reason: str
    old_memory_ids: list[str]
    new_memory: MemoryArtifact | None
    candidate: CandidateArtifact
    subject_id: str
    scope: MemoryScope
    slot_id: str | None

    @model_validator(mode="after")
    def _check_decision_shape(self) -> ResolveDecision:
        requires_new_memory = (
            MemoryDecisionType.ADD,
            MemoryDecisionType.SUPERSEDE,
            MemoryDecisionType.MERGE,
        )
        requires_old_ids = (MemoryDecisionType.SUPERSEDE, MemoryDecisionType.MERGE)
        if self.decision in requires_new_memory and self.new_memory is None:
            raise ValueError(f"{self.decision} must include new_memory")
        if self.decision == MemoryDecisionType.ADD and self.old_memory_ids:
            raise ValueError("ADD must not have old_memory_ids")
        if self.decision in requires_old_ids and not self.old_memory_ids:
            raise ValueError(f"{self.decision} must include old_memory_ids")
        if self.decision == MemoryDecisionType.DISCARD and self.new_memory is not None:
            raise ValueError("DISCARD must not have new_memory")
        if self.decision == MemoryDecisionType.EXPIRE:
            if not self.old_memory_ids:
                raise ValueError("EXPIRE must include old_memory_ids")
            if self.new_memory is not None:
                raise ValueError("EXPIRE must not have new_memory")
        return self
