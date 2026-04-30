from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from sebastian.memory.types import CandidateArtifact, MemoryDecisionType, ProposedSlot, ResolveDecision


class MemoryWriteRequest(BaseModel):
    candidates: list[CandidateArtifact]
    proposed_slots: list[ProposedSlot] = Field(default_factory=list)
    session_id: str
    agent_type: str
    worker_id: str
    model_name: str | None = None
    rule_version: str
    input_source: dict[str, Any]
    proposed_by: Literal["extractor", "consolidator"] = "extractor"


@dataclass
class MemoryWriteResult:
    decisions: list[ResolveDecision] = field(default_factory=list)
    proposed_slots_registered: list[str] = field(default_factory=list)
    proposed_slots_rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def saved_count(self) -> int:
        return sum(
            1
            for decision in self.decisions
            if decision.decision != MemoryDecisionType.DISCARD
            and decision.new_memory is not None
        )

    @property
    def discarded_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.decision == MemoryDecisionType.DISCARD)
