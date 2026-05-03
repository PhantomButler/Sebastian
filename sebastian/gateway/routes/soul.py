from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

from fastapi import APIRouter, Depends

from sebastian.gateway.auth import require_auth

if TYPE_CHECKING:
    from sebastian.core.soul_loader import SoulLoader


class _SoulState(Protocol):
    soul_loader: SoulLoader


router = APIRouter(tags=["soul"])


def _get_state() -> _SoulState:
    import sebastian.gateway.state as state

    return cast(_SoulState, state)


@router.get("/soul/current")
async def get_current_soul(
    _auth: dict[str, Any] = Depends(require_auth),
) -> dict[str, str]:
    state = _get_state()
    return {"active_soul": state.soul_loader.current_soul}
