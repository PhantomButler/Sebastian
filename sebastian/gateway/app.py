from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.llm.registry import LLMProviderRegistry
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
    llm_registry: LLMProviderRegistry,
) -> dict[str, BaseAgent]:
    """Create a singleton instance for each registered agent type."""
    instances: dict[str, BaseAgent] = {}
    for cfg in agent_configs:
        agent = cfg.agent_class(
            gate=gate,
            session_store=session_store,
            event_bus=event_bus,
            index_store=index_store,
            llm_registry=llm_registry,
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
    from sebastian.store.todo_store import TodoStore

    ensure_data_dir()
    setup_logging(
        data_dir=settings.data_dir,
        llm_stream=settings.sebastian_log_llm_stream,
        sse=settings.sebastian_log_sse,
    )
    await init_db()
    db_factory = get_session_factory()
    session_store = SessionStore(settings.sessions_dir)
    todo_store = TodoStore(settings.sessions_dir)
    index_store = IndexStore(settings.sessions_dir, session_store=session_store)

    from sebastian.llm.registry import LLMProviderRegistry

    llm_registry = LLMProviderRegistry(db_factory)

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

    from sebastian.permissions.gate import PolicyGate
    from sebastian.permissions.reviewer import PermissionReviewer

    reviewer = PermissionReviewer(llm_registry=llm_registry)
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
        llm_registry=llm_registry,
        agent_registry={cfg.agent_type: cfg for cfg in agent_configs},
    )

    state.sebastian = sebastian_agent
    state.sse_manager = sse_mgr
    state.event_bus = event_bus
    state.conversation = conversation
    state.session_store = session_store
    state.todo_store = todo_store
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
        llm_registry=llm_registry,
    )

    watchdog_task = start_watchdog(
        index_store=state.index_store,
        session_store=state.session_store,
        event_bus=state.event_bus,
        agent_registry=state.agent_registry,
    )

    # Setup mode detection: triggered when no owner OR no secret.key
    from sebastian.gateway.setup.secret_key import SecretKeyManager
    from sebastian.gateway.setup.security import SetupSecurity
    from sebastian.gateway.setup.setup_routes import create_setup_router
    from sebastian.store.owner_store import OwnerStore

    owner_store = OwnerStore(db_factory)
    secret_key = SecretKeyManager(settings.resolved_secret_key_path())
    needs_setup = (not await owner_store.owner_exists()) or (not secret_key.exists())

    app.state.setup_mode = needs_setup
    if needs_setup:
        token = SetupSecurity.generate_token()
        security = SetupSecurity(token=token)
        app.include_router(
            create_setup_router(
                security=security,
                owner_store=owner_store,
                secret_key=secret_key,
            )
        )
        url = f"http://127.0.0.1:{settings.sebastian_gateway_port}/setup?token={token}"
        print("\n" + "=" * 60)
        print("  Sebastian 首次启动：请完成初始化")
        print(f"  打开浏览器: {url}")
        print("=" * 60 + "\n")
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    logger.info("Sebastian gateway started")
    yield
    watchdog_task.cancel()
    logger.info("Sebastian gateway shutdown")


def create_app() -> FastAPI:
    from fastapi import Request
    from fastapi.responses import JSONResponse

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

    @app.middleware("http")
    async def _setup_mode_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
        if getattr(app.state, "setup_mode", False) and not request.url.path.startswith("/setup"):
            return JSONResponse(
                {"detail": "Sebastian is in setup mode. Visit /setup to initialize."},
                status_code=503,
            )
        return await call_next(request)

    app.include_router(turns.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(stream.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(llm_providers.router, prefix="/api/v1")
    app.include_router(debug.router, prefix="/api/v1")
    return app


app = create_app()
