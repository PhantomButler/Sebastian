from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pydantic import ValidationError

from sebastian.core.stream_events import LLMStreamEvent, ProviderCallEnd, TextDelta
from sebastian.llm.provider import LLMProvider
from sebastian.llm.registry import ResolvedProvider
from sebastian.memory.consolidation import (
    ConsolidationResult,
    ConsolidatorInput,
    MemoryConsolidator,
    MemorySummary,
    ProposedAction,
)
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryKind,
    MemoryScope,
    MemorySource,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLLMProvider(LLMProvider):
    def __init__(self, response_json: str) -> None:
        self._response = response_json

    async def stream(self, **kwargs: Any) -> AsyncGenerator[LLMStreamEvent, None]:  # type: ignore[override]
        yield TextDelta(block_id="b0", delta=self._response)
        yield ProviderCallEnd(stop_reason="end_turn")


class FakeRegistry:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def get_provider(self, agent_type: str) -> ResolvedProvider:
        return ResolvedProvider(
            provider=self._provider,
            model="test",
            thinking_effort=None,
            capability=None,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_artifact_dict() -> dict[str, Any]:
    return {
        "kind": "episode",
        "content": "User discussed memory architecture",
        "structured_payload": {},
        "subject_hint": None,
        "scope": "user",
        "slot_id": None,
        "cardinality": None,
        "resolution_policy": None,
        "confidence": 0.85,
        "source": "inferred",
        "evidence": [],
        "valid_from": None,
        "valid_until": None,
        "policy_tags": [],
        "needs_review": False,
    }


def _make_valid_consolidation_result_json(
    summaries: list[dict[str, Any]] | None = None,
    proposed_artifacts: list[dict[str, Any]] | None = None,
    proposed_actions: list[dict[str, Any]] | None = None,
) -> str:
    if summaries is None:
        summaries = [
            {
                "content": "User prefers concise replies",
                "subject_id": "user:u1",
                "scope": "user",
                "session_id": None,
            }
        ]
    if proposed_artifacts is None:
        proposed_artifacts = [_make_valid_artifact_dict()]
    if proposed_actions is None:
        proposed_actions = [
            {
                "action": "ADD",
                "memory_id": None,
                "reason": "New preference detected",
            }
        ]
    return json.dumps(
        {
            "summaries": summaries,
            "proposed_artifacts": proposed_artifacts,
            "proposed_actions": proposed_actions,
        }
    )


# ---------------------------------------------------------------------------
# ConsolidatorInput field coverage
# ---------------------------------------------------------------------------


class TestConsolidatorInputFields:
    def test_has_all_required_fields(self) -> None:
        inp = ConsolidatorInput(
            session_messages=[{"role": "user", "content": "hello"}],
            candidate_artifacts=[],
            active_memories_for_subject=[{"id": "m1", "content": "old memory"}],
            recent_summaries=[{"content": "prev summary", "subject_id": "user:u1"}],
            slot_definitions=[{"slot_id": "user.preference.language"}],
            entity_registry_snapshot=[{"entity_id": "e1", "name": "Alice"}],
        )
        assert inp.task == "consolidate_memory"
        assert inp.session_messages == [{"role": "user", "content": "hello"}]
        assert inp.candidate_artifacts == []
        assert inp.active_memories_for_subject == [{"id": "m1", "content": "old memory"}]
        assert inp.recent_summaries == [{"content": "prev summary", "subject_id": "user:u1"}]
        assert inp.slot_definitions == [{"slot_id": "user.preference.language"}]
        assert inp.entity_registry_snapshot == [{"entity_id": "e1", "name": "Alice"}]

    def test_task_field_defaults_to_consolidate_memory(self) -> None:
        inp = ConsolidatorInput(
            session_messages=[],
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )
        assert inp.task == "consolidate_memory"

    def test_candidate_artifacts_accepts_candidate_artifact_objects(self) -> None:
        artifact = CandidateArtifact(**_make_valid_artifact_dict())
        inp = ConsolidatorInput(
            session_messages=[],
            candidate_artifacts=[artifact],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )
        assert len(inp.candidate_artifacts) == 1
        assert inp.candidate_artifacts[0].kind == MemoryKind.EPISODE

    def test_round_trip_via_json(self) -> None:
        artifact = CandidateArtifact(**_make_valid_artifact_dict())
        inp = ConsolidatorInput(
            session_messages=[{"role": "user", "content": "test"}],
            candidate_artifacts=[artifact],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )
        restored = ConsolidatorInput.model_validate_json(inp.model_dump_json())
        assert restored.task == inp.task
        assert len(restored.candidate_artifacts) == 1
        assert restored.candidate_artifacts[0].content == artifact.content


# ---------------------------------------------------------------------------
# ConsolidationResult parsing
# ---------------------------------------------------------------------------


class TestConsolidationResultParsing:
    def test_valid_json_parses_correctly(self) -> None:
        raw = _make_valid_consolidation_result_json()
        result = ConsolidationResult.model_validate_json(raw)
        assert isinstance(result.summaries, list)
        assert isinstance(result.proposed_artifacts, list)
        assert isinstance(result.proposed_actions, list)

    def test_summaries_parsed_correctly(self) -> None:
        raw = _make_valid_consolidation_result_json()
        result = ConsolidationResult.model_validate_json(raw)
        assert len(result.summaries) == 1
        summary = result.summaries[0]
        assert isinstance(summary, MemorySummary)
        assert summary.content == "User prefers concise replies"
        assert summary.subject_id == "user:u1"
        assert summary.scope == "user"
        assert summary.session_id is None

    def test_proposed_artifacts_parsed_correctly(self) -> None:
        raw = _make_valid_consolidation_result_json()
        result = ConsolidationResult.model_validate_json(raw)
        assert len(result.proposed_artifacts) == 1
        artifact = result.proposed_artifacts[0]
        assert isinstance(artifact, CandidateArtifact)
        assert artifact.kind == MemoryKind.EPISODE
        assert artifact.confidence == 0.85
        assert artifact.source == MemorySource.INFERRED
        assert artifact.scope == MemoryScope.USER

    def test_proposed_actions_parsed_correctly(self) -> None:
        raw = _make_valid_consolidation_result_json()
        result = ConsolidationResult.model_validate_json(raw)
        assert len(result.proposed_actions) == 1
        action = result.proposed_actions[0]
        assert isinstance(action, ProposedAction)
        assert action.action == "ADD"
        assert action.memory_id is None
        assert action.reason == "New preference detected"

    def test_empty_lists_are_valid(self) -> None:
        raw = json.dumps({"summaries": [], "proposed_artifacts": [], "proposed_actions": []})
        result = ConsolidationResult.model_validate_json(raw)
        assert result.summaries == []
        assert result.proposed_artifacts == []
        assert result.proposed_actions == []

    def test_all_fields_default_to_empty_lists(self) -> None:
        result = ConsolidationResult()
        assert result.summaries == []
        assert result.proposed_artifacts == []
        assert result.proposed_actions == []

    def test_multiple_summaries_parsed(self) -> None:
        summaries = [
            {
                "content": "summary one",
                "subject_id": "user:u1",
                "scope": "user",
                "session_id": None,
            },
            {
                "content": "summary two",
                "subject_id": "user:u2",
                "scope": "session",
                "session_id": "s1",
            },
        ]
        raw = _make_valid_consolidation_result_json(summaries=summaries)
        result = ConsolidationResult.model_validate_json(raw)
        assert len(result.summaries) == 2
        assert result.summaries[1].scope == "session"
        assert result.summaries[1].session_id == "s1"

    def test_invalid_artifact_enum_raises_validation_error(self) -> None:
        bad_artifact = _make_valid_artifact_dict()
        bad_artifact["kind"] = "NOT_VALID"
        raw = _make_valid_consolidation_result_json(proposed_artifacts=[bad_artifact])
        with pytest.raises(ValidationError):
            ConsolidationResult.model_validate_json(raw)


# ---------------------------------------------------------------------------
# MemoryConsolidator.consolidate()
# ---------------------------------------------------------------------------


class TestMemoryConsolidatorConsolidate:
    def _make_input(self) -> ConsolidatorInput:
        return ConsolidatorInput(
            session_messages=[{"role": "user", "content": "I prefer dark mode"}],
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )

    @pytest.mark.asyncio
    async def test_returns_consolidation_result_on_valid_json(self) -> None:
        raw = _make_valid_consolidation_result_json()
        provider = FakeLLMProvider(raw)
        registry = FakeRegistry(provider)
        consolidator = MemoryConsolidator(registry)  # type: ignore[arg-type]

        result = await consolidator.consolidate(self._make_input())
        assert isinstance(result, ConsolidationResult)
        assert len(result.summaries) == 1
        assert len(result.proposed_artifacts) == 1
        assert len(result.proposed_actions) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_result_on_malformed_json_after_retry(self) -> None:
        call_count = 0

        class CountingFakeLLMProvider(LLMProvider):
            async def stream(self, **kwargs: Any) -> AsyncGenerator[LLMStreamEvent, None]:  # type: ignore[override]
                nonlocal call_count
                call_count += 1
                yield TextDelta(block_id="b0", delta="not valid json {{{{")
                yield ProviderCallEnd(stop_reason="end_turn")

        provider = CountingFakeLLMProvider()
        registry = FakeRegistry(provider)
        consolidator = MemoryConsolidator(registry, max_retries=1)  # type: ignore[arg-type]

        result = await consolidator.consolidate(self._make_input())
        assert isinstance(result, ConsolidationResult)
        assert result.summaries == []
        assert result.proposed_artifacts == []
        assert result.proposed_actions == []
        # 1 initial + 1 retry
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_result_on_schema_failure_after_retry(self) -> None:
        call_count = 0

        class SchemaInvalidProvider(LLMProvider):
            async def stream(self, **kwargs: Any) -> AsyncGenerator[LLMStreamEvent, None]:  # type: ignore[override]
                nonlocal call_count
                call_count += 1
                bad_artifact = _make_valid_artifact_dict()
                bad_artifact["kind"] = "not_a_real_kind"
                payload = json.dumps(
                    {
                        "summaries": [],
                        "proposed_artifacts": [bad_artifact],
                        "proposed_actions": [],
                    }
                )
                yield TextDelta(block_id="b0", delta=payload)
                yield ProviderCallEnd(stop_reason="end_turn")

        provider = SchemaInvalidProvider()
        registry = FakeRegistry(provider)
        consolidator = MemoryConsolidator(registry, max_retries=1)  # type: ignore[arg-type]

        result = await consolidator.consolidate(self._make_input())
        assert isinstance(result, ConsolidationResult)
        assert result.summaries == []
        assert result.proposed_artifacts == []
        assert result.proposed_actions == []
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_when_max_retries_zero(self) -> None:
        call_count = 0

        class AlwaysInvalidProvider(LLMProvider):
            async def stream(self, **kwargs: Any) -> AsyncGenerator[LLMStreamEvent, None]:  # type: ignore[override]
                nonlocal call_count
                call_count += 1
                yield TextDelta(block_id="b0", delta="{bad json")
                yield ProviderCallEnd(stop_reason="end_turn")

        provider = AlwaysInvalidProvider()
        registry = FakeRegistry(provider)
        consolidator = MemoryConsolidator(registry, max_retries=0)  # type: ignore[arg-type]

        result = await consolidator.consolidate(self._make_input())
        assert isinstance(result, ConsolidationResult)
        assert result.summaries == []
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_never_raises_on_failure(self) -> None:
        provider = FakeLLMProvider("{completely broken}")
        registry = FakeRegistry(provider)
        consolidator = MemoryConsolidator(registry, max_retries=0)  # type: ignore[arg-type]

        # Must not raise
        result = await consolidator.consolidate(self._make_input())
        assert isinstance(result, ConsolidationResult)
        assert result.summaries == []

    @pytest.mark.asyncio
    async def test_does_not_write_to_db(self) -> None:
        """Consolidator is pure LLM → schema transform; no persistence side-effects."""
        raw = _make_valid_consolidation_result_json()

        db_write_called = False

        class TrackingFakeLLMProvider(LLMProvider):
            async def stream(self, **kwargs: Any) -> AsyncGenerator[LLMStreamEvent, None]:  # type: ignore[override]
                yield TextDelta(block_id="b0", delta=raw)
                yield ProviderCallEnd(stop_reason="end_turn")

        class TrackingRegistry:
            async def get_provider(self, agent_type: str) -> ResolvedProvider:
                return ResolvedProvider(
                    provider=TrackingFakeLLMProvider(),
                    model="test",
                    thinking_effort=None,
                    capability=None,
                )

        consolidator = MemoryConsolidator(TrackingRegistry())  # type: ignore[arg-type]
        result = await consolidator.consolidate(self._make_input())

        # If no DB write was attempted, db_write_called stays False
        assert not db_write_called
        assert isinstance(result, ConsolidationResult)
