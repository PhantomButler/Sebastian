from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_base_agent_persists_user_turn_before_inference_failure(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(
            id="failure-path",
            agent_type="sebastian",
            title="Failure path",
        )
    )

    agent = TestAgent(MagicMock(), store)

    async def failing_stream(*args, **kwargs):
        if False:
            yield None
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        agent._loop.stream = failing_stream  # type: ignore[attr-defined]
        await agent.run("Hello", "failure-path")

    messages = await store.get_messages("failure-path", "sebastian")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"


@pytest.mark.asyncio
async def test_base_agent_writes_messages_to_overridden_agent_context(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(
            id="subagent-session",
            agent_type="stock",
            title="Stock session",
        )
    )

    agent = TestAgent(MagicMock(), store)

    async def successful_stream(*args, **kwargs):
        from sebastian.core.stream_events import TurnDone

        yield TurnDone(full_text="done")

    agent._loop.stream = successful_stream  # type: ignore[attr-defined]
    response = await agent.run(
        "Check this thesis",
        "subagent-session",
        agent_name="stock",
    )

    assert response == "done"
    stock_messages = await store.get_messages(
        "subagent-session",
        agent_type="stock",
    )
    assert [message["role"] for message in stock_messages] == ["user", "assistant"]
    assert stock_messages[0]["content"] == "Check this thesis"
    sebastian_messages = await store.get_messages(
        "subagent-session",
        agent_type="sebastian",
    )
    assert sebastian_messages == []


@pytest.mark.asyncio
async def test_run_streaming_publishes_turn_events(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TurnDone
    from sebastian.core.types import Session
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(
            id="stream-session",
            agent_type="sebastian",
            title="Stream session",
        )
    )

    bus = EventBus()
    collected_events = []

    async def capture(event) -> None:
        collected_events.append(event)

    bus.subscribe(capture)

    agent = TestAgent(MagicMock(), store, bus)

    async def fake_stream(*args, **kwargs):
        yield TurnDone(full_text="response text")

    agent._loop.stream = fake_stream  # type: ignore[attr-defined]

    result = await agent.run_streaming("hello", "stream-session")

    assert result == "response text"
    types = [event.type for event in collected_events]
    assert EventType.TURN_RECEIVED in types
    assert EventType.TURN_RESPONSE in types

    received = next(event for event in collected_events if event.type == EventType.TURN_RECEIVED)
    assert received.data["session_id"] == "stream-session"
    assert received.data["agent_type"] == "sebastian"

    response = next(event for event in collected_events if event.type == EventType.TURN_RESPONSE)
    assert response.data["session_id"] == "stream-session"
    assert response.data["content"] == "response text"
    assert response.data["interrupted"] is False

    messages = await store.get_messages("stream-session", "sebastian")
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "response text"


@pytest.mark.asyncio
async def test_run_streaming_interrupt_publishes_interrupted(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(
            id="interrupt-session",
            agent_type="sebastian",
            title="Interrupt session",
        )
    )

    bus = EventBus()
    collected_events = []

    async def capture(event) -> None:
        collected_events.append(event)

    bus.subscribe(capture)

    agent = TestAgent(MagicMock(), store, bus)

    async def slow_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b0_0")
        yield TextDelta(block_id="b0_0", delta="partial")
        await asyncio.sleep(10)

    agent._loop.stream = slow_stream  # type: ignore[attr-defined]

    stream_task = asyncio.create_task(agent.run_streaming("hello", "interrupt-session"))
    await asyncio.sleep(0.05)
    stream_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stream_task

    types = [event.type for event in collected_events]
    assert EventType.TURN_INTERRUPTED in types
    interrupted = next(
        event for event in collected_events if event.type == EventType.TURN_INTERRUPTED
    )
    assert interrupted.data["session_id"] == "interrupt-session"
    assert interrupted.data["partial_content"] == "partial"

    messages = await store.get_messages("interrupt-session", "sebastian")
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "partial"


def test_base_agent_has_no_execute_delegated_task():
    """execute_delegated_task should be removed."""
    from sebastian.core.base_agent import BaseAgent

    assert not hasattr(BaseAgent, "execute_delegated_task")


def test_build_system_prompt_contains_guidelines_section() -> None:
    """build_system_prompt() 包含 guidelines section，含 workspace_dir 路径。"""
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    from sebastian.core.base_agent import BaseAgent

    class TestAgent(BaseAgent):
        name = "test"

    fake_workspace = Path("/fake/workspace")

    gate = MagicMock()
    gate.get_tool_specs.return_value = []
    gate.get_skill_specs.return_value = []

    with patch("sebastian.core.base_agent.settings") as mock_settings:
        mock_settings.workspace_dir = fake_workspace
        mock_settings.sebastian_owner_name = "Eric"
        mock_settings.sebastian_model = "claude-opus-4-6"
        agent = TestAgent(gate, MagicMock())
        prompt = agent.system_prompt

    assert "Operation Guidelines" in prompt
    assert str(fake_workspace) in prompt
    assert "Read" in prompt
    assert "Write" in prompt
    assert "Glob" in prompt
    assert "Grep" in prompt


