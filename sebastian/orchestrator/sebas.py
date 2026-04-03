from __future__ import annotations

import logging
from datetime import datetime, timezone

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.base_agent import BaseAgent
from sebastian.core.task_manager import TaskManager
from sebastian.core.types import Session, Task
from sebastian.orchestrator.conversation import ConversationManager
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import EventType
from sebastian.store.index_store import IndexStore
from sebastian.store.session_store import SessionStore

logger = logging.getLogger(__name__)

SEBASTIAN_SYSTEM_PROMPT = """You are Sebastian — an elegant, capable personal AI butler.
Your purpose: receive instructions, plan effectively, and execute precisely.
You have access to tools. Use them to fulfill requests completely.
For complex multi-step tasks, break them down and execute step by step.
When you encounter a decision that requires the user's input, ask clearly and concisely.
You never fabricate results — if a tool fails, say so and suggest alternatives."""


class Sebastian(BaseAgent):
    name = "sebastian"
    system_prompt = SEBASTIAN_SYSTEM_PROMPT

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        index_store: IndexStore,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
    ) -> None:
        super().__init__(registry, session_store, event_bus=event_bus)
        self._index = index_store
        self._task_manager = task_manager
        self._conversation = conversation

    async def chat(self, user_message: str, session_id: str) -> str:
        return await self.run_streaming(user_message, session_id)

    async def get_or_create_session(
        self, session_id: str | None, first_message: str
    ) -> Session:
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
