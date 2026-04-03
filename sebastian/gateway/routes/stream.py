from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["stream"])

AuthPayload = dict[str, Any]


def _parse_last_event_id(last_event_id: str | None) -> int | None:
    if last_event_id is None:
        return None
    try:
        return int(last_event_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Last-Event-ID header") from exc


@router.get("/stream")
async def global_stream(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    _auth: AuthPayload = Depends(require_auth),
) -> StreamingResponse:
    """SSE endpoint: streams all events to the connected client."""
    import sebastian.gateway.state as state

    replay_cursor = _parse_last_event_id(last_event_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        async for chunk in state.sse_manager.stream(
            session_id=None,
            last_event_id=replay_cursor,
        ):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/stream")
async def session_stream(
    session_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    _auth: AuthPayload = Depends(require_auth),
) -> StreamingResponse:
    import sebastian.gateway.state as state

    replay_cursor = _parse_last_event_id(last_event_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        async for chunk in state.sse_manager.stream(
            session_id=session_id,
            last_event_id=replay_cursor,
        ):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
