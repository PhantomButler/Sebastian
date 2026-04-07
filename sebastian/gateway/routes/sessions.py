from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sebastian.core.types import InvalidTaskTransitionError, Session, Task
from sebastian.gateway.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sessions"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


@router.get("/sessions")
async def list_sessions(
    agent_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    sessions = await state.index_store.list_all()
    if agent_type is not None:
        sessions = [s for s in sessions if s.get("agent_type") == agent_type]
    if status is not None:
        sessions = [s for s in sessions if s.get("status") == status]
    total = len(sessions)
    sessions = sessions[offset : offset + limit]
    return {"sessions": sessions, "total": total}


@router.get("/agents/{agent_type}/sessions")
async def list_agent_sessions(
    agent_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    sessions = await state.index_store.list_by_agent_type(agent_type)
    return {"agent_type": agent_type, "sessions": sessions}


@router.post("/agents/{agent_type}/sessions")
async def create_agent_session(
    agent_type: str,
    body: dict,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    """Create a new conversation with a sub-agent."""
    import sebastian.gateway.state as state

    if agent_type not in state.agent_instances:
        raise HTTPException(404, f"Agent type not found: {agent_type}")

    content = body.get("content", "")
    if not content:
        raise HTTPException(400, "content is required")

    session = Session(
        agent_type=agent_type,
        title=content[:40],
        depth=2,
    )
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    agent = state.agent_instances[agent_type]

    from sebastian.core.session_runner import run_agent_session

    asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=content,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )

    return {"session_id": session.id, "ts": session.created_at.isoformat()}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    messages = await state.session_store.get_messages(
        session_id,
        session.agent_type,
        limit=50,
    )
    return {"session": session.model_dump(mode="json"), "messages": messages}


class SendTurnBody(BaseModel):
    content: str


def _log_background_turn_failure(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Background session turn failed", exc_info=exc)


async def _resolve_session(state: Any, session_id: str) -> Session:
    entries = await state.index_store.list_all()
    entry = next((e for e in entries if e["id"] == session_id), None)
    if entry is None:
        raise HTTPException(404, "Session not found")
    session = await state.session_store.get_session(session_id, entry["agent_type"])
    if session is None:
        raise HTTPException(404, "Session data not found")
    return cast(Session, session)


async def _touch_session(state: Any, session: Session) -> datetime:
    now = datetime.now(UTC)
    session.updated_at = now
    await state.session_store.update_session(session)
    await state.index_store.upsert(session)
    return now


async def _resolve_session_task(
    state: Any,
    session_id: str,
    task_id: str,
) -> tuple[Session, Task]:
    session = await _resolve_session(state, session_id)
    task = await state.session_store.get_task(
        session_id,
        task_id,
        session.agent_type,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return session, task


async def _schedule_session_turn(
    session: Session,
    content: str,
) -> None:
    """Route a turn to the correct agent instance."""
    import sebastian.gateway.state as state

    if session.agent_type == "sebastian":
        task = asyncio.create_task(
            state.sebastian.run_streaming(content, session.id)
        )
    else:
        agent = state.agent_instances.get(session.agent_type)
        if agent is None:
            raise ValueError(f"No agent instance for type: {session.agent_type}")
        task = asyncio.create_task(
            agent.run_streaming(content, session.id, agent_name=session.agent_type)
        )
    task.add_done_callback(_log_background_turn_failure)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    await state.session_store.delete_session(session)
    await state.index_store.remove(session_id)
    return {"session_id": session_id, "deleted": True}


@router.post("/sessions/{session_id}/turns")
async def send_turn_to_session(
    session_id: str,
    body: SendTurnBody,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    now = await _touch_session(state, session)
    await _schedule_session_turn(session, body.content)

    return {
        "session_id": session_id,
        "ts": now.isoformat(),
    }


@router.get("/sessions/{session_id}/tasks")
async def list_session_tasks(
    session_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    tasks = await state.session_store.list_tasks(
        session_id,
        session.agent_type,
    )
    return {"tasks": [task.model_dump(mode="json") for task in tasks]}


@router.get("/sessions/{session_id}/tasks/{task_id}")
async def get_session_task(
    session_id: str,
    task_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    _, task = await _resolve_session_task(state, session_id, task_id)
    return {"task": task.model_dump(mode="json")}



@router.delete("/sessions/{session_id}/tasks/{task_id}")
async def cancel_task(
    session_id: str,
    task_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    await _resolve_session_task(state, session_id, task_id)
    cancelled = await state.sebastian._task_manager.cancel(task_id)
    return {"task_id": task_id, "cancelled": cancelled}


@router.post(
    "/sessions/{session_id}/tasks/{task_id}/cancel",
    response_model=None,
)
async def cancel_task_post(
    session_id: str,
    task_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict | JSONResponse:
    """Cancel a task by POST (spec Section 8.2).

    Returns 200 + {"ok": true} on success, 404 if not found,
    409 if the state machine forbids cancellation.
    """
    import sebastian.gateway.state as state

    _, task = await _resolve_session_task(state, session_id, task_id)
    try:
        cancelled = await state.sebastian._task_manager.cancel(task_id)
    except InvalidTaskTransitionError as exc:
        # Placeholder for when TaskManager.cancel() is wired through _transition().
        raise HTTPException(
            status_code=409,
            detail={"detail": str(exc), "code": "INVALID_TASK_TRANSITION"},
        ) from exc
    if not cancelled:
        raise HTTPException(status_code=404, detail="Task not found or not cancellable")
    return {"ok": True}


@router.get("/sessions/{session_id}/recent")
async def get_session_recent(
    session_id: str,
    limit: int = 5,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    """HTTP version of inspect_session — returns recent messages + status."""
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    messages = await state.session_store.get_messages(
        session_id, session.agent_type, limit=limit,
    )
    return {
        "session_id": session.id,
        "status": session.status,
        "title": session.title,
        "last_activity_at": session.last_activity_at.isoformat(),
        "messages": messages,
    }
