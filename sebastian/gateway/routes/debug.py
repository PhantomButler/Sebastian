# sebastian/gateway/routes/debug.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from sebastian.gateway.auth import require_auth
from sebastian.log import get_log_manager
from sebastian.log.schema import LogConfigPatch, LogState

router = APIRouter(tags=["debug"])

AuthPayload = dict[str, Any]


@router.get("/debug/logging", response_model=LogState)
async def get_logging_state(
    _auth: AuthPayload = Depends(require_auth),
) -> LogState:
    return get_log_manager().get_state()


@router.patch("/debug/logging", response_model=LogState)
async def patch_logging_state(
    body: LogConfigPatch,
    _auth: AuthPayload = Depends(require_auth),
) -> LogState:
    mgr = get_log_manager()
    if body.llm_stream_enabled is not None:
        mgr.set_llm_stream(body.llm_stream_enabled)
    if body.sse_enabled is not None:
        mgr.set_sse(body.sse_enabled)
    return mgr.get_state()
