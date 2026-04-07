from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

logger = logging.getLogger(__name__)


def _initialize_agent_instances(
    agent_configs: list[AgentConfig],
    gate: Any,
    session_store: SessionStore,
    event_bus: EventBus,
    index_store: IndexStore,
) -> dict[str, BaseAgent]:
    """Create a singleton instance for each registered agent type."""
    instances: dict[str, BaseAgent] = {}
    for cfg in agent_configs:
        agent = cfg.agent_class(
            gate=gate,
            session_store=session_store,
            event_bus=event_bus,
            index_store=index_store,
            allowed_tools=cfg.allowed_tools,
            allowed_skills=cfg.allowed_skills,
        )
        agent.name = cfg.agent_type
        instances[cfg.agent_type] = agent
        logger.info("Registered agent instance: %s (%s)", cfg.agent_type, cfg.display_name)
    return instances


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import sebastian.gateway.state as state
    from sebastian.capabilities.mcps._loader import connect_all, load_mcps
    from sebastian.capabilities.registry import registry
    from sebastian.capabilities.tools._loader import load_tools
    from sebastian.config import ensure_data_dir, settings
    from sebastian.core.task_manager import TaskManager
    from sebastian.gateway.sse import SSEManager
    from sebastian.log import setup_logging
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import bus
    from sebastian.store.database import get_session_factory, init_db
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

    ensure_data_dir()
    setup_logging(
        data_dir=settings.data_dir,
        llm_stream=settings.sebastian_log_llm_stream,
        sse=settings.sebastian_log_sse,
    )
    await init_db()
    db_factory = get_session_factory()
    session_store = SessionStore(settings.sessions_dir)
    index_store = IndexStore(settings.sessions_dir)

    from sebastian.llm.registry import LLMProviderRegistry

    llm_registry = LLMProviderRegistry(db_factory)
    default_provider = await llm_registry.get_default()

    load_tools()

    from sebastian.capabilities.skills._loader import load_skills

    skill_specs = load_skills(
        extra_dirs=[settings.skills_extensions_dir],
    )
    registry.register_skill_specs(skill_specs)
    logger.info("Loaded %d skills", len(skill_specs))

    mcp_clients = load_mcps()
    if mcp_clients:
        await connect_all(mcp_clients, registry)

    event_bus = bus
    conversation = ConversationManager(event_bus, db_factory=db_factory)
    task_manager = TaskManager(session_store, event_bus, index_store=index_store)
    sse_mgr = SSEManager(event_bus)

    from sebastian.llm.anthropic import AnthropicProvider
    from sebastian.permissions.gate import PolicyGate
    from sebastian.permissions.reviewer import PermissionReviewer

    if isinstance(default_provider, AnthropicProvider):
        _reviewer_client = default_provider._client
    else:
        import anthropic as _anthropic
        _reviewer_client = _anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    reviewer = PermissionReviewer(client=_reviewer_client)
    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=conversation)

    from sebastian.agents._loader import load_agents
    from sebastian.core.stalled_watchdog import start_watchdog

    agent_configs = load_agents()

    sebastian_agent = Sebastian(
        gate=gate,
        session_store=session_store,
        index_store=index_store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=event_bus,
        provider=default_provider,
        agent_registry={cfg.agent_type: cfg for cfg in agent_configs},
    )

    state.sebastian = sebastian_agent
    state.sse_manager = sse_mgr
    state.event_bus = event_bus
    state.conversation = conversation
    state.session_store = session_store
    state.index_store = index_store
    state.db_factory = db_factory
    state.llm_registry = llm_registry
    state.agent_registry = {cfg.agent_type: cfg for cfg in agent_configs}
    state.agent_instances = _initialize_agent_instances(
        agent_configs=agent_configs,
        gate=gate,
        session_store=state.session_store,
        event_bus=state.event_bus,
        index_store=state.index_store,
    )

    watchdog_task = start_watchdog(
        index_store=state.index_store,
        session_store=state.session_store,
        event_bus=state.event_bus,
        agent_registry=state.agent_registry,
    )

    logger.info("Sebastian gateway started")
    yield
    watchdog_task.cancel()
    logger.info("Sebastian gateway shutdown")


def create_app() -> FastAPI:
    from sebastian.gateway.routes import (
        agents,
        approvals,
        debug,
        llm_providers,
        sessions,
        stream,
        turns,
    )

    app = FastAPI(title="Sebastian Gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(turns.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(stream.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(llm_providers.router, prefix="/api/v1")
    app.include_router(debug.router, prefix="/api/v1")
    return app


app = create_app()
