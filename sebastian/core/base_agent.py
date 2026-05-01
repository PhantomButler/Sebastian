from __future__ import annotations

import asyncio
import dataclasses
import inspect
import logging
import time
from abc import ABC
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.context.compaction import CompactionScheduler
    from sebastian.llm.provider import LLMProvider
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.memory.resident_snapshot import ResidentSnapshotReadResult

from ulid import ULID

from sebastian.config import settings
from sebastian.core.agent_loop import AgentLoop
from sebastian.core.compaction_hook import (
    allocate_exchange_for_turn,
    schedule_compaction_if_needed,
)
from sebastian.core.stream_events import (
    ProviderCallEnd,
    ProviderCallStart,
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
from sebastian.core.stream_events import ToolResult as StreamToolResult
from sebastian.core.stream_helpers import (
    dispatch_tool_call as _dispatch_tool_call_fn,
)
from sebastian.core.stream_helpers import (
    ensure_tool_results_for_pending_calls as _ensure_tool_results_for_pending_calls,
)
from sebastian.memory.retrieval.depth_guard import is_memory_eligible
from sebastian.memory.working_memory import WorkingMemory
from sebastian.permissions.gate import PolicyGate
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType
from sebastian.store.session_store import SessionStore

logger = logging.getLogger(__name__)

CancelIntent = Literal["cancel", "stop"]


BASE_PERSONA = (
    "You are Sebastian, a personal AI butler. "
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
    _active_streams: dict[str, asyncio.Task[Any]]

    def __init__(
        self,
        gate: PolicyGate,
        session_store: SessionStore,
        event_bus: EventBus | None = None,
        provider: LLMProvider | None = None,
        model: str | None = None,
        allowed_tools: list[str] | None = None,
        allowed_skills: list[str] | None = None,
        llm_registry: LLMProviderRegistry | None = None,
        db_factory: async_sessionmaker[AsyncSession] | None = None,
        compaction_scheduler: CompactionScheduler | None = None,
        attachment_store: Any | None = None,
    ) -> None:
        self._gate = gate
        self._db_factory = db_factory
        self._attachment_store = attachment_store
        self._compaction_scheduler = compaction_scheduler
        self._current_task_goals: dict[str, str] = {}  # session_id → goal
        self._current_depth: dict[str, int] = {}  # session_id → depth
        self._session_store = session_store
        self._event_bus = event_bus
        self._llm_registry = llm_registry
        self.working_memory = WorkingMemory()
        self._active_streams: dict[str, asyncio.Task[str]] = {}  # session_id → task
        # session_id → intent: "cancel" ends as cancelled; "stop" keeps context for resume.
        self._cancel_requested: dict[str, CancelIntent] = {}
        # session_id → completed cancel intent, available for outer consumers after teardown.
        self._completed_cancel_intents: dict[str, CancelIntent] = {}
        # session_id → pre-cancel intent registered before the stream task is live.
        # Consumed by run_streaming immediately after registering _active_streams.
        self._pending_cancel_intents: dict[str, CancelIntent] = {}
        # session_id → asyncio.TimerHandle for pending-cancel TTL cleanup
        self._pending_cancel_timers: dict[str, asyncio.TimerHandle] = {}
        self._partial_buffer: dict[str, str] = {}
        self._pending_blocks: dict[str, list[dict[str, Any]]] = {}

        # instance-level overrides class-level defaults
        if allowed_tools is not None:
            self.allowed_tools = allowed_tools
        if allowed_skills is not None:
            self.allowed_skills = allowed_skills

        resolved_model = model or settings.sebastian_model
        self._provider_injected = provider is not None

        self._loop = AgentLoop(
            provider,
            gate,
            resolved_model,
            allowed_tools=(set(self.allowed_tools) if self.allowed_tools is not None else None),
            allowed_skills=(set(self.allowed_skills) if self.allowed_skills is not None else None),
        )
        self.system_prompt = self.build_system_prompt(gate)

    def _persona_section(self) -> str:
        return self.persona

    def _guidelines_section(self) -> str:
        return (
            "## Operation Guidelines\n\n"
            f"- Workspace directory: `{settings.workspace_dir}`. "
            "Use relative paths for all file operations — they resolve to "
            "workspace automatically.\n"
            "- Prefer structured tools over shell commands for file operations:\n"
            "  - Use `Read` instead of `bash cat`\n"
            "  - Use `Write` / `Edit` instead of `bash sed`, `bash tee`, or redirect (`>`)\n"
            "  - Use `Glob` instead of `bash find`\n"
            "  - Use `Grep` instead of `bash grep` / `bash rg`\n"
            "- Operations outside the workspace directory require user approval. "
            "Always explain why you need to access a path outside workspace before requesting."
        )

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

    def _agents_section(self, agent_registry: Mapping[str, Any] | None = None) -> str:  # noqa: ARG002
        return ""

    def _knowledge_dir(self) -> Path:
        module_file = inspect.getfile(type(self))
        return Path(module_file).parent / "knowledge"

    async def _session_todos_section(
        self,
        session_id: str,
        agent_type: str,
    ) -> str:
        """Return a '## Session Todos' section reflecting current todos.json.

        Empty string if no todos exist. Called fresh each turn so the LLM
        sees the latest state without needing a read tool.
        """
        try:
            import sebastian.gateway.state as state

            store = state.todo_store
        except (ImportError, AttributeError):
            return ""

        items = await store.read(agent_type, session_id)
        if not items:
            return ""

        lines = ["## Session Todos", ""]
        for idx, item in enumerate(items, start=1):
            marker = {
                "pending": "[ ]",
                "in_progress": "[→]",
                "completed": "[x]",
            }.get(item.status.value, "[?]")
            display = item.active_form if item.status.value == "in_progress" else item.content
            lines.append(f"{idx}. {marker} {display}")
        lines.append("")
        lines.append(
            "(The above reflects the current session todo list. Use todo_write "
            "to update — pass the complete new list, not just changed items.)"
        )
        return "\n".join(lines)

    async def _resident_memory_section(self, session_id: str) -> ResidentSnapshotReadResult:
        """Return the cached resident memory snapshot for depth-1 sessions.

        Returns an empty ResidentSnapshotReadResult on any failure, if memory is
        disabled, if the refresher is absent, or if depth != 1.
        """
        from sebastian.memory.resident_snapshot import ResidentSnapshotReadResult

        if not is_memory_eligible(self._current_depth.get(session_id)):
            return ResidentSnapshotReadResult(content="")
        try:
            import sebastian.gateway.state as state

            if state.memory_service is None or not state.memory_service.is_enabled():
                return ResidentSnapshotReadResult(content="")
            refresher = getattr(state, "resident_snapshot_refresher", None)
            if refresher is None:
                return ResidentSnapshotReadResult(content="")
            return cast("ResidentSnapshotReadResult", await refresher.read())
        except Exception:
            logger.warning("Resident memory section read failed", exc_info=True)
            return ResidentSnapshotReadResult(content="")

    async def _memory_section(
        self,
        session_id: str,
        agent_context: str,
        user_message: str,
        *,
        resident_record_ids: set[str] | None = None,
        resident_dedupe_keys: set[str] | None = None,
        resident_canonical_bullets: set[str] | None = None,
    ) -> str:
        """Return assembled memory context string. Empty string on any failure or if disabled.

        depth 守卫（spec §5 / artifact-model.md §10.4）：长期记忆只注入给 depth=1
        的 Sebastian 本体。depth != 1（包括未初始化 → None）一律 fail-closed 返回 "".
        """
        if not is_memory_eligible(self._current_depth.get(session_id)):
            return ""

        if self._db_factory is None:
            return ""
        try:
            from sebastian.memory.subject import resolve_subject
            from sebastian.memory.trace import trace
            from sebastian.memory.types import MemoryScope

            subject_id = await resolve_subject(
                MemoryScope.USER,
                session_id=session_id,
                agent_type=agent_context,
            )

            import sebastian.gateway.state as state

            if state.memory_service is None:
                return ""

            from sebastian.memory.contracts.retrieval import PromptMemoryRequest

            request = PromptMemoryRequest(
                session_id=session_id,
                agent_type=agent_context,
                user_message=user_message,
                subject_id=subject_id,
                active_project_or_agent_context={"agent_type": agent_context},
                resident_record_ids=resident_record_ids or set(),
                resident_dedupe_keys=resident_dedupe_keys or set(),
                resident_canonical_bullets=resident_canonical_bullets or set(),
            )
            result = await state.memory_service.retrieve_for_prompt(request)
            trace(
                "memory_section.injected",
                session_id=session_id,
                agent_type=agent_context,
                subject_id=subject_id,
                section_chars=len(result.section),
            )
            return result.section
        except Exception:
            logger.warning(
                "Memory section retrieval failed, continuing without memory context",
                exc_info=True,
            )
            return ""

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
        agent_registry: Mapping[str, Any] | None = None,
    ) -> str:
        sections = [
            self._persona_section(),
            self._guidelines_section(),
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
        *,
        persist_user_message: bool = True,
        preallocated_exchange: tuple[str, int] | None = None,
    ) -> str:
        self._completed_cancel_intents.pop(session_id, None)
        self._current_task_goals[session_id] = user_message

        thinking_effort_for_llm: str | None = None
        if not self._provider_injected and self._llm_registry is not None:
            resolved = await self._llm_registry.get_provider(self.name)
            provider, model = resolved.provider, resolved.model
            self._loop._provider = provider
            self._loop._model = model
            thinking_effort_for_llm = resolved.thinking_effort
            logger.info(
                "LLM resolved: agent=%s session=%s provider=%s model=%s thinking_effort=%s",
                self.name,
                session_id,
                type(provider).__name__,
                model,
                resolved.thinking_effort,
            )

        agent_context = agent_name or self.name
        existing_stream = self._active_streams.get(session_id)
        if existing_stream is not None and not existing_stream.done():
            existing_stream.cancel()
            try:
                await existing_stream
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

        self._current_depth[session_id] = worker_session.depth

        await self._publish(
            session_id,
            EventType.TURN_RECEIVED,
            {
                "agent_type": worker_session.agent_type,
                "message": user_message[:200],
            },
        )
        await self._update_activity(session_id, agent_context)

        # _llm_registry resolution above guarantees _provider is set in production;
        # "anthropic" is the fallback for test-only agents with no provider injected.
        provider_format = "anthropic"
        if self._loop._provider is not None:
            provider_format = self._loop._provider.message_format

        if self._db_factory is not None:
            messages = await self._session_store.get_context_messages(
                session_id,
                agent_context,
                provider_format,
                attachment_store=self._attachment_store,
                require_attachments=self._attachment_store is not None,
            )
        else:
            raw = await self._session_store.get_messages(session_id, agent_context, limit=50)
            messages = [{"role": m["role"], "content": m["content"]} for m in raw]

        if persist_user_message:
            messages.append({"role": "user", "content": user_message})

        exchange_id: str | None = None
        exchange_index: int | None = None
        if preallocated_exchange is not None:
            exchange_id, exchange_index = preallocated_exchange
        elif self._db_factory is not None and persist_user_message:
            exchange_id, exchange_index = await allocate_exchange_for_turn(
                self._session_store, session_id, agent_context
            )

        if persist_user_message:
            await self._session_store.append_message(
                session_id,
                "user",
                user_message,
                agent_type=agent_context,
                exchange_id=exchange_id,
                exchange_index=exchange_index,
            )

        current_stream = asyncio.create_task(
            self._stream_inner(
                messages=messages,
                session_id=session_id,
                task_id=task_id,
                agent_context=agent_context,
                thinking_effort=thinking_effort_for_llm,
                exchange_id=exchange_id,
                exchange_index=exchange_index,
            )
        )
        self._active_streams[session_id] = current_stream
        # Consume pre-cancel: user clicked stop before we finished setup.
        pending_intent = self._pending_cancel_intents.pop(session_id, None)
        pending_timer = self._pending_cancel_timers.pop(session_id, None)
        if pending_timer is not None:
            pending_timer.cancel()
        if pending_intent is not None:
            self._cancel_requested[session_id] = pending_intent
            current_stream.cancel()
        try:
            return await current_stream
        finally:
            cancel_intent = self._cancel_requested.pop(session_id, None)
            was_cancelled = cancel_intent is not None
            self._active_streams.pop(session_id, None)
            self._current_task_goals.pop(session_id, None)
            self._current_depth.pop(session_id, None)

            if was_cancelled:
                assert cancel_intent is not None
                self._completed_cancel_intents[session_id] = cancel_intent
                pending_blocks = self._pending_blocks.pop(session_id, [])
                partial = self._partial_buffer.pop(session_id, "")
                if partial or pending_blocks:
                    try:
                        if pending_blocks:
                            _ensure_tool_results_for_pending_calls(
                                pending_blocks,
                                reason="Tool execution cancelled before result was available.",
                            )
                        await self._session_store.append_message(
                            session_id,
                            "assistant",
                            (f"{partial}\n\n[用户中断]" if cancel_intent == "cancel" else partial),
                            agent_type=agent_context,
                            blocks=pending_blocks if pending_blocks else None,
                            exchange_id=exchange_id,
                            exchange_index=exchange_index,
                        )
                    except Exception:
                        logger.warning("Failed to flush partial text on cancel", exc_info=True)
                if cancel_intent == "cancel":
                    await self._publish(
                        session_id,
                        EventType.TURN_CANCELLED,
                        {"agent_type": agent_context, "had_partial": bool(partial)},
                    )
                else:
                    await self._publish(
                        session_id,
                        EventType.TURN_INTERRUPTED,
                        {
                            "agent_type": agent_context,
                            "intent": cancel_intent,
                            "partial_content": partial,
                        },
                    )
                await self._publish(session_id, EventType.TURN_RESPONSE, {})
            else:
                self._partial_buffer.pop(session_id, None)
                self._pending_blocks.pop(session_id, None)

    async def _stream_inner(
        self,
        messages: list[dict[str, str]],
        session_id: str,
        task_id: str | None,
        agent_context: str,
        thinking_effort: str | None = None,
        exchange_id: str | None = None,
        exchange_index: int | None = None,
    ) -> str:
        from sebastian.context.usage import TokenUsage

        full_text = ""
        assistant_blocks: list[dict[str, Any]] = []
        assistant_turn_id = str(ULID())
        current_pci: int = 0
        block_index: int = 0
        last_provider_usage: TokenUsage | None = None
        todo_section = await self._session_todos_section(session_id, agent_context)
        resident = await self._resident_memory_section(session_id)
        last_user_msg = messages[-1].get("content", "") if messages else ""
        memory_section = await self._memory_section(
            session_id,
            agent_context,
            user_message=last_user_msg,
            resident_record_ids=resident.rendered_record_ids,
            resident_dedupe_keys=resident.rendered_dedupe_keys,
            resident_canonical_bullets=resident.rendered_canonical_bullets,
        )
        sections = [self.system_prompt]
        if resident.content:
            sections.append(resident.content)
        if memory_section:
            sections.append(memory_section)
        if todo_section:
            sections.append(todo_section)
        effective_system_prompt = "\n\n".join(sections)
        gen = self._loop.stream(
            effective_system_prompt, messages, task_id=task_id, thinking_effort=thinking_effort
        )
        _thinking_start: dict[str, float] = {}
        send_value: StreamToolResult | None = None

        try:
            while True:
                try:
                    event = await gen.asend(send_value)
                except StopAsyncIteration:
                    return full_text
                send_value = None

                if isinstance(event, ProviderCallStart):
                    current_pci = event.index
                    block_index = 0
                    continue

                if isinstance(event, ProviderCallEnd):
                    if event.usage is not None:
                        last_provider_usage = event.usage
                    continue

                if isinstance(event, TextDelta):
                    full_text += event.delta
                    self._partial_buffer[session_id] = full_text

                if isinstance(event, ThinkingBlockStart):
                    _thinking_start[event.block_id] = time.monotonic()

                if isinstance(event, ThinkingBlockStop):
                    start = _thinking_start.pop(event.block_id, None)
                    if start is not None:
                        event.duration_ms = int((time.monotonic() - start) * 1000)

                stream_event_type = _STREAM_EVENT_TYPES.get(type(event))
                if stream_event_type is not None:
                    await self._publish(
                        session_id,
                        stream_event_type,
                        dataclasses.asdict(event),
                    )

                if isinstance(event, ThinkingBlockStop):
                    block: dict[str, Any] = {
                        "type": "thinking",
                        "thinking": event.thinking,
                        "assistant_turn_id": assistant_turn_id,
                        "provider_call_index": current_pci,
                        "block_index": block_index,
                    }
                    if event.signature is not None:
                        block["signature"] = event.signature
                    if event.duration_ms is not None:
                        block["duration_ms"] = event.duration_ms
                    assistant_blocks.append(block)
                    block_index += 1
                    self._pending_blocks[session_id] = assistant_blocks

                if isinstance(event, TextBlockStop):
                    assistant_blocks.append(
                        {
                            "type": "text",
                            "text": event.text,
                            "assistant_turn_id": assistant_turn_id,
                            "provider_call_index": current_pci,
                            "block_index": block_index,
                        }
                    )
                    block_index += 1
                    self._pending_blocks[session_id] = assistant_blocks

                if isinstance(event, ToolCallReady):
                    send_value, block_index = await _dispatch_tool_call_fn(
                        event,
                        session_id=session_id,
                        task_id=task_id,
                        agent_context=agent_context,
                        assistant_turn_id=assistant_turn_id,
                        assistant_blocks=assistant_blocks,
                        current_pci=current_pci,
                        block_index=block_index,
                        gate_call=self._gate.call,
                        update_activity=self._update_activity,
                        publish=self._publish,
                        current_task_goals=self._current_task_goals,
                        current_depth=self._current_depth,
                        allowed_tools=self.allowed_tools,
                        pending_blocks=self._pending_blocks,
                    )
                    continue

                if isinstance(event, TurnDone):
                    self._pending_blocks.pop(session_id, None)
                    await self._session_store.append_message(
                        session_id,
                        "assistant",
                        event.full_text,
                        agent_type=agent_context,
                        blocks=assistant_blocks if assistant_blocks else None,
                        exchange_id=exchange_id,
                        exchange_index=exchange_index,
                    )
                    await self._publish(
                        session_id,
                        EventType.TURN_RESPONSE,
                        {
                            "content": event.full_text,
                            "interrupted": False,
                        },
                    )
                    await self._update_activity(session_id, agent_context)
                    await schedule_compaction_if_needed(
                        scheduler=self._compaction_scheduler,
                        session_id=session_id,
                        agent_type=agent_context,
                        usage=last_provider_usage,
                        messages=messages,
                        system_prompt=effective_system_prompt,
                    )
                    return event.full_text
        except asyncio.CancelledError:
            # When cancelled via cancel_session(), the finally block in run_streaming
            # handles episodic flush. Only save here for external cancellations.
            if session_id not in self._cancel_requested:
                self._pending_blocks.pop(session_id, None)
                if full_text or assistant_blocks:
                    try:
                        _ensure_tool_results_for_pending_calls(
                            assistant_blocks,
                            reason="Tool execution cancelled before result was available.",
                        )
                        await self._session_store.append_message(
                            session_id,
                            "assistant",
                            full_text,
                            agent_type=agent_context,
                            blocks=assistant_blocks if assistant_blocks else None,
                            exchange_id=exchange_id,
                            exchange_index=exchange_index,
                        )
                    except Exception:
                        logger.warning("Failed to flush blocks on external cancel", exc_info=True)
                await self._publish(
                    session_id,
                    EventType.TURN_INTERRUPTED,
                    {
                        "partial_content": full_text,
                    },
                )
            raise

    async def _update_activity(self, session_id: str, agent_type: str) -> None:
        """Update last_activity_at for stalled detection."""
        await self._session_store.update_activity(session_id, agent_type)

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

    async def cancel_session(self, session_id: str, intent: CancelIntent = "cancel") -> bool:
        """Cancel the active streaming turn for session_id.

        If no stream is registered yet (race between REST return and
        run_streaming registering _active_streams), record the intent in
        _pending_cancel_intents so run_streaming consumes it on registration.

        Returns True if a stream was cancelled OR a pending cancel was registered;
        False only if the intent is invalid (raised) — never silently False.
        """
        validated_intent = self._validate_cancel_intent(intent)
        stream = self._active_streams.get(session_id)
        if stream is None or stream.done():
            # Pre-cancel: run_streaming will consume this on _active_streams registration.
            self._pending_cancel_intents[session_id] = validated_intent
            self._schedule_pending_cancel_cleanup(session_id)
            return True
        previous = self._cancel_requested.get(session_id)
        if previous is not None and previous != validated_intent:
            logger.warning(
                "cancel_session overriding pending intent for session %s: %s -> %s",
                session_id,
                previous,
                validated_intent,
            )
        self._cancel_requested[session_id] = validated_intent
        stream.cancel()
        try:
            await stream
        except (asyncio.CancelledError, Exception):
            pass
        return True

    def _schedule_pending_cancel_cleanup(self, session_id: str) -> None:
        """Expire _pending_cancel_intents[session_id] after 60s to avoid leaks
        when run_streaming never starts (e.g. turn aborted during setup)."""
        previous = self._pending_cancel_timers.pop(session_id, None)
        if previous is not None:
            previous.cancel()
        loop = asyncio.get_running_loop()
        handle = loop.call_later(60.0, self._expire_pending_cancel, session_id)
        self._pending_cancel_timers[session_id] = handle

    def _expire_pending_cancel(self, session_id: str) -> None:
        self._pending_cancel_intents.pop(session_id, None)
        self._pending_cancel_timers.pop(session_id, None)

    def consume_cancel_intent(self, session_id: str) -> CancelIntent | None:
        """Return and clear the completed cancel intent for a session, if any."""
        return self._completed_cancel_intents.pop(session_id, None)

    @staticmethod
    def _validate_cancel_intent(intent: str) -> CancelIntent:
        if intent not in ("cancel", "stop"):
            raise ValueError(f"Invalid cancel intent: {intent}")
        return cast(CancelIntent, intent)
