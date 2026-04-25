from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth
from sebastian.gateway.routes.llm_accounts import _build_resolved_metadata

router = APIRouter(tags=["agents"])

ORCHESTRATOR_AGENT_TYPE = "sebastian"

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


class BindingUpdate(BaseModel):
    account_id: str | None = None
    model_id: str | None = None
    thinking_effort: str | None = None


async def _binding_to_dict(registry: Any, binding: Any) -> JSONDict:
    resolved = await _build_resolved_metadata(registry, binding.account_id, binding.model_id)
    return {
        "agent_type": binding.agent_type,
        "account_id": binding.account_id,
        "model_id": binding.model_id,
        "thinking_effort": binding.thinking_effort,
        "resolved": resolved,
    }


@router.get("/agents")
async def list_agents(_auth: AuthPayload = Depends(require_auth)) -> JSONDict:
    import sebastian.gateway.state as state

    bindings = await state.llm_registry.list_bindings()
    binding_map = {b.agent_type: b for b in bindings}

    agents: list[JSONDict] = []

    seb_binding = binding_map.get(ORCHESTRATOR_AGENT_TYPE)
    agents.append(
        {
            "agent_type": ORCHESTRATOR_AGENT_TYPE,
            "description": "主管家 AI，负责对话调度与任务分解",
            "is_orchestrator": True,
            "active_session_count": 0,
            "max_children": None,
            "binding": (
                await _binding_to_dict(state.llm_registry, seb_binding)
                if seb_binding is not None
                else None
            ),
        }
    )

    for agent_type, config in state.agent_registry.items():
        if agent_type == ORCHESTRATOR_AGENT_TYPE:
            continue

        sessions = await state.session_store.list_sessions_by_agent_type(agent_type)
        active_count = sum(1 for s in sessions if s.get("status") == "active")
        binding = binding_map.get(agent_type)

        agents.append(
            {
                "agent_type": agent_type,
                "description": config.description,
                "is_orchestrator": False,
                "active_session_count": active_count,
                "max_children": config.max_children,
                "binding": (
                    await _binding_to_dict(state.llm_registry, binding)
                    if binding is not None
                    else None
                ),
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
            "account_id": None,
            "model_id": None,
            "thinking_effort": None,
        }
    return await _binding_to_dict(state.llm_registry, binding)


@router.put("/agents/{agent_type}/llm-binding")
async def set_agent_binding(
    agent_type: str,
    body: BindingUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.llm.registry import _coerce_thinking

    if agent_type != ORCHESTRATOR_AGENT_TYPE and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    if body.account_id is None or body.model_id is None:
        # Both must be provided together, or both None to clear
        if body.account_id is not None or body.model_id is not None:
            raise HTTPException(
                status_code=400,
                detail="account_id and model_id must both be provided or both be null",
            )
        await state.llm_registry.clear_binding(agent_type)
        return {
            "agent_type": agent_type,
            "account_id": None,
            "model_id": None,
            "thinking_effort": None,
        }

    account = await state.llm_registry.get_account(body.account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="Account not found")

    try:
        model_spec = await state.llm_registry.get_model_spec(account, body.model_id)
    except (KeyError, RuntimeError):
        raise HTTPException(status_code=400, detail=f"Model {body.model_id!r} not found")

    existing = await state.llm_registry.get_binding(agent_type)
    binding_changed = existing is None or (
        existing.account_id != body.account_id or existing.model_id != body.model_id
    )

    if binding_changed:
        effort: str | None = None
    else:
        effort = body.thinking_effort

    effort = _coerce_thinking(effort, model_spec.thinking_capability)

    binding = await state.llm_registry.set_binding(
        agent_type,
        body.account_id,
        body.model_id,
        thinking_effort=effort,
    )
    return await _binding_to_dict(state.llm_registry, binding)


@router.delete("/agents/{agent_type}/llm-binding", status_code=204)
async def clear_agent_binding(
    agent_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    if agent_type == "__default__":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete __default__ binding; PUT a new value instead.",
        )

    if agent_type != ORCHESTRATOR_AGENT_TYPE and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    await state.llm_registry.clear_binding(agent_type)
    return Response(status_code=204)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
