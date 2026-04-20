from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.gateway.sse import SSEManager
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.memory.consolidation import MemoryConsolidationScheduler
    from sebastian.memory.extraction import MemoryExtractor
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.owner_store import OwnerStore
    from sebastian.store.session_store import SessionStore
    from sebastian.store.todo_store import TodoStore


class MemoryRuntimeSettings(BaseModel):
    enabled: bool


sebastian: Sebastian
sse_manager: SSEManager
event_bus: EventBus
conversation: ConversationManager
session_store: SessionStore
todo_store: TodoStore
index_store: IndexStore
db_factory: async_sessionmaker[AsyncSession]
llm_registry: LLMProviderRegistry
memory_settings: MemoryRuntimeSettings
consolidation_scheduler: MemoryConsolidationScheduler | None = None
memory_extractor: MemoryExtractor | None = None
agent_instances: dict[str, BaseAgent] = {}
agent_registry: dict[str, AgentConfig] = {}


def get_owner_store() -> OwnerStore:
    from sebastian.store.owner_store import OwnerStore as _OwnerStore

    return _OwnerStore(db_factory)  # noqa: F821
