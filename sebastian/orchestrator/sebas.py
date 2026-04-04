from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.base_agent import BaseAgent
from sebastian.core.task_manager import TaskManager
from sebastian.core.types import Session, Task
from sebastian.orchestrator.conversation import ConversationManager
from sebastian.orchestrator.tools import (
    delegate as _delegate_tools,  # noqa: F401  # registers delegate_to_agent tool
)
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import EventType
from sebastian.store.index_store import IndexStore
from sebastian.store.session_store import SessionStore

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

SEBASTIAN_PERSONA = """\
You are Sebastian — a personal AI butler of absolute capability and unwavering loyalty.

Your master is {owner_name}. Your existence has one purpose: to serve their goals completely.

## Character
You are elegant in manner, precise in execution, and utterly composed under pressure.
You do not speculate aloud, do not complain, and do not make excuses.
When you say something will be done, it will be done.

## Loyalty
You serve your master's true intent, not just their literal words.
When instructions are ambiguous, you infer the most reasonable goal and act —
pausing only when the cost of a wrong assumption is irreversible.

## Counsel
You are not merely an executor — you are an advisor.
When you see a better path, a hidden risk, or a flaw in the plan, you say so before proceeding.
You speak plainly: state the concern, state your recommendation, then ask whether to proceed.
You do not volunteer opinions on every decision — only when it matters.

## Capability
You command a staff of specialized sub-agents, each with their own domain.
You decompose complex goals, assign work to the right hands, and hold every thread together —
nothing is dropped, nothing is forgotten.
The master deals only with you. What happens beneath is your responsibility entirely.
You use tools, sub-agents, and skills without hesitation, and own the outcome regardless of who
executed it.
You never fabricate results — if something fails, you report it plainly and propose what comes next.

## Manner
- Report what was done, not what you are about to do.
- When clarification is needed, surface all critical questions at once — do not drip-feed them.
  The master should be able to course-correct early, not after you have gone far down the wrong
  path.
- Do not pad responses with pleasantries or apologies.\
"""


class Sebastian(BaseAgent):
    name = "sebastian"
    persona = SEBASTIAN_PERSONA

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        index_store: IndexStore,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
        provider: LLMProvider | None = None,
        agent_registry: dict[str, AgentConfig] | None = None,
    ) -> None:
        super().__init__(registry, session_store, event_bus=event_bus, provider=provider)
        self._index = index_store
        self._task_manager = task_manager
        self._conversation = conversation
        self._agent_registry = agent_registry or {}
        # Rebuild with agent_registry so _agents_section is included
        self.system_prompt = self.build_system_prompt(registry, self._agent_registry)

    def _agents_section(self, agent_registry: dict[str, object] | None = None) -> str:
        if not agent_registry:
            return ""
        lines = ["## Available Sub-Agents", ""]
        for config in agent_registry.values():
            from sebastian.agents._loader import AgentConfig
            if isinstance(config, AgentConfig):
                lines.append(f"- **{config.agent_type}** ({config.name}): {config.description}")
        lines += [
            "",
            "Use the `delegate_to_agent` tool to hand off tasks to the appropriate sub-agent.",
        ]
        return "\n".join(lines)

    async def chat(self, user_message: str, session_id: str) -> str:
        return await self.run_streaming(user_message, session_id)

    async def get_or_create_session(self, session_id: str | None, first_message: str) -> Session:
        if session_id:
            existing = await self._session_store.get_session(
                session_id,
                agent_type="sebastian",
                agent_id="sebastian_01",
            )
            if existing is not None:
                existing.updated_at = datetime.now(timezone.utc)  # noqa: UP017
                await self._session_store.update_session(existing)
                await self._index.upsert(existing)
                return existing

        session = Session(
            agent_type="sebastian",
            agent_id="sebastian_01",
            title=first_message[:40],
        )
        await self._session_store.create_session(session)
        await self._index.upsert(session)
        return session

    async def intervene(self, agent_name: str, session_id: str, message: str) -> str:
        response = await self.run(message, session_id, agent_name=agent_name)
        await self._publish(
            session_id,
            EventType.USER_INTERVENED,
            {
                "agent": agent_name,
                "message": message[:200],
            },
        )
        return response

    async def submit_background_task(self, goal: str, session_id: str) -> Task:
        task = Task(goal=goal, session_id=session_id, assigned_agent=self.name)

        async def execute(current_task: Task) -> None:
            await self.run(current_task.goal, session_id=session_id, task_id=current_task.id)

        await self._task_manager.submit(task, execute)
        return task
