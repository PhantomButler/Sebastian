from __future__ import annotations

import asyncio

import pytest

from sebastian.gateway.sse import SSEManager
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType


@pytest.mark.asyncio
async def test_event_routed_to_parent_session_subscriber():
    """订阅 Sebastian session 的客户端应收到子代理的 SESSION_COMPLETED 事件。"""
    bus = EventBus()
    mgr = SSEManager(bus)

    received: list[str] = []

    async def consume():
        async for chunk in mgr.stream(session_id="seb-123"):
            received.append(chunk)
            break  # 收到一条就退出

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # 让 consume 进入等待

    await bus.publish(
        Event(
            type=EventType.SESSION_COMPLETED,
            data={
                "session_id": "child-456",
                "parent_session_id": "seb-123",
                "agent_type": "code",
                "goal": "重构",
                "status": "completed",
            },
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert "session.completed" in received[0]


@pytest.mark.asyncio
async def test_event_not_routed_to_unrelated_subscriber():
    """不相关 session 的订阅者不应收到其他 parent 的子代理事件。"""
    bus = EventBus()
    mgr = SSEManager(bus)

    received: list[str] = []

    async def consume():
        async for chunk in mgr.stream(session_id="other-999"):
            received.append(chunk)
            break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)

    await bus.publish(
        Event(
            type=EventType.SESSION_COMPLETED,
            data={
                "session_id": "child-456",
                "parent_session_id": "seb-123",
                "agent_type": "code",
                "goal": "重构",
                "status": "completed",
            },
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 0
