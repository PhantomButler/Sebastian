from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from sebastian.gateway.auth import require_auth
from sebastian.llm.catalog import load_builtin_catalog

router = APIRouter(tags=["llm-accounts"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Pydantic DTOs
# ---------------------------------------------------------------------------


class LLMAccountCreate(BaseModel):
    name: str
    catalog_provider_id: str
    api_key: str
    provider_type: str | None = None
    base_url_override: str | None = None


class LLMAccountUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    base_url_override: str | None = None


class CustomModelCreate(BaseModel):
    model_id: str
    display_name: str
    context_window_tokens: int
    thinking_capability: str | None = None
    thinking_format: str | None = None


class CustomModelUpdate(BaseModel):
    model_id: str | None = None
    display_name: str | None = None
    context_window_tokens: int | None = None
    thinking_capability: str | None = None
    thinking_format: str | None = None


class DefaultBindingUpdate(BaseModel):
    account_id: str
    model_id: str
    thinking_effort: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _account_to_dict(record: Any) -> JSONDict:
    return {
        "id": record.id,
        "name": record.name,
        "catalog_provider_id": record.catalog_provider_id,
        "provider_type": record.provider_type,
        "has_api_key": bool(record.api_key_enc),
        "base_url_override": record.base_url_override,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _custom_model_to_dict(record: Any) -> JSONDict:
    return {
        "id": record.id,
        "account_id": record.account_id,
        "model_id": record.model_id,
        "display_name": record.display_name,
        "context_window_tokens": record.context_window_tokens,
        "thinking_capability": record.thinking_capability,
        "thinking_format": record.thinking_format,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


async def _build_resolved_metadata(registry: Any, account_id: str, model_id: str) -> JSONDict:
    """Build resolved metadata for a binding response."""
    account = await registry.get_account(account_id)
    if account is None:
        return {}
    try:
        model_spec = await registry.get_model_spec(account, model_id)
    except (KeyError, RuntimeError):
        return {}
    provider_display_name = account.catalog_provider_id
    if account.catalog_provider_id != "custom":
        try:
            catalog = load_builtin_catalog()
            provider_spec = catalog.get_provider(account.catalog_provider_id)
            provider_display_name = provider_spec.display_name
        except KeyError:
            pass
    return {
        "account_name": account.name,
        "provider_display_name": provider_display_name,
        "model_display_name": model_spec.display_name,
        "context_window_tokens": model_spec.context_window_tokens,
        "thinking_capability": model_spec.thinking_capability,
    }


def _validate_base_url(base_url: str) -> str:
    value = base_url.strip()
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or any(ch.isspace() for ch in value)
    ):
        raise HTTPException(
            status_code=400,
            detail="base_url must be an http(s) URL",
        )
    return value


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@router.get("/llm-catalog")
async def get_catalog(
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    catalog = load_builtin_catalog()
    providers: list[JSONDict] = []
    for p in catalog.providers:
        models: list[JSONDict] = []
        for m in p.models:
            models.append(
                {
                    "id": m.id,
                    "display_name": m.display_name,
                    "context_window_tokens": m.context_window_tokens,
                    "thinking_capability": m.thinking_capability,
                    "thinking_format": m.thinking_format,
                }
            )
        providers.append(
            {
                "id": p.id,
                "display_name": p.display_name,
                "provider_type": p.provider_type,
                "base_url": p.base_url,
                "models": models,
            }
        )
    return {"providers": providers}


# ---------------------------------------------------------------------------
# Account CRUD
# ---------------------------------------------------------------------------


@router.get("/llm-accounts")
async def list_accounts(
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    records = await state.llm_registry.list_accounts()
    return {"accounts": [_account_to_dict(r) for r in records]}


@router.post("/llm-accounts", status_code=201)
async def create_account(
    body: LLMAccountCreate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.llm.crypto import encrypt
    from sebastian.store.models import LLMAccountRecord

    # Validate api_key non-empty
    if not body.api_key:
        raise HTTPException(status_code=400, detail="api_key must be non-empty")

    if body.catalog_provider_id == "custom":
        if not body.provider_type:
            raise HTTPException(
                status_code=400,
                detail="provider_type is required for custom providers",
            )
        if not body.base_url_override:
            raise HTTPException(
                status_code=400,
                detail="base_url_override is required for custom providers",
            )
        base_url = _validate_base_url(body.base_url_override)
        provider_type = body.provider_type
    else:
        # Validate catalog_provider_id exists in catalog
        catalog = load_builtin_catalog()
        try:
            provider_spec = catalog.get_provider(body.catalog_provider_id)
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown catalog provider: {body.catalog_provider_id!r}",
            )
        provider_type = provider_spec.provider_type
        base_url = body.base_url_override
        if base_url is not None:
            base_url = _validate_base_url(base_url)

    record = LLMAccountRecord(
        name=body.name,
        catalog_provider_id=body.catalog_provider_id,
        provider_type=provider_type,
        api_key_enc=encrypt(body.api_key),
        base_url_override=base_url,
    )
    await state.llm_registry.create_account(record)
    return _account_to_dict(record)


@router.put("/llm-accounts/{account_id}")
async def update_account(
    account_id: str,
    body: LLMAccountUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    data = body.model_dump(exclude_unset=True)

    # api_key must be non-empty if present (not null, not empty)
    if "api_key" in data and (data["api_key"] is None or data["api_key"] == ""):
        raise HTTPException(status_code=400, detail="api_key must be non-empty")

    updates: dict[str, Any] = {}
    if "name" in data:
        updates["name"] = data["name"]
    if "api_key" in data:
        updates["api_key"] = data["api_key"]
    if "base_url_override" in data:
        val = data["base_url_override"]
        if val is not None:
            updates["base_url_override"] = _validate_base_url(val)
        else:
            updates["base_url_override"] = None

    record = await state.llm_registry.update_account(account_id, **updates)
    if record is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return _account_to_dict(record)


@router.delete("/llm-accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> None:
    import sebastian.gateway.state as state
    from sebastian.store.models import AgentLLMBindingRecord

    # Check if any bindings reference this account
    async with state.db_factory() as session:
        result = await session.execute(
            select(AgentLLMBindingRecord).where(
                AgentLLMBindingRecord.account_id == account_id
            )
        )
        bound = list(result.scalars().all())

    if bound:
        agent_types = [b.agent_type for b in bound]
        raise HTTPException(
            status_code=409,
            detail=f"Account is bound to agents: {agent_types}",
        )

    deleted = await state.llm_registry.delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")


# ---------------------------------------------------------------------------
# Custom Model CRUD
# ---------------------------------------------------------------------------


@router.get("/llm-accounts/{account_id}/models")
async def list_custom_models(
    account_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.store.models import LLMCustomModelRecord

    account = await state.llm_registry.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    async with state.db_factory() as session:
        result = await session.execute(
            select(LLMCustomModelRecord)
            .where(LLMCustomModelRecord.account_id == account_id)
            .order_by(LLMCustomModelRecord.created_at)
        )
        records = list(result.scalars().all())

    return {"models": [_custom_model_to_dict(r) for r in records]}


@router.post("/llm-accounts/{account_id}/models", status_code=201)
async def create_custom_model(
    account_id: str,
    body: CustomModelCreate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.store.models import LLMCustomModelRecord

    account = await state.llm_registry.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if account.catalog_provider_id != "custom":
        raise HTTPException(
            status_code=400,
            detail="Custom models can only be added to custom accounts",
        )

    if body.context_window_tokens < 1000 or body.context_window_tokens > 10_000_000:
        raise HTTPException(
            status_code=400,
            detail="context_window_tokens must be between 1,000 and 10,000,000",
        )

    # Enforce unique (account_id, model_id)
    async with state.db_factory() as session:
        existing = await session.execute(
            select(LLMCustomModelRecord).where(
                LLMCustomModelRecord.account_id == account_id,
                LLMCustomModelRecord.model_id == body.model_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Model {body.model_id!r} already exists for this account",
            )

        record = LLMCustomModelRecord(
            account_id=account_id,
            model_id=body.model_id,
            display_name=body.display_name,
            context_window_tokens=body.context_window_tokens,
            thinking_capability=body.thinking_capability,
            thinking_format=body.thinking_format,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

    return _custom_model_to_dict(record)


@router.put("/llm-accounts/{account_id}/models/{model_record_id}")
async def update_custom_model(
    account_id: str,
    model_record_id: str,
    body: CustomModelUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.store.models import AgentLLMBindingRecord, LLMCustomModelRecord

    async with state.db_factory() as session:
        result = await session.execute(
            select(LLMCustomModelRecord).where(
                LLMCustomModelRecord.id == model_record_id,
                LLMCustomModelRecord.account_id == account_id,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="Custom model not found")

        data = body.model_dump(exclude_unset=True)

        if "context_window_tokens" in data:
            cwt = data["context_window_tokens"]
            if cwt is not None and (cwt < 1000 or cwt > 10_000_000):
                raise HTTPException(
                    status_code=400,
                    detail="context_window_tokens must be between 1,000 and 10,000,000",
                )

        # If model_id changes, check bindings
        if "model_id" in data and data["model_id"] != record.model_id:
            bind_result = await session.execute(
                select(AgentLLMBindingRecord).where(
                    AgentLLMBindingRecord.account_id == account_id,
                    AgentLLMBindingRecord.model_id == record.model_id,
                )
            )
            if bind_result.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot change model_id: model is referenced by bindings",
                )

        for key, value in data.items():
            setattr(record, key, value)
        await session.commit()
        await session.refresh(record)

    return _custom_model_to_dict(record)


@router.delete("/llm-accounts/{account_id}/models/{model_record_id}", status_code=204)
async def delete_custom_model(
    account_id: str,
    model_record_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> None:
    import sebastian.gateway.state as state
    from sebastian.store.models import AgentLLMBindingRecord, LLMCustomModelRecord

    async with state.db_factory() as session:
        result = await session.execute(
            select(LLMCustomModelRecord).where(
                LLMCustomModelRecord.id == model_record_id,
                LLMCustomModelRecord.account_id == account_id,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="Custom model not found")

        # Check bindings by (account_id, model_id)
        bind_result = await session.execute(
            select(AgentLLMBindingRecord).where(
                AgentLLMBindingRecord.account_id == account_id,
                AgentLLMBindingRecord.model_id == record.model_id,
            )
        )
        if bind_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete: model is referenced by bindings",
            )

        await session.delete(record)
        await session.commit()


# ---------------------------------------------------------------------------
# Default Binding
# ---------------------------------------------------------------------------


@router.get("/llm-bindings/default")
async def get_default_binding(
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.llm.registry import DEFAULT_BINDING_AGENT_TYPE

    binding = await state.llm_registry.get_binding(DEFAULT_BINDING_AGENT_TYPE)
    if binding is None:
        return {
            "agent_type": DEFAULT_BINDING_AGENT_TYPE,
            "account_id": None,
            "model_id": None,
            "thinking_effort": None,
            "resolved": {},
        }
    resolved = await _build_resolved_metadata(
        state.llm_registry, binding.account_id, binding.model_id
    )
    return {
        "agent_type": binding.agent_type,
        "account_id": binding.account_id,
        "model_id": binding.model_id,
        "thinking_effort": binding.thinking_effort,
        "resolved": resolved,
    }


@router.put("/llm-bindings/default")
async def set_default_binding(
    body: DefaultBindingUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state
    from sebastian.llm.registry import DEFAULT_BINDING_AGENT_TYPE, _coerce_thinking

    account = await state.llm_registry.get_account(body.account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="Account not found")

    # Validate model exists
    try:
        model_spec = await state.llm_registry.get_model_spec(account, body.model_id)
    except (KeyError, RuntimeError):
        raise HTTPException(status_code=400, detail=f"Model {body.model_id!r} not found")

    effort = _coerce_thinking(body.thinking_effort, model_spec.thinking_capability)

    binding = await state.llm_registry.set_binding(
        DEFAULT_BINDING_AGENT_TYPE,
        body.account_id,
        body.model_id,
        thinking_effort=effort,
    )
    resolved = await _build_resolved_metadata(
        state.llm_registry, binding.account_id, binding.model_id
    )
    return {
        "agent_type": binding.agent_type,
        "account_id": binding.account_id,
        "model_id": binding.model_id,
        "thinking_effort": binding.thinking_effort,
        "resolved": resolved,
    }
