from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from sebastian.core.agent_pool import AgentPool
    from sebastian.protocol.events.bus import EventHandler
    from sebastian.protocol.events.types import EventType

logger = logging.getLogger(__name__)


def _discover_agent_types() -> list[str]:
    agents_dir = Path(__file__).resolve().parents[1] / "agents"
    agent_types = ["sebastian"]
    for entry in sorted(agents_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("__"):
            agent_types.append(entry.name)
    return agent_types


def _initialize_runtime_agent_state() -> tuple[dict[str, AgentPool], dict[str, str | None]]:
    from sebastian.core.agent_pool import AgentPool

    agent_pools: dict[str, AgentPool] = {}
    worker_sessions: dict[str, str | None] = {}

    for agent_type in _discover_agent_types():
        worker_count = 1 if agent_type == "sebastian" else 3
        pool = AgentPool(agent_type, worker_count=worker_count)
        agent_pools[agent_type] = pool
        for worker_id in pool.status():
            worker_sessions[worker_id] = None

    return agent_pools, worker_sessions


def _agent_type_from_worker_id(worker_id: str) -> str:
    return worker_id.rsplit("_", maxsplit=1)[0]


def _register_runtime_agent_state_handlers() -> list[tuple[EventType, EventHandler]]:
    import sebastian.gateway.state as state
    from sebastian.core.agent_pool import WorkerStatus
    from sebastian.protocol.events.types import Event, EventType

    async def update_runtime_agent_state(event: Event) -> None:
        session_id = event.data.get("session_id")
        if not isinstance(session_id, str):
            return

        if event.type == EventType.TURN_RECEIVED:
            worker_id = event.data.get("agent_id")
            if not isinstance(worker_id, str):
                return

            pool = state.agent_pools.get(_agent_type_from_worker_id(worker_id))
            if pool is None:
                logger.debug("Ignoring turn event for unknown worker %s", worker_id)
                return

            if pool.status().get(worker_id) == WorkerStatus.BUSY:
                # Worker already busy; skip to avoid ValueError from mark_busy (C2).
                return

            pool.mark_busy(worker_id)
            state.worker_sessions[worker_id] = session_id
            return

        if event.type not in {EventType.TURN_RESPONSE, EventType.TURN_INTERRUPTED}:
            return

        for worker_id, bound_session_id in tuple(state.worker_sessions.items()):
            if bound_session_id != session_id:
                continue
            pool = state.agent_pools.get(_agent_type_from_worker_id(worker_id))
            if pool is None:
                continue
            pool.mark_idle(worker_id)
            state.worker_sessions[worker_id] = None

    subscriptions: list[tuple[EventType, EventHandler]] = []
    for event_type in (
        EventType.TURN_RECEIVED,
        EventType.TURN_RESPONSE,
        EventType.TURN_INTERRUPTED,
    ):
        state.event_bus.subscribe(update_runtime_agent_state, event_type)
        subscriptions.append((event_type, update_runtime_agent_state))
    return subscriptions


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import sebastian.gateway.state as state
    from sebastian.capabilities.mcps._loader import connect_all, load_mcps
    from sebastian.capabilities.registry import registry
    from sebastian.capabilities.tools._loader import load_tools
    from sebastian.config import ensure_data_dir, settings
    from sebastian.core.task_manager import TaskManager
    from sebastian.gateway.sse import SSEManager
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import bus
    from sebastian.store.database import get_session_factory, init_db
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

    ensure_data_dir()
    await init_db()
    db_factory = get_session_factory()
    session_store = SessionStore(settings.sessions_dir)
    index_store = IndexStore(settings.sessions_dir)

    load_tools()

    mcp_clients = load_mcps()
    if mcp_clients:
        await connect_all(mcp_clients, registry)

    event_bus = bus
    conversation = ConversationManager(event_bus)
    task_manager = TaskManager(session_store, event_bus, index_store=index_store)
    sse_mgr = SSEManager(event_bus)
    sebastian_agent = Sebastian(
        registry=registry,
        session_store=session_store,
        index_store=index_store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=event_bus,
    )

    state.sebastian = sebastian_agent
    state.sse_manager = sse_mgr
    state.event_bus = event_bus
    state.conversation = conversation
    state.session_store = session_store
    state.index_store = index_store
    state.db_factory = db_factory
    state.agent_pools, state.worker_sessions = _initialize_runtime_agent_state()
    runtime_subscriptions = _register_runtime_agent_state_handlers()

    logger.info("Sebastian gateway started")
    yield
    for event_type, handler in runtime_subscriptions:
        state.event_bus.unsubscribe(handler, event_type)
    logger.info("Sebastian gateway shutdown")


def create_app() -> FastAPI:
    from sebastian.gateway.routes import agents, approvals, sessions, stream, turns

    app = FastAPI(title="Sebastian Gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(turns.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(stream.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    return app


app = create_app()
