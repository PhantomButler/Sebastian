from __future__ import annotations

from types import SimpleNamespace

from sebastian.memory.retrieval import (
    MIN_CONFIDENCE_AUTO_INJECT,
    MIN_CONFIDENCE_HARD,
    MemorySectionAssembler,
    RetrievalContext,
    RetrievalPlan,
    _keep_record,
)


def _rec(confidence: float) -> SimpleNamespace:
    return SimpleNamespace(
        content="x",
        kind="fact",
        confidence=confidence,
        policy_tags=[],
        status="active",
        valid_until=None,
        valid_from=None,
        subject_id="user:eric",
    )


def _ctx(purpose: str) -> RetrievalContext:
    return RetrievalContext(
        subject_id="user:eric",
        session_id="s1",
        agent_type="sebastian",
        user_message="dummy",
        access_purpose=purpose,
    )


def test_min_confidence_hard_is_0_3() -> None:
    assert MIN_CONFIDENCE_HARD == 0.3


def test_min_confidence_auto_inject_is_0_5() -> None:
    assert MIN_CONFIDENCE_AUTO_INJECT == 0.5


def test_hard_gate_drops_below_0_3_context_injection() -> None:
    assert _keep_record(_rec(0.25), context=_ctx("context_injection")) is False


def test_hard_gate_drops_below_0_3_tool_search() -> None:
    assert _keep_record(_rec(0.25), context=_ctx("tool_search")) is False


def test_hard_gate_passes_at_0_3() -> None:
    assert _keep_record(_rec(0.3), context=_ctx("tool_search")) is True


def test_auto_inject_drops_mid_band() -> None:
    plan = RetrievalPlan()
    out = MemorySectionAssembler().assemble(
        profile_records=[_rec(0.35)],
        context_records=[],
        episode_records=[],
        relation_records=[],
        plan=plan,
        context=_ctx("context_injection"),
    )
    assert out == ""


def test_tool_search_keeps_mid_band() -> None:
    plan = RetrievalPlan()
    out = MemorySectionAssembler().assemble(
        profile_records=[_rec(0.35)],
        context_records=[],
        episode_records=[],
        relation_records=[],
        plan=plan,
        context=_ctx("tool_search"),
    )
    assert "x" in out


def test_auto_inject_keeps_above_gate() -> None:
    plan = RetrievalPlan()
    out = MemorySectionAssembler().assemble(
        profile_records=[_rec(0.55)],
        context_records=[],
        episode_records=[],
        relation_records=[],
        plan=plan,
        context=_ctx("context_injection"),
    )
    assert "x" in out


def test_min_confidence_constant_fully_removed() -> None:
    """旧常量必须彻底删除，避免调用方误用。"""
    import sebastian.memory.retrieval as ret_mod

    assert not hasattr(ret_mod, "MIN_CONFIDENCE")
