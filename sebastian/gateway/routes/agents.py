from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["agents"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


@router.get("/agents")
async def list_agents(_auth: AuthPayload = Depends(require_auth)) -> JSONDict:
    import sebastian.gateway.state as state

    agents = []
    for agent_type, config in state.agent_registry.items():
        if agent_type == "sebastian":
            continue

        sessions = await state.index_store.list_by_agent_type(agent_type)
        active_count = sum(1 for s in sessions if s.get("status") == "active")

        agents.append({
            "agent_type": agent_type,
            "name": config.display_name,
            "description": config.description,
            "active_session_count": active_count,
            "max_children": config.max_children,
        })

    return {"agents": agents}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
