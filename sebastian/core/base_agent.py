from __future__ import annotations
import logging
from abc import ABC
from typing import Any

import anthropic

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.agent_loop import AgentLoop
from sebastian.memory.episodic_memory import EpisodicMemory
from sebastian.memory.working_memory import WorkingMemory

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = (
    "You are Sebastian, a personal AI butler. You are helpful, precise, and action-oriented. "
    "You have access to tools and will use them when needed. "
    "Think step by step, act efficiently, and always confirm important actions before executing."
)


class BaseAgent(ABC):
    """Abstract base for all agents (Sebastian and Sub-Agents).
    Provides an AgentLoop, working memory (instance-level), and episodic
    memory access (per-session via session factory).
    """

    name: str = "base_agent"
    system_prompt: str = BASE_SYSTEM_PROMPT

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_factory: Any,  # async_sessionmaker[AsyncSession]
        model: str | None = None,
    ) -> None:
        self._registry = registry
        self._session_factory = session_factory
        self.working_memory = WorkingMemory()

        from sebastian.config import settings
        resolved_model = model or settings.sebastian_model
        api_key = settings.anthropic_api_key
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._loop = AgentLoop(self._client, registry, resolved_model)

    async def run(
        self,
        user_message: str,
        session_id: str,
        task_id: str | None = None,
    ) -> str:
        """Run one turn: load history, call agent loop, persist turn, return response."""
        async with self._session_factory() as db_session:
            episodic = EpisodicMemory(db_session)
            turns = await episodic.get_turns(session_id, limit=20)
            messages: list[dict[str, Any]] = [
                {"role": t.role, "content": t.content} for t in turns
            ]
            messages.append({"role": "user", "content": user_message})

            response = await self._loop.run(
                system_prompt=self.system_prompt,
                messages=messages,
                task_id=task_id,
            )

            await episodic.add_turn(session_id, "user", user_message)
            await episodic.add_turn(session_id, "assistant", response)
            return response
