from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import logging
from abc import ABC
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sebastian.llm.provider import LLMProvider
    from sebastian.protocol.a2a.types import DelegateTask
    from sebastian.protocol.a2a.types import TaskResult as A2ATaskResult

from sebastian.permissions.gate import PolicyGate
from sebastian.permissions.types import ToolCallContext
from sebastian.config import settings
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

BASE_PERSONA = (
    "You are Sebastian, a personal AI butler for {owner_name}. "
    "You are helpful, precise, and action-oriented. "
    "You have access to tools and will use them when needed."
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
    persona: str = BASE_PERSONA
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None
    system_prompt: str = ""  # populated by build_system_prompt in __init__

    def __init__(
        self,
        gate: PolicyGate,
        session_store: SessionStore,
        event_bus: EventBus | None = None,
        provider: LLMProvider | None = None,
        model: str | None = None,
        allowed_tools: list[str] | None = None,
        allowed_skills: list[str] | None = None,
    ) -> None:
        self._gate = gate
        self._current_task_goal: str = ""
        self._session_store = session_store
        self._event_bus = event_bus
        self._episodic = EpisodicMemory(session_store)
        self.working_memory = WorkingMemory()
        self._active_stream: asyncio.Task[str] | None = None

        # instance-level overrides class-level defaults
        if allowed_tools is not None:
            self.allowed_tools = allowed_tools
        if allowed_skills is not None:
            self.allowed_skills = allowed_skills

        resolved_model = model or settings.sebastian_model
        self._provider_injected = provider is not None

        if provider is None:
            from sebastian.llm.anthropic import AnthropicProvider

            provider = AnthropicProvider(api_key=settings.anthropic_api_key)

        self._loop = AgentLoop(
            provider,
            gate,
            resolved_model,
        )
        self.system_prompt = self.build_system_prompt(gate)

    def _persona_section(self) -> str:
        return self.persona.replace("{owner_name}", settings.sebastian_owner_name)

    def _tools_section(self, gate: PolicyGate) -> str:
        allowed = set(self.allowed_tools) if self.allowed_tools is not None else None
        specs = gate.get_tool_specs(allowed)
        if not specs:
            return ""
        lines = ["## Available Tools", ""]
        for spec in specs:
            lines.append(f"- **{spec['name']}**: {spec['description']}")
        return "\n".join(lines)

    def _skills_section(self, gate: PolicyGate) -> str:
        allowed = set(self.allowed_skills) if self.allowed_skills is not None else None
        specs = gate.get_skill_specs(allowed)
        if not specs:
            return ""
        lines = ["## Available Skills", ""]
        for spec in specs:
            lines.append(f"- **{spec['name']}**: {spec['description']}")
        return "\n".join(lines)

    def _agents_section(self, agent_registry: dict[str, object] | None = None) -> str:  # noqa: ARG002
        return ""

    def _knowledge_dir(self) -> Path:
        module_file = inspect.getfile(type(self))
        return Path(module_file).parent / "knowledge"

    def _knowledge_section(self) -> str:
        kdir = self._knowledge_dir()
        if not kdir.is_dir():
            return ""
        md_files = sorted(kdir.glob("*.md"))
        if not md_files:
            return ""
        parts = [f.read_text(encoding="utf-8") for f in md_files]
        body = "\n\n---\n\n".join(parts)
        return f"## Knowledge\n\n{body}"

    def build_system_prompt(
        self,
        gate: PolicyGate,
        agent_registry: dict[str, object] | None = None,
    ) -> str:
        sections = [
            self._persona_section(),
            self._tools_section(gate),
            self._skills_section(gate),
            self._agents_section(agent_registry),
            self._knowledge_section(),
        ]
        return "\n\n".join(s for s in sections if s)

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
        self._current_task_goal = user_message

        if not self._provider_injected:
            try:
                import sebastian.gateway.state as _state

                if not hasattr(_state, "llm_registry"):
                    raise AttributeError("llm_registry not initialised")
                provider, model = await _state.llm_registry.get_default_with_model()
                self._loop._provider = provider
                self._loop._model = model
            except AttributeError:
                pass  # state not initialised — keep existing provider

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
        tool_records: list[dict[str, Any]] = []
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
                    record: dict[str, Any] = {
                        "type": "tool",
                        "tool_id": event.tool_id,
                        "name": event.name,
                        "input": json.dumps(event.inputs, default=str),
                        "status": "failed",
                    }
                    tool_records.append(record)
                    try:
                        context = ToolCallContext(
                            task_goal=self._current_task_goal,
                            session_id=session_id,
                            task_id=task_id,
                        )
                        result = await self._gate.call(event.name, event.inputs, context)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # pragma: no cover - exercised via async failure paths
                        error = str(exc)
                        record["result"] = error
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
                            record["status"] = "done"
                            record["result"] = str(result.output)[:200]
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
                            record["result"] = result.error or ""
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
                        blocks=tool_records if tool_records else None,
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
                    blocks=tool_records if tool_records else None,
                )
            await self._publish(
                session_id,
                EventType.TURN_INTERRUPTED,
                {
                    "partial_content": full_text,
                },
            )
            raise

    async def execute_delegated_task(self, task: DelegateTask) -> A2ATaskResult:
        """Execute a delegated task from Sebastian. Creates an isolated session per task."""
        from sebastian.core.types import Session
        from sebastian.protocol.a2a.types import TaskResult as A2ATaskResult

        session = Session(
            id=f"a2a_{task.task_id}",
            agent_type=self.name,
            agent_id=f"{self.name}_01",
            title=task.goal[:40],
        )
        await self._session_store.create_session(session)

        try:
            result_text = await self.run_streaming(
                task.goal,
                session.id,
                task_id=task.task_id,
                agent_name=self.name,
            )
            return A2ATaskResult(
                task_id=task.task_id,
                ok=True,
                output={"summary": result_text},
            )
        except Exception as exc:
            return A2ATaskResult(
                task_id=task.task_id,
                ok=False,
                error=str(exc),
            )

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
