from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sessions"])


@router.get("/sessions")
async def list_sessions(_auth: dict = Depends(require_auth)) -> dict:
    import sebastian.gateway.state as state

    sessions = await state.index_store.list_all()
    return {"sessions": sessions}


@router.get("/agents/{agent_type}/sessions")
async def list_agent_sessions(
    agent_type: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    sessions = await state.index_store.list_by_agent_type(agent_type)
    return {"agent_type": agent_type, "sessions": sessions}


@router.get("/agents/{agent_type}/workers/{agent_id}/sessions")
async def list_worker_sessions(
    agent_type: str,
    agent_id: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    sessions = await state.index_store.list_by_worker(agent_type, agent_id)
    return {
        "agent_type": agent_type,
        "agent_id": agent_id,
        "sessions": sessions,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    messages = await state.session_store.get_messages(
        session_id,
        session.agent_type,
        session.agent_id,
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


async def _resolve_session(state, session_id: str):
    sessions = await state.index_store.list_all()
    session_meta = next((item for item in sessions if item["id"] == session_id), None)
    if session_meta is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session = await state.session_store.get_session(
        session_id,
        session_meta.get("agent_type", "sebastian"),
        session_meta.get("agent_id", "sebastian_01"),
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _touch_session(state, session) -> datetime:
    now = datetime.now(UTC)
    session.updated_at = now
    await state.session_store.update_session(session)
    await state.index_store.upsert(session)
    return now


async def _resolve_session_task(state, session_id: str, task_id: str):
    session = await _resolve_session(state, session_id)
    task = await state.session_store.get_task(
        session_id,
        task_id,
        session.agent_type,
        session.agent_id,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return session, task


def _schedule_session_turn(state, session, content: str) -> None:
    if session.agent_type == "sebastian":
        task = asyncio.create_task(state.sebastian.run_streaming(content, session.id))
    else:
        task = asyncio.create_task(
            state.sebastian.intervene(session.agent_type, session.id, content)
        )
    task.add_done_callback(_log_background_turn_failure)


@router.post("/sessions/{session_id}/turns")
async def send_turn_to_session(
    session_id: str,
    body: SendTurnBody,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    now = await _touch_session(state, session)
    _schedule_session_turn(state, session, body.content)

    return {
        "session_id": session_id,
        "ts": now.isoformat(),
    }


@router.post("/sessions/{session_id}/intervene")
async def intervene_session(
    session_id: str,
    body: SendTurnBody,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    now = await _touch_session(state, session)
    _schedule_session_turn(state, session, body.content)
    return {
        "session_id": session_id,
        "ts": now.isoformat(),
    }


@router.get("/sessions/{session_id}/tasks")
async def list_session_tasks(
    session_id: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    tasks = await state.session_store.list_tasks(
        session_id,
        session.agent_type,
        session.agent_id,
    )
    return {"tasks": [task.model_dump(mode="json") for task in tasks]}


@router.get("/sessions/{session_id}/tasks/{task_id}")
async def get_session_task(
    session_id: str,
    task_id: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    _, task = await _resolve_session_task(state, session_id, task_id)
    return {"task": task.model_dump(mode="json")}


@router.post("/sessions/{session_id}/tasks/{task_id}/pause")
async def pause_task(
    session_id: str,
    task_id: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    await _resolve_session_task(state, session_id, task_id)
    cancelled = await state.sebastian._task_manager.cancel(task_id)
    return {"task_id": task_id, "paused": cancelled}


@router.delete("/sessions/{session_id}/tasks/{task_id}")
async def cancel_task(
    session_id: str,
    task_id: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    await _resolve_session_task(state, session_id, task_id)
    cancelled = await state.sebastian._task_manager.cancel(task_id)
    return {"task_id": task_id, "cancelled": cancelled}
