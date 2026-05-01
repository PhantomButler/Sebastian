from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.session_store import SessionStore

logger = logging.getLogger(__name__)


def _initialize_agent_instances(
    agent_configs: list[AgentConfig],
    gate: Any,
    session_store: SessionStore,
    event_bus: EventBus,
    llm_registry: LLMProviderRegistry,
    db_factory: Any = None,
    compaction_scheduler: Any = None,
    attachment_store: Any = None,
) -> dict[str, BaseAgent]:
    """Create a singleton instance for each registered agent type."""
    instances: dict[str, BaseAgent] = {}
    for cfg in agent_configs:
        agent = cfg.agent_class(
            gate=gate,
            session_store=session_store,
            event_bus=event_bus,
            llm_registry=llm_registry,
            allowed_tools=cfg.allowed_tools,
            allowed_skills=cfg.allowed_skills,
            db_factory=db_factory,
            compaction_scheduler=compaction_scheduler,
            attachment_store=attachment_store,
        )
        agent.name = cfg.agent_type
        instances[cfg.agent_type] = agent
        logger.info("Registered agent instance: %s", cfg.agent_type)
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
    from sebastian.memory.stores.entity_registry import EntityRegistry
    from sebastian.memory.startup import (
        bootstrap_slot_registry,
        init_memory_storage,
        seed_builtin_slots,
    )
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import bus
    from sebastian.store.database import get_engine, get_session_factory, init_db
    from sebastian.store.session_store import SessionStore
    from sebastian.store.todo_store import TodoStore

    ensure_data_dir()
    setup_logging(
        logs_dir=settings.logs_dir,
        llm_stream=settings.sebastian_log_llm_stream,
        sse=settings.sebastian_log_sse,
    )
    await init_db()
    await init_memory_storage(get_engine())
    db_factory = get_session_factory()

    from sebastian.gateway.state import MemoryRuntimeSettings
    from sebastian.store.app_settings_store import APP_SETTING_MEMORY_ENABLED, AppSettingsStore

    async with db_factory() as _app_settings_session:
        _app_store = AppSettingsStore(_app_settings_session)
        _mem_val = await _app_store.get(APP_SETTING_MEMORY_ENABLED)
    mem_enabled = (
        (_mem_val.lower() == "true") if _mem_val is not None else settings.sebastian_memory_enabled
    )
    state.memory_settings = MemoryRuntimeSettings(enabled=mem_enabled)

    async with db_factory() as _seed_session:
        await seed_builtin_slots(_seed_session)
        entity_registry = EntityRegistry(_seed_session)
        try:
            await entity_registry.sync_jieba_terms()
        except Exception as exc:  # noqa: BLE001
            logger.warning("jieba entity term sync failed at startup: %s", exc)
        try:
            # 把 Entity 名灌入 Planner relation 触发词缓存
            from sebastian.memory.retrieval.retrieval import DEFAULT_RETRIEVAL_PLANNER

            await DEFAULT_RETRIEVAL_PLANNER.bootstrap_entity_triggers(entity_registry)
        except Exception as exc:  # noqa: BLE001
            logger.warning("planner entity trigger bootstrap failed at startup: %s", exc)

    from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY

    async with db_factory() as _bootstrap_session:
        await bootstrap_slot_registry(_bootstrap_session, DEFAULT_SLOT_REGISTRY)

    from sebastian.store.attachments import AttachmentStore

    attachment_store = AttachmentStore(settings.attachments_dir, db_factory)
    state.attachment_store = attachment_store

    from sebastian.trigger.job_runs import ScheduledJobRunStore
    from sebastian.trigger.jobs import register_builtin_jobs
    from sebastian.trigger.scheduler import JobRegistry, SchedulerRunner

    _job_registry = JobRegistry()
    register_builtin_jobs(_job_registry, attachment_store=attachment_store)
    _scheduler = SchedulerRunner(
        registry=_job_registry,
        run_store=ScheduledJobRunStore(db_factory),
    )
    await _scheduler.start()
    state.scheduler = _scheduler

    session_store = SessionStore(db_factory=db_factory)
    todo_store = TodoStore(db_factory=db_factory)

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
    from sebastian.memory.consolidation.consolidation import (
        MemoryConsolidationScheduler,
        MemoryConsolidator,
        SessionConsolidationWorker,
    )
    from sebastian.memory.consolidation.extraction import MemoryExtractor
    from sebastian.memory.resident.resident_snapshot import (
        ResidentMemorySnapshotRefresher,
        ResidentSnapshotPaths,
    )

    resident_refresher = ResidentMemorySnapshotRefresher(
        paths=ResidentSnapshotPaths.from_user_data_dir(settings.user_data_dir),
        db_factory=db_factory,
    )
    state.resident_snapshot_refresher = resident_refresher
    try:
        async with db_factory() as _resident_session:
            await resident_refresher.rebuild(_resident_session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("resident snapshot rebuild failed at startup: %s", exc, exc_info=True)
        resident_refresher.schedule_refresh()

    from sebastian.memory.services import MemoryService

    state.memory_service = MemoryService(
        db_factory=db_factory,
        resident_snapshot_refresher=resident_refresher,
        memory_settings_fn=lambda: state.memory_settings.enabled,
    )

    consolidator = MemoryConsolidator(llm_registry)
    extractor = MemoryExtractor(llm_registry)
    consolidation_worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=consolidator,
        extractor=extractor,
        session_store=session_store,
        memory_settings_fn=lambda: state.memory_settings.enabled,
        resident_snapshot_refresher=resident_refresher,
        memory_service=state.memory_service,
    )
    consolidation_scheduler = MemoryConsolidationScheduler(
        event_bus=event_bus,
        worker=consolidation_worker,
        memory_settings_fn=lambda: state.memory_settings.enabled,
    )
    state.consolidation_scheduler = consolidation_scheduler
    state.memory_extractor = extractor

    from sebastian.context.compaction import (
        SessionContextCompactionWorker,
        TurnEndCompactionScheduler,
    )
    from sebastian.context.estimator import TokenEstimator

    _compaction_worker = SessionContextCompactionWorker(
        session_store=session_store,
        llm_registry=llm_registry,
    )

    async def _resolve_context_window(agent_type: str) -> int:
        resolved = await llm_registry.get_provider(agent_type)
        return resolved.context_window_tokens

    state.context_compaction_scheduler = TurnEndCompactionScheduler(
        worker=_compaction_worker,
        context_window_resolver=_resolve_context_window,
        estimator=TokenEstimator(),
    )
    state.context_compaction_worker = _compaction_worker

    # Catch-up sweep: consolidate sessions that completed while the gateway was down.
    from sebastian.memory.consolidation.consolidation import sweep_unconsolidated

    await sweep_unconsolidated(
        db_factory=db_factory,
        worker=consolidation_worker,
        session_store=session_store,
        memory_settings_fn=lambda: state.memory_settings.enabled,
    )

    conversation = ConversationManager(event_bus, db_factory=db_factory)
    task_manager = TaskManager(session_store, event_bus)
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
        task_manager=task_manager,
        conversation=conversation,
        event_bus=event_bus,
        llm_registry=llm_registry,
        agent_registry={cfg.agent_type: cfg for cfg in agent_configs},
        db_factory=db_factory,
        compaction_scheduler=state.context_compaction_scheduler,
        attachment_store=attachment_store,
    )

    state.sebastian = sebastian_agent
    state.sse_manager = sse_mgr
    state.event_bus = event_bus
    state.conversation = conversation
    state.session_store = session_store
    state.todo_store = todo_store
    state.db_factory = db_factory
    state.llm_registry = llm_registry
    state.agent_registry = {cfg.agent_type: cfg for cfg in agent_configs}
    state.agent_instances = _initialize_agent_instances(
        agent_configs=agent_configs,
        gate=gate,
        session_store=state.session_store,
        event_bus=state.event_bus,
        llm_registry=llm_registry,
        db_factory=state.db_factory,
        compaction_scheduler=state.context_compaction_scheduler,
        attachment_store=attachment_store,
    )

    watchdog_task = start_watchdog(
        session_store=state.session_store,
        event_bus=state.event_bus,
        agent_registry=state.agent_registry,
    )

    from sebastian.gateway.completion_notifier import CompletionNotifier

    completion_notifier = CompletionNotifier(
        event_bus=state.event_bus,
        session_store=state.session_store,
        sebastian=state.sebastian,
        agent_instances=state.agent_instances,
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
    with suppress(asyncio.CancelledError):
        await watchdog_task
    try:
        if state.scheduler is not None:
            await state.scheduler.aclose()
            state.scheduler = None
        await completion_notifier.aclose()
        if state.consolidation_scheduler is not None:
            await state.consolidation_scheduler.aclose()
        if state.resident_snapshot_refresher is not None:
            await state.resident_snapshot_refresher.aclose()
            state.resident_snapshot_refresher = None
    finally:
        state.context_compaction_scheduler = None
        state.context_compaction_worker = None
        from sebastian.store.database import get_engine

        await get_engine().dispose()
        await asyncio.sleep(0)
    logger.info("Sebastian gateway shutdown")


def create_app() -> FastAPI:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from sebastian.gateway.routes import (
        agents,
        approvals,
        attachments,
        debug,
        llm_accounts,
        memory_components,
        memory_settings,
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
    app.include_router(attachments.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(stream.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(llm_accounts.router, prefix="/api/v1")
    app.include_router(debug.router, prefix="/api/v1")
    app.include_router(memory_components.router, prefix="/api/v1")
    app.include_router(memory_settings.router, prefix="/api/v1")
    return app


app = create_app()
