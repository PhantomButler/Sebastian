from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sebastian.core.base_agent import BaseAgent
from sebastian.permissions.gate import PolicyGate
from sebastian.core.task_manager import TaskManager
from sebastian.core.types import Session, Task
from sebastian.orchestrator.conversation import ConversationManager
from sebastian.capabilities.tools import delegate_to_agent as _delegate_tools  # noqa: F401  # registers delegate_to_agent tool
from sebastian.protocol.events.bus import EventBus
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
        gate: PolicyGate,
        session_store: SessionStore,
        index_store: IndexStore,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
        provider: LLMProvider | None = None,
        agent_registry: dict[str, AgentConfig] | None = None,
    ) -> None:
        self._agent_registry: dict[str, AgentConfig] = agent_registry or {}
        super().__init__(gate, session_store, event_bus=event_bus, provider=provider)
        self._index = index_store
        self._task_manager = task_manager
        self._conversation = conversation
        # Rebuild with agent_registry so _agents_section is included
        self.system_prompt = self.build_system_prompt(gate, self._agent_registry)

    def _agents_section(self, agent_registry: dict[str, object] | None = None) -> str:
        registry = agent_registry or self._agent_registry
        if not registry:
            return ""
        lines = ["## Available Sub-Agents", ""]
        for config in registry.values():
            display = getattr(config, "display_name", config.agent_type)
            desc = getattr(config, "description", "")
            lines.append(f"- **{config.agent_type}** ({display}): {desc}")
        lines.append("")
        lines.append("Use the `delegate_to_agent` tool to assign tasks to these agents.")
        return "\n".join(lines)

    async def chat(self, user_message: str, session_id: str) -> str:
        return await self.run_streaming(user_message, session_id)

    async def get_or_create_session(
        self,
        session_id: str | None = None,
        first_message: str = "",
    ) -> Session:
        if session_id:
            session = await self._session_store.get_session(session_id, "sebastian")
            if session:
                return session

        session = Session(
            agent_type="sebastian",
            title=first_message[:40] or "新对话",
            goal=first_message,
            depth=1,
        )
        await self._session_store.create_session(session)

        await self._index.upsert(session)

        return session

    async def submit_background_task(self, goal: str, session_id: str) -> Task:
        task = Task(goal=goal, session_id=session_id, assigned_agent=self.name)

        async def execute(current_task: Task) -> None:
            await self.run(current_task.goal, session_id=session_id, task_id=current_task.id)

        await self._task_manager.submit(task, execute)
        return task
