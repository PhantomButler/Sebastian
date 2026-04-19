from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pydantic import ValidationError

from sebastian.core.stream_events import LLMStreamEvent, ProviderCallEnd, TextDelta
from sebastian.llm.provider import LLMProvider
from sebastian.llm.registry import ResolvedProvider
from sebastian.memory.extraction import ExtractorInput, ExtractorOutput, MemoryExtractor
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


def _make_valid_extractor_output_json(artifacts: list[dict[str, Any]] | None = None) -> str:
    if artifacts is None:
        artifacts = [_make_valid_artifact_dict()]
    return json.dumps({"artifacts": artifacts})


# ---------------------------------------------------------------------------
# ExtractorInput serialisation
# ---------------------------------------------------------------------------


class TestExtractorInputSerialisation:
    def test_serialises_with_all_fields(self) -> None:
        inp = ExtractorInput(
            subject_context={"user_id": "u1", "name": "Alice"},
            conversation_window=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
            known_slots=[
                {"slot_id": "user.preference.language", "description": "Language preference"}
            ],
        )
        data = json.loads(inp.model_dump_json())
        assert data["subject_context"]["user_id"] == "u1"
        assert len(data["conversation_window"]) == 2
        assert data["known_slots"][0]["slot_id"] == "user.preference.language"

    def test_serialises_with_empty_collections(self) -> None:
        inp = ExtractorInput(
            subject_context={},
            conversation_window=[],
            known_slots=[],
        )
        data = json.loads(inp.model_dump_json())
        assert data["subject_context"] == {}
        assert data["conversation_window"] == []
        assert data["known_slots"] == []

    def test_round_trip_via_json(self) -> None:
        inp = ExtractorInput(
            subject_context={"key": "value"},
            conversation_window=[{"role": "user", "content": "test"}],
            known_slots=[],
        )
        restored = ExtractorInput.model_validate_json(inp.model_dump_json())
        assert restored.subject_context == inp.subject_context
        assert restored.conversation_window == inp.conversation_window


# ---------------------------------------------------------------------------
# ExtractorOutput parsing
# ---------------------------------------------------------------------------


class TestExtractorOutputParsing:
    def test_valid_json_parses_to_artifacts_list(self) -> None:
        raw = _make_valid_extractor_output_json()
        output = ExtractorOutput.model_validate_json(raw)
        assert isinstance(output.artifacts, list)
        assert len(output.artifacts) == 1
        assert isinstance(output.artifacts[0], CandidateArtifact)

    def test_artifact_fields_are_correct(self) -> None:
        raw = _make_valid_extractor_output_json()
        output = ExtractorOutput.model_validate_json(raw)
        artifact = output.artifacts[0]
        assert artifact.kind == MemoryKind.EPISODE
        assert artifact.content == "User discussed memory architecture"
        assert artifact.confidence == 0.85
        assert artifact.source == MemorySource.INFERRED
        assert artifact.scope == MemoryScope.USER

    def test_multiple_artifacts_parsed(self) -> None:
        artifacts = [_make_valid_artifact_dict(), _make_valid_artifact_dict()]
        artifacts[1]["content"] = "Second artifact"
        artifacts[1]["confidence"] = 0.5
        raw = json.dumps({"artifacts": artifacts})
        output = ExtractorOutput.model_validate_json(raw)
        assert len(output.artifacts) == 2
        assert output.artifacts[1].content == "Second artifact"

    def test_empty_artifacts_list_is_valid(self) -> None:
        raw = json.dumps({"artifacts": []})
        output = ExtractorOutput.model_validate_json(raw)
        assert output.artifacts == []

    def test_invalid_kind_enum_raises_validation_error(self) -> None:
        bad = _make_valid_artifact_dict()
        bad["kind"] = "INVALID_KIND_VALUE"
        raw = json.dumps({"artifacts": [bad]})
        with pytest.raises(ValidationError):
            ExtractorOutput.model_validate_json(raw)

    def test_invalid_scope_enum_raises_validation_error(self) -> None:
        bad = _make_valid_artifact_dict()
        bad["scope"] = "INVALID_SCOPE"
        raw = json.dumps({"artifacts": [bad]})
        with pytest.raises(ValidationError):
            ExtractorOutput.model_validate_json(raw)

    def test_confidence_out_of_range_raises_validation_error(self) -> None:
        bad = _make_valid_artifact_dict()
        bad["confidence"] = 1.5  # > 1.0
        raw = json.dumps({"artifacts": [bad]})
        with pytest.raises(ValidationError):
            ExtractorOutput.model_validate_json(raw)


