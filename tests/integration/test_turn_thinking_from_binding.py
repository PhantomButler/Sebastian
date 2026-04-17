from __future__ import annotations

"""Task A5: HTTP 入口不再暴露 thinking_effort 字段。

静态断言：SendTurnRequest / SendTurnBody 里不应存在该字段。
行为断言见 test_agent_binding_api.py::test_send_turn_with_extra_thinking_effort_field_is_accepted。
"""


def test_send_turn_request_has_no_thinking_effort_field() -> None:
    """SendTurnRequest（/api/v1/turns）DTO 不应包含 thinking_effort 字段。"""
    from sebastian.gateway.routes.turns import SendTurnRequest

    assert "thinking_effort" not in SendTurnRequest.model_fields


def test_send_turn_body_has_no_thinking_effort_field() -> None:
    """SendTurnBody（/api/v1/sessions/{id}/turns）DTO 不应包含 thinking_effort 字段。"""
    from sebastian.gateway.routes.sessions import SendTurnBody

    assert "thinking_effort" not in SendTurnBody.model_fields
