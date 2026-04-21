from __future__ import annotations

import json
import logging
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
from sebastian.memory.extraction import ExtractorOutput
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


class CapturingLLMProvider(LLMProvider):
    """Fake LLM provider that records every stream() call's kwargs for assertion."""

    def __init__(self, response_json: str) -> None:
        self._response = response_json
        self.calls: list[dict[str, Any]] = []

    async def stream(self, **kwargs: Any) -> AsyncGenerator[LLMStreamEvent, None]:  # type: ignore[override]
        self.calls.append(dict(kwargs))
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
    async def test_consolidator_returns_empty_when_stream_raises(self) -> None:
        """Provider raising arbitrary exception during stream → empty result, no crash."""

        class _RaisingProvider(LLMProvider):
            async def stream(  # type: ignore[override]
                self, **kwargs: Any
            ) -> AsyncGenerator[LLMStreamEvent, None]:
                raise TimeoutError("simulated network timeout")
                yield  # pragma: no cover — makes this an async generator

        class _RaisingRegistry:
            async def get_provider(self, binding: str) -> ResolvedProvider:
                return ResolvedProvider(
                    provider=_RaisingProvider(),
                    model="test-model",
                    thinking_effort=None,
                    capability=None,
                )

        consolidator = MemoryConsolidator(_RaisingRegistry(), max_retries=0)  # type: ignore[arg-type]
        result = await consolidator.consolidate(self._make_input())
        assert isinstance(result, ConsolidationResult)
        assert result.summaries == []
        assert result.proposed_artifacts == []
        assert result.proposed_actions == []

    @pytest.mark.asyncio
    async def test_consolidator_prompt_contains_schema_instruction(self) -> None:
        """Consolidator must call LLM with a system prompt referencing the JSON schema
        and a user message whose content is valid JSON carrying the expected input fields.
        """
        raw = _make_valid_consolidation_result_json()
        provider = CapturingLLMProvider(raw)
        registry = FakeRegistry(provider)
        consolidator = MemoryConsolidator(registry)  # type: ignore[arg-type]

        inp = ConsolidatorInput(
            session_messages=[{"role": "user", "content": "I prefer dark mode"}],
            candidate_artifacts=[],
            active_memories_for_subject=[{"id": "m1", "content": "old preference"}],
            recent_summaries=[{"content": "summary one", "subject_id": "user:u1"}],
            slot_definitions=[
                {
                    "slot_id": "user.preference.theme",
                    "scope": "user",
                    "subject_kind": "user",
                    "cardinality": "single",
                    "resolution_policy": "supersede",
                    "kind_constraints": ["preference"],
                    "description": "UI theme",
                }
            ],
            entity_registry_snapshot=[{"entity_id": "e1", "name": "Alice"}],
        )
        result = await consolidator.consolidate(inp)
        assert isinstance(result, ConsolidationResult)

        # Exactly one LLM call was made
        assert len(provider.calls) == 1
        call = provider.calls[0]

        # system prompt must contain the shared consolidator prompt sections
        system: str = call["system"]
        assert "Consolidator 额外任务" in system, (
            f"system prompt missing 'Consolidator 额外任务': {system!r}"
        )
        assert "proposed_slots" in system, f"system prompt missing 'proposed_slots': {system!r}"
        assert "CandidateArtifact 字段" in system, (
            f"system prompt missing 'CandidateArtifact 字段': {system!r}"
        )

        # messages[0] content must be valid JSON carrying the expected ConsolidatorInput fields
        messages: list[dict[str, Any]] = call["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        user_content = messages[0]["content"]
        parsed = json.loads(user_content)  # must not raise
        assert "session_messages" in parsed, (
            f"user message JSON missing 'session_messages': {list(parsed.keys())}"
        )
        assert "slot_definitions" in parsed, (
            f"user message JSON missing 'slot_definitions': {list(parsed.keys())}"
        )
        assert "active_memories_for_subject" in parsed, (
            f"user message JSON missing 'active_memories_for_subject': {list(parsed.keys())}"
        )
        assert "entity_registry_snapshot" in parsed, (
            f"user message JSON missing 'entity_registry_snapshot': {list(parsed.keys())}"
        )

    @pytest.mark.asyncio
    async def test_worker_writes_nothing_when_memory_disabled(self, caplog) -> None:
        """When memory_settings_fn returns False, the worker must not write anything."""
        from sqlalchemy import select, text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from sebastian.memory.consolidation import SessionConsolidationWorker
        from sebastian.store.models import (
            Base,
            EpisodeMemoryRecord,
            ProfileMemoryRecord,
            SessionConsolidationRecord,
        )

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Create FTS virtual table required by EpisodeMemoryStore
                await conn.execute(
                    text(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                        "USING fts5(memory_id UNINDEXED, content_segmented, "
                        "tokenize=unicode61)"
                    )
                )
            factory = async_sessionmaker(engine, expire_on_commit=False)

            class _FakeSessionStore:
                async def get_messages(
                    self, session_id: str, agent_type: str = "sebastian"
                ) -> list[dict[str, Any]]:
                    return [{"role": "user", "content": "should not be read"}]

            class _FailingConsolidator:
                """If the early-return is missing, we'd reach this and raise."""

                async def consolidate(
                    self, consolidator_input: ConsolidatorInput
                ) -> ConsolidationResult:
                    raise AssertionError("consolidator must not run when memory is disabled")

            class _FailingExtractor:
                async def extract(self, extractor_input):  # type: ignore[no-untyped-def]
                    raise AssertionError("extractor must not run when memory is disabled")

                async def extract_with_slot_retry(self, extractor_input, *, attempt_register):  # type: ignore[no-untyped-def]
                    raise AssertionError("extractor must not run when memory is disabled")

            worker = SessionConsolidationWorker(
                db_factory=factory,
                consolidator=_FailingConsolidator(),  # type: ignore[arg-type]
                extractor=_FailingExtractor(),  # type: ignore[arg-type]
                session_store=_FakeSessionStore(),
                memory_settings_fn=lambda: False,
            )

            caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
            await worker.consolidate_session("s1", "default")

            async with factory() as s:
                profiles = list((await s.scalars(select(ProfileMemoryRecord))).all())
                episodes = list((await s.scalars(select(EpisodeMemoryRecord))).all())
                markers = list((await s.scalars(select(SessionConsolidationRecord))).all())
                assert profiles == []
                assert episodes == []
                assert markers == []
            assert "MEMORY_TRACE consolidation.skip" in caplog.text
            assert "reason=memory_disabled" in caplog.text
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_worker_logs_discard_for_non_expire_action(self) -> None:
        """Non-EXPIRE proposed_actions must be logged as DISCARD in the decision log."""
        from sqlalchemy import select, text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from sebastian.memory.consolidation import SessionConsolidationWorker
        from sebastian.store.models import Base, MemoryDecisionLogRecord

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(
                    text(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                        "USING fts5(memory_id UNINDEXED, content_segmented, "
                        "tokenize=unicode61)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                        "USING fts5(memory_id UNINDEXED, content_segmented, "
                        "tokenize=unicode61)"
                    )
                )
            factory = async_sessionmaker(engine, expire_on_commit=False)

            class _FakeSessionStore:
                async def get_messages(
                    self, session_id: str, agent_type: str = "sebastian"
                ) -> list[dict[str, Any]]:
                    return []

            class _FakeExtractor:
                async def extract(self, extractor_input):  # type: ignore[no-untyped-def]
                    return ExtractorOutput(artifacts=[])

                async def extract_with_slot_retry(self, extractor_input, *, attempt_register):  # type: ignore[no-untyped-def]
                    return ExtractorOutput(artifacts=[])

            class _FakeConsolidator:
                last_resolved = None

                async def consolidate(
                    self, consolidator_input: ConsolidatorInput
                ) -> ConsolidationResult:
                    return ConsolidationResult(
                        proposed_actions=[
                            ProposedAction(
                                action="ADD",
                                memory_id=None,
                                reason="test ignored action",
                            )
                        ],
                        summaries=[],
                        proposed_artifacts=[],
                    )

            worker = SessionConsolidationWorker(
                db_factory=factory,
                consolidator=_FakeConsolidator(),  # type: ignore[arg-type]
                extractor=_FakeExtractor(),  # type: ignore[arg-type]
                session_store=_FakeSessionStore(),
                memory_settings_fn=lambda: True,
            )

            await worker.consolidate_session("sess-1", "sebastian")

            async with factory() as s:
                log_rows = list(
                    (
                        await s.scalars(
                            select(MemoryDecisionLogRecord).where(
                                MemoryDecisionLogRecord.decision == "DISCARD"
                            )
                        )
                    ).all()
                )
            assert len(log_rows) >= 1, "Expected at least one DISCARD log entry"
            assert any("ADD" in row.reason for row in log_rows), (
                f"Expected 'ADD' in DISCARD reason, got: {[r.reason for r in log_rows]}"
            )
        finally:
            await engine.dispose()


def test_consolidator_input_task_rejects_invalid_literal() -> None:
    with pytest.raises(Exception):
        ConsolidatorInput(
            task="wrong_task",
            session_messages=[],
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )


def test_memory_summary_rejects_invalid_scope() -> None:
    with pytest.raises(ValidationError):
        MemorySummary(content="x", subject_id="owner", scope="User", session_id=None)  # type: ignore[arg-type]


def test_memory_summary_accepts_valid_scope() -> None:
    s = MemorySummary(content="x", subject_id="owner", scope=MemoryScope.USER, session_id=None)
    assert s.scope == MemoryScope.USER
    s2 = MemorySummary(content="x", subject_id="owner", scope="user", session_id=None)
    assert s2.scope == MemoryScope.USER
