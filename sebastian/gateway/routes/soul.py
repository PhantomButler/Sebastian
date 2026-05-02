from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["soul"])

AuthPayload = dict[str, Any]


def _get_state() -> Any:
    import sebastian.gateway.state as state

    return state


@router.get("/soul/current")
async def get_current_soul(
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, str]:
    state = _get_state()
    return {"active_soul": state.soul_loader.current_soul}
