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
    for agent_type, pool in state.agent_pools.items():
        workers = []
        for agent_id, worker_status in pool.status().items():
            workers.append(
                {
                    "agent_id": agent_id,
                    "status": worker_status.value,
                    "session_id": state.worker_sessions.get(agent_id),
                }
            )
        agents.append(
            {
                "agent_type": agent_type,
                "workers": workers,
                "queue_depth": pool.queue_depth,
            }
        )

    return {
        "agents": agents,
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
