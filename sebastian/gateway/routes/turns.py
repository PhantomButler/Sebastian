from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sebastian.gateway.auth import create_access_token, require_auth, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(tags=["turns"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SendTurnRequest(BaseModel):
    content: str
    session_id: str | None = None


def _log_background_turn_failure(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Background Sebastian turn failed", exc_info=exc)


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    from sebastian.config import settings

    stored_hash = settings.sebastian_owner_password_hash
    if not stored_hash or not verify_password(body.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = create_access_token({"sub": settings.sebastian_owner_name, "role": "owner"})
    return TokenResponse(access_token=token)


@router.post("/turns")
async def send_turn(
    body: SendTurnRequest,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await state.sebastian.get_or_create_session(body.session_id, body.content)
    task = asyncio.create_task(state.sebastian.run_streaming(body.content, session.id))
    task.add_done_callback(_log_background_turn_failure)
    return {
        "session_id": session.id,
        "ts": datetime.now(UTC).isoformat(),
    }
