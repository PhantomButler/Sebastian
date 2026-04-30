from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PromptMemoryRequest(BaseModel):
    session_id: str
    agent_type: str
    user_message: str
    subject_id: str
    active_project_or_agent_context: dict[str, Any] | None = None
    resident_record_ids: set[str] = Field(default_factory=set)
    resident_dedupe_keys: set[str] = Field(default_factory=set)
    resident_canonical_bullets: set[str] = Field(default_factory=set)


class PromptMemoryResult(BaseModel):
    section: str


class ExplicitMemorySearchRequest(BaseModel):
    query: str
    session_id: str
    agent_type: str
    subject_id: str
    limit: int = 5


class ExplicitMemorySearchResult(BaseModel):
    items: list[dict[str, Any]]
