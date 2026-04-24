from __future__ import annotations

from sebastian.core.stream_helpers import _DISPLAY_MAX, format_tool_display
from sebastian.core.types import ToolResult


class TestFormatToolDisplay:
    def test_display_field_used_when_present(self) -> None:
        r = ToolResult(ok=True, output={"content": "raw"}, display="clean")
        assert format_tool_display(r) == "clean"

    def test_falls_back_to_str_output_when_display_is_none(self) -> None:
        r = ToolResult(ok=True, output={"k": "v"})
        assert format_tool_display(r) == "{'k': 'v'}"

    def test_empty_output_returns_empty_string(self) -> None:
        r = ToolResult(ok=True, output=None)
        assert format_tool_display(r) == ""

    def test_truncates_overlong_display(self) -> None:
        long_text = "x" * (_DISPLAY_MAX + 50)
        r = ToolResult(ok=True, display=long_text)
        formatted = format_tool_display(r)
        assert len(formatted) == _DISPLAY_MAX + 1  # +1 for ellipsis
        assert formatted.endswith("…")

    def test_truncates_overlong_fallback_output(self) -> None:
        long_output = "y" * (_DISPLAY_MAX + 50)
        r = ToolResult(ok=True, output=long_output)
        formatted = format_tool_display(r)
        assert len(formatted) == _DISPLAY_MAX + 1
        assert formatted.endswith("…")

    def test_exact_max_length_display_not_truncated(self) -> None:
        exact = "z" * _DISPLAY_MAX
        r = ToolResult(ok=True, display=exact)
        formatted = format_tool_display(r)
        assert formatted == exact
        assert not formatted.endswith("…")
