from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["llm-providers"])

AuthPayload = dict[str, Any]


class LLMProviderCreate(BaseModel):
    name: str
    provider_type: str  # "anthropic" | "openai"
    api_key: str
    model: str
    base_url: str | None = None
    thinking_format: str | None = None  # None | "reasoning_content" | "think_tags"
    thinking_capability: str | None = None
    is_default: bool = False


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    thinking_format: str | None = None
    thinking_capability: str | None = None
    is_default: bool | None = None


def _record_to_dict(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "provider_type": record.provider_type,
        "base_url": record.base_url,
        "model": record.model,
        "thinking_format": record.thinking_format,
        "thinking_capability": record.thinking_capability,
        "is_default": record.is_default,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


@router.get("/llm-providers")
async def list_llm_providers(
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state

    records = await state.llm_registry.list_all()
    return {"providers": [_record_to_dict(r) for r in records]}


@router.post("/llm-providers", status_code=201)
async def create_llm_provider(
    body: LLMProviderCreate,
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state
    from sebastian.llm.crypto import encrypt
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name=body.name,
        provider_type=body.provider_type,
        api_key_enc=encrypt(body.api_key),
        model=body.model,
        base_url=body.base_url,
        thinking_format=body.thinking_format,
        thinking_capability=body.thinking_capability,
        is_default=body.is_default,
    )
    await state.llm_registry.create(record)
    return _record_to_dict(record)


@router.put("/llm-providers/{provider_id}")
async def update_llm_provider(
    provider_id: str,
    body: LLMProviderUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state
    from sebastian.llm.crypto import encrypt

    data = body.model_dump(exclude_unset=True)
    updates: dict[str, Any] = {}
    if "name" in data:
        updates["name"] = data["name"]
    if "api_key" in data:
        updates["api_key_enc"] = encrypt(data["api_key"])
    if "model" in data:
        updates["model"] = data["model"]
    if "base_url" in data:
        updates["base_url"] = data["base_url"]
    if "thinking_format" in data:
        updates["thinking_format"] = data["thinking_format"]
    if "thinking_capability" in data:
        updates["thinking_capability"] = data["thinking_capability"]
    if "is_default" in data:
        updates["is_default"] = data["is_default"]

    record = await state.llm_registry.update(provider_id, **updates)
    if record is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _record_to_dict(record)


@router.delete("/llm-providers/{provider_id}", status_code=204)
async def delete_llm_provider(
    provider_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> None:
    import sebastian.gateway.state as state

    deleted = await state.llm_registry.delete(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider not found")
