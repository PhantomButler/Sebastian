from __future__ import annotations


def test_thinking_block_stop_has_thinking_field() -> None:
    from sebastian.core.stream_events import ThinkingBlockStop

    e = ThinkingBlockStop(block_id="b0_0", thinking="I reasoned.")
    assert e.thinking == "I reasoned."


def test_text_block_stop_has_text_field() -> None:
    from sebastian.core.stream_events import TextBlockStop

    e = TextBlockStop(block_id="b0_1", text="Hello.")
    assert e.text == "Hello."


def test_provider_call_end_has_stop_reason() -> None:
    from sebastian.core.stream_events import ProviderCallEnd

    e = ProviderCallEnd(stop_reason="end_turn")
    assert e.stop_reason == "end_turn"


def test_provider_call_end_is_in_llm_stream_event_union() -> None:
    from sebastian.core.stream_events import LLMStreamEvent, ProviderCallEnd

    e: LLMStreamEvent = ProviderCallEnd(stop_reason="tool_use")
    assert isinstance(e, ProviderCallEnd)
