from __future__ import annotations

from sebastian.memory.contracts.retrieval import (
    ExplicitMemorySearchRequest,
    ExplicitMemorySearchResult,
    PromptMemoryRequest,
    PromptMemoryResult,
)
from sebastian.memory.contracts.writing import MemoryWriteRequest, MemoryWriteResult


def test_prompt_memory_request_defaults_dedupe_sets() -> None:
    request = PromptMemoryRequest(
        session_id="sess-1",
        agent_type="sebastian",
        user_message="我喜欢什么",
        subject_id="user:owner",
    )
    assert request.resident_record_ids == set()
    assert request.resident_dedupe_keys == set()
    assert request.resident_canonical_bullets == set()


def test_prompt_memory_result_instantiation() -> None:
    result = PromptMemoryResult(section="## 记忆\n- 喜欢咖啡")
    assert result.section == "## 记忆\n- 喜欢咖啡"


def test_explicit_memory_search_request_default_limit() -> None:
    request = ExplicitMemorySearchRequest(
        query="咖啡",
        session_id="sess-1",
        agent_type="sebastian",
        subject_id="user:owner",
    )
    assert request.limit == 5


def test_explicit_memory_search_result_instantiation() -> None:
    result = ExplicitMemorySearchResult(items=[{"id": "m1", "content": "喜欢咖啡"}])
    assert len(result.items) == 1


def test_memory_write_result_defaults() -> None:
    result = MemoryWriteResult()
    assert result.decisions == []
    assert result.proposed_slots_registered == []
    assert result.proposed_slots_rejected == []
    assert result.saved_count == 0
    assert result.discarded_count == 0
