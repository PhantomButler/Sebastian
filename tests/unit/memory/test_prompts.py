from __future__ import annotations

from sebastian.memory.prompts import (
    build_consolidator_prompt,
    build_extractor_prompt,
    group_slots_by_kind,
)
from sebastian.memory.writing.slots import _BUILTIN_SLOTS


def test_group_slots_by_kind_buckets_correctly() -> None:
    grouped = group_slots_by_kind(_BUILTIN_SLOTS)
    assert "fact" in grouped
    assert "preference" in grouped
    fact_ids = {s["slot_id"] for s in grouped["fact"]}
    assert "user.profile.name" in fact_ids


def test_extractor_prompt_contains_required_sections() -> None:
    prompt = build_extractor_prompt(group_slots_by_kind(_BUILTIN_SLOTS))
    assert "输出契约" in prompt
    assert "CandidateArtifact 字段" in prompt
    assert "ProposedSlot 字段" in prompt
    assert "Slot 选择规则" in prompt
    assert "Cardinality" in prompt
    assert "示例 1" in prompt
    assert "示例 2" in prompt
    assert "示例 3" in prompt


def test_consolidator_prompt_includes_extractor_sections_plus_summary() -> None:
    prompt = build_consolidator_prompt(group_slots_by_kind(_BUILTIN_SLOTS))
    assert "CandidateArtifact 字段" in prompt
    assert "Consolidator 额外任务" in prompt
    assert "summaries" in prompt
    assert "EXPIRE" in prompt


def test_extractor_prompt_no_pinned_example() -> None:
    """spec §10.2：Extractor LLM 不得提议 pinned，prompt 中不应出现诱导字样。"""
    prompt = build_extractor_prompt(group_slots_by_kind(_BUILTIN_SLOTS))
    assert "pinned" not in prompt.lower(), (
        "Extractor prompt 仍含 'pinned' 字样，违反 artifact-model.md §10.2"
    )


def test_embedded_examples_parse_as_extractor_output() -> None:
    """示例 JSON 必须能被 ExtractorOutput 解析，防止 prompt 示例随代码演进腐坏。"""
    from sebastian.memory.extraction import ExtractorOutput
    from sebastian.memory.prompts import _EXAMPLE_1_JSON, _EXAMPLE_2_JSON, _EXAMPLE_3_JSON

    for example_json in (_EXAMPLE_1_JSON, _EXAMPLE_2_JSON, _EXAMPLE_3_JSON):
        parsed = ExtractorOutput.model_validate_json(example_json)
        assert isinstance(parsed.artifacts, list)
        assert isinstance(parsed.proposed_slots, list)


def test_extractor_prompt_contains_confidence_guide() -> None:
    """置信度评分指南必须出现在 extractor system prompt 中。"""
    from sebastian.memory.prompts import build_extractor_prompt, group_slots_by_kind
    from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY

    prompt = build_extractor_prompt(group_slots_by_kind(DEFAULT_SLOT_REGISTRY.list_all()))

    assert "置信度评分指南" in prompt
    assert "0.9" in prompt
    assert "source=explicit" in prompt
    assert "source=inferred" in prompt
