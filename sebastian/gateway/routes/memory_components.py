# sebastian/gateway/routes/memory_components.py
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth
from sebastian.gateway.routes.llm_accounts import _build_resolved_metadata
from sebastian.memory.provider_bindings import MEMORY_COMPONENT_META, MEMORY_COMPONENT_TYPES

if TYPE_CHECKING:
    from sebastian.store.models import AgentLLMBindingRecord

router = APIRouter(tags=["memory"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


class ComponentBindingUpdate(BaseModel):
    account_id: str | None = None
    model_id: str | None = None
    thinking_effort: str | None = None


async def _binding_to_dict(
    registry: Any,
    component_type: str,
    binding: AgentLLMBindingRecord | None,
) -> JSONDict:
    if binding is None:
        return {
            "component_type": component_type,
            "account_id": None,
            "model_id": None,
            "thinking_effort": None,
            "resolved": {},
        }
    resolved = await _build_resolved_metadata(registry, binding.account_id, binding.model_id)
    return {
        "component_type": component_type,
        "account_id": binding.account_id,
        "model_id": binding.model_id,
        "thinking_effort": binding.thinking_effort,
        "resolved": resolved,
    }


@router.get("/memory/components")
async def list_memory_components(
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    bindings = await state.llm_registry.list_bindings()
    binding_map = {b.agent_type: b for b in bindings}

    components: list[JSONDict] = []
    for component_type, meta in MEMORY_COMPONENT_META.items():
        binding = binding_map.get(component_type)
        if binding is None:
            binding_payload: JSONDict | None = None
        else:
            resolved = await _build_resolved_metadata(
                state.llm_registry, binding.account_id, binding.model_id
            )
            binding_payload = {
                "account_id": binding.account_id,
                "model_id": binding.model_id,
                "thinking_effort": binding.thinking_effort,
                "resolved": resolved,
            }
        components.append(
            {
                "component_type": component_type,
                "display_name": meta["display_name"],
                "description": meta["description"],
                "binding": binding_payload,
            }
        )
    return {"components": components}


@router.get("/memory/components/{component_type}/llm-binding")
async def get_component_binding(
    component_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if component_type not in MEMORY_COMPONENT_TYPES:
        raise HTTPException(status_code=404, detail="Memory component not found")

    binding = await state.llm_registry.get_binding(component_type)
    return await _binding_to_dict(state.llm_registry, component_type, binding)


@router.put("/memory/components/{component_type}/llm-binding")
async def set_component_binding(
    component_type: str,
    body: ComponentBindingUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.llm.registry import _coerce_thinking

    if component_type not in MEMORY_COMPONENT_TYPES:
        raise HTTPException(status_code=404, detail="Memory component not found")

    if body.account_id is None or body.model_id is None:
        if body.account_id is not None or body.model_id is not None:
            raise HTTPException(
                status_code=400,
                detail="account_id and model_id must both be provided or both be null",
            )
        await state.llm_registry.clear_binding(component_type)
        return await _binding_to_dict(state.llm_registry, component_type, None)

    account = await state.llm_registry.get_account(body.account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="Account not found")

    try:
        model_spec = await state.llm_registry.get_model_spec(account, body.model_id)
    except (KeyError, RuntimeError):
        raise HTTPException(status_code=400, detail=f"Model {body.model_id!r} not found")

    existing = await state.llm_registry.get_binding(component_type)
    binding_changed = existing is None or (
        existing.account_id != body.account_id or existing.model_id != body.model_id
    )

    effort: str | None = None if binding_changed else body.thinking_effort
    effort = _coerce_thinking(effort, model_spec.thinking_capability)

    binding = await state.llm_registry.set_binding(
        component_type,
        body.account_id,
        body.model_id,
        thinking_effort=effort,
    )
    return await _binding_to_dict(state.llm_registry, component_type, binding)


@router.delete("/memory/components/{component_type}/llm-binding", status_code=204)
async def clear_component_binding(
    component_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    if component_type not in MEMORY_COMPONENT_TYPES:
        raise HTTPException(status_code=404, detail="Memory component not found")

    await state.llm_registry.clear_binding(component_type)
    return Response(status_code=204)
