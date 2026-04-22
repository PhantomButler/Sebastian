from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from sebastian.gateway.completion_notifier import CompletionNotifier
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType


def _make_notifier(parent_agent=None, last_message="任务已完成，所有文件已修改"):
    bus = EventBus()
    session_store = AsyncMock()

    session_store.list_sessions = AsyncMock(
        return_value=[
            {
                "id": "seb-123",
                "agent_type": "sebastian",
                "depth": 1,
                "status": "active",
                "goal": "管理任务",
            }
        ]
    )

    session_store.get_recent_timeline_items = AsyncMock(
        return_value=[
            {"kind": "user_message", "role": "user", "content": "重构 auth", "seq": 1, "created_at": "2026-01-01T00:00:00"},
            {"kind": "assistant_message", "role": "assistant", "content": last_message, "seq": 2, "created_at": "2026-01-01T00:01:00"},
        ]
    )

    if parent_agent is not None:
        sebastian = parent_agent
    else:
        sebastian = AsyncMock()
        sebastian.run_streaming = AsyncMock(return_value="ok")

    notifier = CompletionNotifier(
        event_bus=bus,
        session_store=session_store,
        sebastian=sebastian,
        agent_instances={},
        agent_registry={},
    )
    return notifier, bus, sebastian


@pytest.mark.asyncio
async def test_completed_event_triggers_sebastian_turn():
    notifier, bus, sebastian = _make_notifier()

    await bus.publish(
        Event(
            type=EventType.SESSION_COMPLETED,
            data={
                "session_id": "child-456",
                "parent_session_id": "seb-123",
                "agent_type": "code",
                "goal": "重构 auth 模块",
                "status": "completed",
            },
        )
    )

    await asyncio.sleep(0.1)
    await notifier.aclose()

    sebastian.run_streaming.assert_called_once()
    call_args = sebastian.run_streaming.call_args
    notification = call_args[0][0]
    session_id_arg = call_args[0][1]

    assert "已完成" in notification
    assert "重构 auth 模块" in notification
    assert "任务已完成，所有文件已修改" in notification
    assert session_id_arg == "seb-123"


@pytest.mark.asyncio
async def test_failed_event_triggers_sebastian_turn():
    notifier, bus, sebastian = _make_notifier(last_message="执行失败，无法找到配置文件")

    await bus.publish(
        Event(
            type=EventType.SESSION_FAILED,
            data={
                "session_id": "child-456",
                "parent_session_id": "seb-123",
                "agent_type": "code",
                "goal": "重构 auth 模块",
                "status": "failed",
            },
        )
    )

    await asyncio.sleep(0.1)
    await notifier.aclose()

    notification = sebastian.run_streaming.call_args[0][0]
    assert "失败" in notification
    assert "执行失败，无法找到配置文件" in notification


@pytest.mark.asyncio
async def test_waiting_event_triggers_sebastian_turn_with_question():
    notifier, bus, sebastian = _make_notifier()

    await bus.publish(
        Event(
            type=EventType.SESSION_WAITING,
            data={
                "session_id": "child-456",
                "parent_session_id": "seb-123",
                "agent_type": "code",
                "goal": "重构 auth 模块",
                "question": "config.yaml 文件要覆盖吗？",
            },
        )
    )

    await asyncio.sleep(0.1)
    await notifier.aclose()

    notification = sebastian.run_streaming.call_args[0][0]
    assert "config.yaml 文件要覆盖吗？" in notification
    assert "resume_agent" in notification
    assert "agent_type：code" in notification


@pytest.mark.asyncio
async def test_no_parent_session_id_is_ignored():
    notifier, bus, sebastian = _make_notifier()

    await bus.publish(
        Event(
            type=EventType.SESSION_COMPLETED,
            data={
                "session_id": "orphan-789",
                "agent_type": "code",
                "goal": "x",
                "status": "completed",
            },
        )
    )

    await asyncio.sleep(0.1)
    await notifier.aclose()

    sebastian.run_streaming.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_events_serialized_for_same_parent():
    """同一父 session 的多个通知应串行处理，不并发。"""
    call_order: list[int] = []
    call_count = 0

    async def fake_run_streaming(msg, session_id, **kwargs):
        nonlocal call_count
        call_count += 1
        order = call_count
        await asyncio.sleep(0.05)
        call_order.append(order)
        return "ok"

    sebastian = AsyncMock()
    sebastian.run_streaming = fake_run_streaming

    notifier, bus, _ = _make_notifier(parent_agent=sebastian)

    for _ in range(3):
        await bus.publish(
            Event(
                type=EventType.SESSION_COMPLETED,
                data={
                    "session_id": "child-x",
                    "parent_session_id": "seb-123",
                    "agent_type": "code",
                    "goal": "任务",
                    "status": "completed",
                },
            )
        )

    await asyncio.sleep(0.5)
    await notifier.aclose()

    assert call_order == [1, 2, 3]
