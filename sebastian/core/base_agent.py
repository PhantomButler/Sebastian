from __future__ import annotations

import asyncio
import dataclasses
import logging
from abc import ABC

import anthropic

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.agent_loop import AgentLoop
from sebastian.core.stream_events import (
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ThinkingDelta,
    ToolCallBlockStart,
    ToolCallReady,
    TurnDone,
)
from sebastian.core.stream_events import (
    ToolResult as StreamToolResult,
)
from sebastian.memory.episodic_memory import EpisodicMemory
from sebastian.memory.working_memory import WorkingMemory
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType
from sebastian.store.session_store import SessionStore

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = (
    "You are Sebastian, a personal AI butler. You are helpful, precise, and action-oriented. "
    "You have access to tools and will use them when needed. "
    "Think step by step, act efficiently, and always confirm important actions before executing."
)

_STREAM_EVENT_TYPES: dict[type[object], EventType] = {
    ThinkingBlockStart: EventType.THINKING_BLOCK_START,
    ThinkingDelta: EventType.TURN_THINKING_DELTA,
    ThinkingBlockStop: EventType.THINKING_BLOCK_STOP,
    TextBlockStart: EventType.TEXT_BLOCK_START,
    TextDelta: EventType.TURN_DELTA,
    TextBlockStop: EventType.TEXT_BLOCK_STOP,
    ToolCallBlockStart: EventType.TOOL_BLOCK_START,
}


class BaseAgent(ABC):
    name: str = "base_agent"
    system_prompt: str = BASE_SYSTEM_PROMPT

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        event_bus: EventBus | None = None,
        model: str | None = None,
    ) -> None:
        self._registry = registry
        self._session_store = session_store
        self._event_bus = event_bus
        self._episodic = EpisodicMemory(session_store)
        self.working_memory = WorkingMemory()
        self._active_stream: asyncio.Task[str] | None = None

        from sebastian.config import settings

        resolved_model = model or settings.sebastian_model
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._loop = AgentLoop(self._client, registry, resolved_model)

    async def run(
        self,
        user_message: str,
        session_id: str,
        task_id: str | None = None,
        agent_name: str | None = None,
    ) -> str:
        return await self.run_streaming(
            user_message,
            session_id,
            task_id=task_id,
            agent_name=agent_name,
        )

    async def run_streaming(
        self,
        user_message: str,
        session_id: str,
        task_id: str | None = None,
        agent_name: str | None = None,
    ) -> str:
        agent_context = agent_name or self.name
        if self._active_stream is not None and not self._active_stream.done():
            self._active_stream.cancel()
            try:
                await self._active_stream
            except (asyncio.CancelledError, Exception):
                pass  # Previous stream has ended; ignore its result (M5).

        worker_session = await self._session_store.get_session_for_agent_type(
            session_id,
            agent_context,
        )
        if worker_session is None:
            raise FileNotFoundError(
                f"Session {session_id!r} not found for agent_type {agent_context!r}"
            )

        await self._publish(
            session_id,
            EventType.TURN_RECEIVED,
            {
                "agent_id": worker_session.agent_id,
                "message": user_message[:200],
            },
        )
        turns = await self._episodic.get_turns(session_id, agent=agent_context, limit=20)
        messages: list[dict[str, str]] = [
            {"role": turn.role, "content": turn.content} for turn in turns
        ]
        messages.append({"role": "user", "content": user_message})

        await self._episodic.add_turn(
            session_id,
            "user",
            user_message,
            agent=agent_context,
        )

        current_stream = asyncio.create_task(
            self._stream_inner(
                messages=messages,
                session_id=session_id,
                task_id=task_id,
                agent_context=agent_context,
            )
        )
        self._active_stream = current_stream
        try:
            return await current_stream
        finally:
            if self._active_stream is current_stream:
                self._active_stream = None

    async def _stream_inner(
        self,
        messages: list[dict[str, str]],
        session_id: str,
        task_id: str | None,
        agent_context: str,
    ) -> str:
        full_text = ""
        gen = self._loop.stream(self.system_prompt, messages, task_id=task_id)
        send_value: StreamToolResult | None = None

        try:
            while True:
                try:
                    event = await gen.asend(send_value)
                except StopAsyncIteration:
                    return full_text
                send_value = None

                if isinstance(event, TextDelta):
                    full_text += event.delta

                stream_event_type = _STREAM_EVENT_TYPES.get(type(event))
                if stream_event_type is not None:
                    await self._publish(
                        session_id,
                        stream_event_type,
                        dataclasses.asdict(event),
                    )

                if isinstance(event, ToolCallReady):
                    await self._publish(
                        session_id,
                        EventType.TOOL_BLOCK_STOP,
                        dataclasses.asdict(event),
                    )
                    await self._publish(
                        session_id,
                        EventType.TOOL_RUNNING,
                        {
                            "tool_id": event.tool_id,
                            "name": event.name,
                        },
                    )
                    try:
                        result = await self._registry.call(event.name, **event.inputs)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # pragma: no cover - exercised via async failure paths
                        error = str(exc)
                        await self._publish(
                            session_id,
                            EventType.TOOL_FAILED,
                            {
                                "tool_id": event.tool_id,
                                "name": event.name,
                                "error": error,
                            },
                        )
                        send_value = StreamToolResult(
                            tool_id=event.tool_id,
                            name=event.name,
                            ok=False,
                            output=None,
                            error=error,
                        )
                    else:
                        if result.ok:
                            await self._publish(
                                session_id,
                                EventType.TOOL_EXECUTED,
                                {
                                    "tool_id": event.tool_id,
                                    "name": event.name,
                                    "result_summary": str(result.output)[:200],
                                },
                            )
                        else:
                            await self._publish(
                                session_id,
                                EventType.TOOL_FAILED,
                                {
                                    "tool_id": event.tool_id,
                                    "name": event.name,
                                    "error": result.error,
                                },
                            )
                        send_value = StreamToolResult(
                            tool_id=event.tool_id,
                            name=event.name,
                            ok=result.ok,
                            output=result.output,
                            error=result.error,
                        )
                    continue

                if isinstance(event, TurnDone):
                    await self._episodic.add_turn(
                        session_id,
                        "assistant",
                        event.full_text,
                        agent=agent_context,
                    )
                    await self._publish(
                        session_id,
                        EventType.TURN_RESPONSE,
                        {
                            "content": event.full_text,
                            "interrupted": False,
                        },
                    )
                    return event.full_text
        except asyncio.CancelledError:
            if full_text:
                await self._episodic.add_turn(
                    session_id,
                    "assistant",
                    full_text,
                    agent=agent_context,
                )
            await self._publish(
                session_id,
                EventType.TURN_INTERRUPTED,
                {
                    "partial_content": full_text,
                },
            )
            raise

    async def _publish(
        self,
        session_id: str,
        event_type: EventType,
        data: dict[str, object],
    ) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            Event(
                type=event_type,
                data={"session_id": session_id, **data},
            )
        )
