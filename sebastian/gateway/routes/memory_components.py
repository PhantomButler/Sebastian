# sebastian/gateway/routes/memory_components.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth
from sebastian.memory.provider_bindings import MEMORY_COMPONENT_META, MEMORY_COMPONENT_TYPES

router = APIRouter(tags=["memory"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


class ComponentBindingUpdate(BaseModel):
    provider_id: str | None = None
    thinking_effort: str | None = None


def _binding_to_dict(component_type: str, binding: Any | None) -> JSONDict:
    return {
        "component_type": component_type,
        "provider_id": binding.provider_id if binding is not None else None,
        "thinking_effort": binding.thinking_effort if binding is not None else None,
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
        components.append(
            {
                "component_type": component_type,
                "display_name": meta["display_name"],
                "description": meta["description"],
                "binding": _binding_to_dict(component_type, binding)
                if binding is not None
                else None,
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
    return _binding_to_dict(component_type, binding)


@router.put("/memory/components/{component_type}/llm-binding")
async def set_component_binding(
    component_type: str,
    body: ComponentBindingUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if component_type not in MEMORY_COMPONENT_TYPES:
        raise HTTPException(status_code=404, detail="Memory component not found")

    record = None
    if body.provider_id is not None:
        record = await state.llm_registry.get_record(body.provider_id)
        if record is None:
            raise HTTPException(status_code=400, detail="Provider not found")

    existing = await state.llm_registry.get_binding(component_type)
    provider_changed = existing is None or existing.provider_id != body.provider_id

    effort: str | None = None if provider_changed else body.thinking_effort
    if record is not None and record.thinking_capability in ("none", "always_on"):
        effort = None

    binding = await state.llm_registry.set_binding(
        component_type,
        body.provider_id,
        thinking_effort=effort,
    )
    return _binding_to_dict(component_type, binding)


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
