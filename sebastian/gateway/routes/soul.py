from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from sebastian.gateway.auth import require_auth

if TYPE_CHECKING:
    import sebastian.gateway.state as _StateModule

router = APIRouter(tags=["soul"])


def _get_state() -> _StateModule:
    import sebastian.gateway.state as state

    return state  # type: ignore[return-value]


@router.get("/soul/current")
async def get_current_soul(
    _auth: dict[str, Any] = Depends(require_auth),
) -> dict[str, str]:
    state = _get_state()
    return {"active_soul": state.soul_loader.current_soul}
