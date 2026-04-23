from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_mock_gate() -> MagicMock:
    gate = MagicMock()
    gate.get_tool_specs.return_value = []
    gate.get_skill_specs.return_value = []
    gate.get_all_tool_specs.return_value = []
    return gate


@pytest.mark.asyncio
async def test_chat_uses_run_streaming_without_duplicate_turn_events(
    tmp_path: Path,
) -> None:
    from sebastian.core.task_manager import TaskManager
    from sebastian.core.types import Session
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType
    from sebastian.store.session_store import SessionStore

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    bus = EventBus()
    conversation = ConversationManager(bus)
    task_manager = TaskManager(store, bus)

    await store.create_session(
        Session(
            id="chat-session",
            agent_type="sebastian",
            title="Chat session",
        )
    )

    collected_events: list[Event] = []

    async def capture(event: Event) -> None:
        collected_events.append(event)

    bus.subscribe(capture)

    agent = Sebastian(
        gate=_make_mock_gate(),
        session_store=store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=bus,
    )

    async def fake_run_streaming(user_message: str, session_id: str) -> str:
        await bus.publish(
            Event(
                type=EventType.TURN_RECEIVED,
                data={"session_id": session_id, "message": user_message[:200]},
            )
        )
        await bus.publish(
            Event(
                type=EventType.TURN_RESPONSE,
                data={"session_id": session_id, "content": "streamed response"},
            )
        )
        return "streamed response"

    agent.run = AsyncMock(side_effect=AssertionError("run should not be called"))  # type: ignore[method-assign]
    agent.run_streaming = AsyncMock(side_effect=fake_run_streaming)  # type: ignore[method-assign]

    response = await agent.chat("hello", "chat-session")

    assert response == "streamed response"
    agent.run_streaming.assert_awaited_once_with("hello", "chat-session")
    assert [event.type for event in collected_events].count(EventType.TURN_RECEIVED) == 1
    assert [event.type for event in collected_events].count(EventType.TURN_RESPONSE) == 1


@pytest.mark.asyncio
async def test_get_or_create_session_creates_sebastian_session(
    tmp_path: Path,
) -> None:

    from sebastian.core.task_manager import TaskManager
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.session_store import SessionStore

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    bus = EventBus()
    conversation = ConversationManager(bus)
    task_manager = TaskManager(store, bus)

    agent = Sebastian(
        gate=_make_mock_gate(),
        session_store=store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=bus,
    )

    session = await agent.get_or_create_session(None, "hello from sebastian")

    assert session.agent_type == "sebastian"
    assert session.depth == 1
    assert session.title == "hello from sebastian"

    loaded = await store.get_session(session.id, "sebastian")
    assert loaded is not None
    assert loaded.id == session.id


@pytest.mark.asyncio
async def test_get_or_create_session_reloads_existing_sebastian_session(
    tmp_path: Path,
) -> None:
    from sebastian.core.task_manager import TaskManager
    from sebastian.core.types import Session
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.session_store import SessionStore

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    bus = EventBus()
    conversation = ConversationManager(bus)
    task_manager = TaskManager(store, bus)

    existing_session = Session(
        id="existing-session",
        agent_type="sebastian",
        title="Persisted title",
    )
    await store.create_session(existing_session)

    agent = Sebastian(
        gate=_make_mock_gate(),
        session_store=store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=bus,
    )

    loaded = await agent.get_or_create_session("existing-session", "ignored")

    assert loaded.id == "existing-session"
    assert loaded.agent_type == "sebastian"
    assert loaded.title == "Persisted title"


@pytest.mark.asyncio
async def test_get_or_create_session_creates_with_client_provided_id(
    tmp_path: Path,
) -> None:
    from sebastian.core.task_manager import TaskManager
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.session_store import SessionStore

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    bus = EventBus()
    conversation = ConversationManager(bus)
    task_manager = TaskManager(store, bus)

    agent = Sebastian(
        gate=_make_mock_gate(),
        session_store=store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=bus,
    )

    # session 不存在，client 提供的 id 应被采用
    session = await agent.get_or_create_session("my-client-id", "hello")

    assert session.id == "my-client-id"
    assert session.agent_type == "sebastian"
    assert session.depth == 1

    loaded = await store.get_session("my-client-id", "sebastian")
    assert loaded is not None
    assert loaded.id == "my-client-id"
    assert loaded.goal == "hello"


def test_sebastian_allowed_tools_use_resume_and_stop_agent() -> None:
    """Sebastian 作为主管家，需要恢复或终止等待中的下属代理。"""
    from sebastian.orchestrator.sebas import Sebastian

    assert Sebastian.allowed_tools is not None
    assert "resume_agent" in Sebastian.allowed_tools
    assert "stop_agent" in Sebastian.allowed_tools