# ---------------------------------------------------------------------------
# MemoryExtractor.extract()
# ---------------------------------------------------------------------------


class TestMemoryExtractorExtract:
    @pytest.mark.asyncio
    async def test_returns_artifacts_on_valid_json(self) -> None:
        raw = _make_valid_extractor_output_json()
        provider = FakeLLMProvider(raw)
        registry = FakeRegistry(provider)
        extractor = MemoryExtractor(registry)  # type: ignore[arg-type]

        inp = ExtractorInput(
            subject_context={"user_id": "u1"},
            conversation_window=[{"role": "user", "content": "I prefer concise replies"}],
            known_slots=[],
        )
        result = await extractor.extract(inp)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], CandidateArtifact)

    @pytest.mark.asyncio
    async def test_malformed_json_retries_once_then_returns_empty(self) -> None:
        call_count = 0

        class CountingFakeLLMProvider(LLMProvider):
            async def stream(self, **kwargs: Any) -> AsyncGenerator[LLMStreamEvent, None]:  # type: ignore[override]
                nonlocal call_count
                call_count += 1
                yield TextDelta(block_id="b0", delta="not valid json {{{{")
                yield ProviderCallEnd(stop_reason="end_turn")

        provider = CountingFakeLLMProvider()
        registry = FakeRegistry(provider)
        extractor = MemoryExtractor(registry, max_retries=1)  # type: ignore[arg-type]

        inp = ExtractorInput(
            subject_context={},
            conversation_window=[],
            known_slots=[],
        )
        result = await extractor.extract(inp)
        assert result == []
        # 1 initial attempt + 1 retry = 2 calls
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_schema_invalid_json_retries_once_then_returns_empty(self) -> None:
        """Syntactically valid JSON but fails ExtractorOutput schema → retry once → []."""
        call_count = 0

        class SchemaInvalidProvider(LLMProvider):
            async def stream(self, **kwargs: Any) -> AsyncGenerator[LLMStreamEvent, None]:  # type: ignore[override]
                nonlocal call_count
                call_count += 1
                # "artifacts" contains an object with invalid enum
                bad = _make_valid_artifact_dict()
                bad["kind"] = "not_a_real_kind"
                yield TextDelta(block_id="b0", delta=json.dumps({"artifacts": [bad]}))
                yield ProviderCallEnd(stop_reason="end_turn")

        provider = SchemaInvalidProvider()
        registry = FakeRegistry(provider)
        extractor = MemoryExtractor(registry, max_retries=1)  # type: ignore[arg-type]

        inp = ExtractorInput(
            subject_context={},
            conversation_window=[],
            known_slots=[],
        )
        result = await extractor.extract(inp)
        assert result == []
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
        extractor = MemoryExtractor(registry, max_retries=0)  # type: ignore[arg-type]

        inp = ExtractorInput(subject_context={}, conversation_window=[], known_slots=[])
        result = await extractor.extract(inp)
        assert result == []
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_returns_empty_list_not_raises_on_failure(self) -> None:
        """Extractor must never raise — always returns [] on any parse failure."""
        provider = FakeLLMProvider("{completely broken}")
        registry = FakeRegistry(provider)
        extractor = MemoryExtractor(registry, max_retries=0)  # type: ignore[arg-type]

        inp = ExtractorInput(subject_context={}, conversation_window=[], known_slots=[])
        # Should not raise
        result = await extractor.extract(inp)
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_artifacts_returned(self) -> None:
        artifacts = [_make_valid_artifact_dict(), _make_valid_artifact_dict()]
        artifacts[1]["content"] = "Another memory"
        artifacts[1]["kind"] = "fact"
        artifacts[1]["slot_id"] = "user.current_project_focus"
        raw = json.dumps({"artifacts": artifacts})
        provider = FakeLLMProvider(raw)
        registry = FakeRegistry(provider)
        extractor = MemoryExtractor(registry)  # type: ignore[arg-type]

        inp = ExtractorInput(subject_context={}, conversation_window=[], known_slots=[])
        result = await extractor.extract(inp)
        assert len(result) == 2
        assert result[1].content == "Another memory"
        assert result[1].kind == MemoryKind.FACT
