from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["agents"])

ORCHESTRATOR_AGENT_TYPE = "sebastian"

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


class BindingUpdate(BaseModel):
    provider_id: str | None = None
    thinking_effort: str | None = None


def _binding_to_dict(binding: Any) -> JSONDict:
    return {
        "agent_type": binding.agent_type,
        "provider_id": binding.provider_id,
        "thinking_effort": binding.thinking_effort,
    }


@router.get("/agents")
async def list_agents(_auth: AuthPayload = Depends(require_auth)) -> JSONDict:
    import sebastian.gateway.state as state

    bindings = await state.llm_registry.list_bindings()
    binding_map = {b.agent_type: b for b in bindings}

    agents: list[JSONDict] = []

    # Sebastian 置顶
    seb_binding = binding_map.get(ORCHESTRATOR_AGENT_TYPE)
    agents.append(
        {
            "agent_type": ORCHESTRATOR_AGENT_TYPE,
            "description": "主管家 AI，负责对话调度与任务分解",
            "is_orchestrator": True,
            "active_session_count": 0,
            "max_children": None,
            "binding": _binding_to_dict(seb_binding) if seb_binding is not None else None,
        }
    )

    for agent_type, config in state.agent_registry.items():
        if agent_type == ORCHESTRATOR_AGENT_TYPE:
            continue  # 已置顶，跳过重复

        sessions = await state.index_store.list_by_agent_type(agent_type)
        active_count = sum(1 for s in sessions if s.get("status") == "active")
        binding = binding_map.get(agent_type)

        agents.append(
            {
                "agent_type": agent_type,
                "description": config.description,
                "is_orchestrator": False,
                "active_session_count": active_count,
                "max_children": config.max_children,
                "binding": _binding_to_dict(binding) if binding is not None else None,
            }
        )

    return {"agents": agents}


@router.get("/agents/{agent_type}/llm-binding")
async def get_agent_binding(
    agent_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if agent_type != ORCHESTRATOR_AGENT_TYPE and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    binding = await state.llm_registry.get_binding(agent_type)
    if binding is None:
        return {
            "agent_type": agent_type,
            "provider_id": None,
            "thinking_effort": None,
        }
    return _binding_to_dict(binding)


@router.put("/agents/{agent_type}/llm-binding")
async def set_agent_binding(
    agent_type: str,
    body: BindingUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if agent_type != ORCHESTRATOR_AGENT_TYPE and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    # 查 provider record（需要读 thinking_capability）
    record = None
    if body.provider_id is not None:
        record = await state.llm_registry.get_record(body.provider_id)
        if record is None:
            raise HTTPException(status_code=400, detail="Provider not found")

    # 查现有 binding，判断 provider 是否切换
    existing = await state.llm_registry.get_binding(agent_type)
    provider_changed = existing is None or existing.provider_id != body.provider_id

    if provider_changed:
        effort: str | None = None
    else:
        effort = body.thinking_effort

    # NONE / ALWAYS_ON capability 强制清空
    if record is not None and record.thinking_capability in ("none", "always_on"):
        effort = None

    binding = await state.llm_registry.set_binding(
        agent_type,
        body.provider_id,
        thinking_effort=effort,
    )
    return _binding_to_dict(binding)


@router.delete("/agents/{agent_type}/llm-binding", status_code=204)
async def clear_agent_binding(
    agent_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    if agent_type != ORCHESTRATOR_AGENT_TYPE and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    await state.llm_registry.clear_binding(agent_type)
    return Response(status_code=204)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
