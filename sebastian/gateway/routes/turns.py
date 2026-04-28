from __future__ import annotations

import logging
from asyncio import Task
from asyncio import create_task as _create_task
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
    content: str = ""
    session_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)


async def _ensure_llm_ready(agent_type: str) -> None:
    """Verify that the given agent_type has a usable LLM provider.

    Raises HTTPException(400) with a structured code if none is configured,
    so the client can render a friendly error pointing to Settings.
    """
    import sebastian.gateway.state as state

    try:
        await state.llm_registry.get_provider(agent_type)
    except RuntimeError:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_llm_provider",
                "message": "尚未配置 LLM Provider，请前往 Settings → 模型 页面添加",
            },
        )


def _log_background_turn_failure(task: Task[object]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Background Sebastian turn failed", exc_info=exc)


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    from sebastian.gateway.state import get_owner_store

    owner = await get_owner_store().get_owner()
    if owner is None or not verify_password(body.password, owner.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = create_access_token({"sub": owner.name, "role": "owner"})
    return TokenResponse(access_token=token)


@router.post("/turns")
async def send_turn(
    body: SendTurnRequest,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.gateway.routes._attachment_helpers import validate_and_write_attachment_turn

    await _ensure_llm_ready("sebastian")

    if body.attachment_ids:
        # Attachment path: validate first, then create/get session, then write atomically
        # Use first attachment filename as session goal hint if content is empty
        session_goal = body.content or "(attachment)"
        session = await state.sebastian.get_or_create_session(body.session_id, session_goal)

        _att_records, exchange_id, exchange_index = await validate_and_write_attachment_turn(
            content=body.content,
            attachment_ids=body.attachment_ids,
            session_id=session.id,
            agent_type="sebastian",
        )

        task = _create_task(
            state.sebastian.run_streaming(
                body.content,
                session.id,
                persist_user_message=False,
                preallocated_exchange=(exchange_id, exchange_index),
            )
        )
        task.add_done_callback(_log_background_turn_failure)
    else:
        # No attachments: existing path unchanged
        if not body.content.strip():
            raise HTTPException(400, "content or attachment_ids required")
        session = await state.sebastian.get_or_create_session(body.session_id, body.content)
        task = _create_task(state.sebastian.run_streaming(body.content, session.id))
        task.add_done_callback(_log_background_turn_failure)

    return {
        "session_id": session.id,
        "ts": datetime.now(UTC).isoformat(),
    }