def test_guidelines_section_appears_before_tools_section() -> None:
    """guidelines section 必须在 tools section 之前出现。"""
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    from sebastian.core.base_agent import BaseAgent

    class TestAgent(BaseAgent):
        name = "test"

    gate = MagicMock()
    gate.get_tool_specs.return_value = [{"name": "Read", "description": "Read a file"}]
    gate.get_skill_specs.return_value = []

    with patch("sebastian.core.base_agent.settings") as mock_settings:
        mock_settings.workspace_dir = Path("/fake/ws")
        mock_settings.sebastian_owner_name = "Eric"
        mock_settings.sebastian_model = "claude-opus-4-6"
        agent = TestAgent(gate, MagicMock())
        prompt = agent.system_prompt

    guidelines_pos = prompt.index("Operation Guidelines")
    tools_pos = prompt.index("Available Tools")
    assert guidelines_pos < tools_pos


# ──────────────────────────────────────────────────────────────────────────────
# cancel_session tests
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_session_returns_false_when_no_active_stream(tmp_path: Path) -> None:
    """Cancelling an idle session returns False — no stream to cancel."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="idle-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    result = await agent.cancel_session("idle-session")

    assert result is False


@pytest.mark.asyncio
async def test_cancel_session_cancels_active_stream(tmp_path: Path) -> None:
    """cancel_session() cancels a long-running stream and clears _active_streams."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="running-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def slow_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="hello")
        stream_started.set()
        await asyncio.sleep(10)  # runs until cancelled

    agent._loop.stream = slow_stream  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hi", "running-session"))
    await stream_started.wait()

    result = await agent.cancel_session("running-session")

    assert result is True
    # After cancellation the stream task is no longer tracked
    assert "running-session" not in agent._active_streams

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task


@pytest.mark.asyncio
async def test_cancel_session_flushes_partial_text_to_episodic(tmp_path: Path) -> None:
    """Partial text is saved to episodic memory with [用户中断] suffix on cancel."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="partial-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def partial_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="你好世界")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = partial_stream  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hello", "partial-session"))
    await stream_started.wait()
    await asyncio.sleep(0.01)  # let TextDelta be processed

    await agent.cancel_session("partial-session")

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task

    messages = await store.get_messages("partial-session", "sebastian")
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert "你好世界" in assistant_msgs[0]["content"]
    assert "[用户中断]" in assistant_msgs[0]["content"]


@pytest.mark.asyncio
async def test_cancel_session_skips_flush_when_no_partial(tmp_path: Path) -> None:
    """If no text was emitted before cancel, no assistant message is written."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="no-partial", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def empty_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = empty_stream  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hi", "no-partial"))
    await stream_started.wait()

    await agent.cancel_session("no-partial")

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task

    messages = await store.get_messages("no-partial", "sebastian")
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 0


@pytest.mark.asyncio
async def test_cancel_session_emits_turn_cancelled_and_turn_response(tmp_path: Path) -> None:
    """cancel_session emits TURN_CANCELLED then TURN_RESPONSE on the event bus."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="event-session", agent_type="sebastian", title="t"))
    bus = EventBus()
    collected: list = []
    bus.subscribe(lambda e: collected.append(e))
    agent = TestAgent(MagicMock(), store, bus)

    stream_started = asyncio.Event()

    async def stream_with_text(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="hi")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = stream_with_text  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hello", "event-session"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    await agent.cancel_session("event-session")

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task

    event_types = [e.type for e in collected]
    assert EventType.TURN_CANCELLED in event_types
    assert EventType.TURN_RESPONSE in event_types
    # TURN_CANCELLED must appear before TURN_RESPONSE
    assert event_types.index(EventType.TURN_CANCELLED) < event_types.index(EventType.TURN_RESPONSE)


@pytest.mark.asyncio
async def test_cancel_session_idempotent(tmp_path: Path) -> None:
    """Second cancel call on same session returns False and does not raise."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="idem-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def slow(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = slow  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hi", "idem-session"))
    await stream_started.wait()

    first = await agent.cancel_session("idem-session")
    second = await agent.cancel_session("idem-session")

    assert first is True
    assert second is False  # stream already gone

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task


@pytest.mark.asyncio
async def test_cancel_session_no_memory_leak_in_buffers(tmp_path: Path) -> None:
    """After cancel, _cancel_requested and _partial_buffer are cleaned up."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="leak-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def stream_partial(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="text")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = stream_partial  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hi", "leak-session"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    await agent.cancel_session("leak-session")

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task

    assert "leak-session" not in agent._cancel_requested
    assert "leak-session" not in agent._partial_buffer
