# tests/unit/test_permission_types.py
from __future__ import annotations


def test_permission_tier_values() -> None:
    from sebastian.permissions.types import PermissionTier

    assert PermissionTier.LOW == "low"
    assert PermissionTier.MODEL_DECIDES == "model_decides"
    assert PermissionTier.HIGH_RISK == "high_risk"


def test_tool_call_context_fields() -> None:
    from sebastian.permissions.types import ToolCallContext

    ctx = ToolCallContext(task_goal="test goal", session_id="s1", task_id="t1")
    assert ctx.task_goal == "test goal"
    assert ctx.session_id == "s1"
    assert ctx.task_id == "t1"


def test_tool_call_context_task_id_optional() -> None:
    from sebastian.permissions.types import ToolCallContext

    ctx = ToolCallContext(task_goal="goal", session_id="s1", task_id=None)
    assert ctx.task_id is None


def test_review_decision_fields() -> None:
    from sebastian.permissions.types import ReviewDecision

    d = ReviewDecision(decision="proceed", explanation="")
    assert d.decision == "proceed"
    assert d.explanation == ""

    d2 = ReviewDecision(decision="escalate", explanation="Risky operation detected.")
    assert d2.decision == "escalate"
