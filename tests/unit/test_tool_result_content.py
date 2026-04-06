from __future__ import annotations


from sebastian.core.agent_loop import _is_empty_output, _tool_result_content
from sebastian.core.stream_events import ToolResult


# ---------------------------------------------------------------------------
# _is_empty_output
# ---------------------------------------------------------------------------

class TestIsEmptyOutput:
    def test_none_is_empty(self) -> None:
        assert _is_empty_output(None) is True

    def test_empty_string_is_empty(self) -> None:
        assert _is_empty_output("") is True

    def test_empty_list_is_empty(self) -> None:
        assert _is_empty_output([]) is True

    def test_empty_dict_is_empty(self) -> None:
        assert _is_empty_output({}) is True

    def test_nonempty_string_is_not_empty(self) -> None:
        assert _is_empty_output("hello") is False

    def test_nonempty_dict_is_not_empty(self) -> None:
        assert _is_empty_output({"key": "val"}) is False

    def test_nonempty_list_is_not_empty(self) -> None:
        assert _is_empty_output(["item"]) is False

    def test_zero_is_not_empty(self) -> None:
        assert _is_empty_output(0) is False

    def test_false_is_not_empty(self) -> None:
        assert _is_empty_output(False) is False


# ---------------------------------------------------------------------------
# _tool_result_content
# ---------------------------------------------------------------------------

def _make_result(
    *,
    ok: bool = True,
    output: object = None,
    error: str | None = None,
    empty_hint: str | None = None,
) -> ToolResult:
    return ToolResult(
        tool_id="t1",
        name="test_tool",
        ok=ok,
        output=output,
        error=error,
        empty_hint=empty_hint,
    )


class TestToolResultContent:
    def test_error_result(self) -> None:
        r = _make_result(ok=False, error="timeout")
        assert _tool_result_content(r) == "Error: timeout"

    def test_empty_hint_takes_priority_over_nonempty_output(self) -> None:
        r = _make_result(output={"data": 1}, empty_hint="没有找到匹配项")
        assert _tool_result_content(r) == "没有找到匹配项"

    def test_none_output_without_hint(self) -> None:
        r = _make_result(output=None)
        assert _tool_result_content(r) == "<empty output>"

    def test_empty_string_output_without_hint(self) -> None:
        r = _make_result(output="")
        assert _tool_result_content(r) == "<empty output>"

    def test_empty_dict_output_without_hint(self) -> None:
        r = _make_result(output={})
        assert _tool_result_content(r) == "<empty output>"

    def test_none_output_with_hint(self) -> None:
        r = _make_result(output=None, empty_hint="查询结果为空")
        assert _tool_result_content(r) == "查询结果为空"

    def test_nonempty_string_output(self) -> None:
        r = _make_result(output="some text")
        assert _tool_result_content(r) == "some text"

    def test_nonempty_dict_output_uses_str(self) -> None:
        output = {"stdout": "", "returncode": 0}
        r = _make_result(output=output)
        assert _tool_result_content(r) == str(output)
