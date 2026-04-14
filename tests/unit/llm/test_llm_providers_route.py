from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from sebastian.gateway.routes.llm_providers import (
    LLMProviderUpdate,
    _record_to_dict,
    update_llm_provider,
)
from sebastian.llm.crypto import encrypt


def _make_record(**overrides: Any) -> SimpleNamespace:
    now = _dt.datetime.now()
    base = {
        "id": "p1",
        "name": "anthropic",
        "provider_type": "anthropic",
        "base_url": "https://api.example.com/v1",
        "api_key_enc": encrypt("sk-test"),
        "model": "claude-sonnet-4-6",
        "thinking_format": None,
        "thinking_capability": "effort",
        "is_default": True,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_put_provider_clears_thinking_capability_with_explicit_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式传 thinking_capability=None 时应调用 registry 把字段清空。"""
    captured: dict[str, Any] = {}

    async def fake_update(pid: str, **kwargs: Any) -> SimpleNamespace:
        captured["pid"] = pid
        captured["kwargs"] = kwargs
        return _make_record(thinking_capability=None)

    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", SimpleNamespace(update=fake_update), raising=False)

    body = LLMProviderUpdate(
        thinking_capability=None,
        base_url="https://api.example.com/v1",
    )
    result = await update_llm_provider("p1", body=body, _auth={})

    assert "thinking_capability" in captured["kwargs"]
    assert captured["kwargs"]["thinking_capability"] is None
    assert result["thinking_capability"] is None


@pytest.mark.asyncio
async def test_put_provider_omitted_field_not_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未提供的字段不应出现在 registry.update 的 kwargs 里。"""
    captured: dict[str, Any] = {}

    async def fake_update(pid: str, **kwargs: Any) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        return _make_record(name=kwargs.get("name", "anthropic"))

    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", SimpleNamespace(update=fake_update), raising=False)

    body = LLMProviderUpdate(name="updated")
    with pytest.raises(HTTPException) as exc_info:
        await update_llm_provider("p1", body=body, _auth={})

    assert exc_info.value.status_code == 400
    assert "base_url" in exc_info.value.detail


@pytest.mark.asyncio
async def test_put_provider_rejects_base_url_with_explicit_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式传 base_url=None 时应返回 400。"""

    async def fake_update(pid: str, **kwargs: Any) -> SimpleNamespace:
        raise AssertionError("registry.update 不应被调用")

    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", SimpleNamespace(update=fake_update), raising=False)

    body = LLMProviderUpdate(base_url=None)
    with pytest.raises(HTTPException) as exc_info:
        await update_llm_provider("p1", body=body, _auth={})

    assert exc_info.value.status_code == 400
    assert "base_url" in exc_info.value.detail


@pytest.mark.asyncio
async def test_put_provider_api_key_encrypted_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api_key 提供时应以 api_key_enc 形式传给 registry.update。"""
    captured: dict[str, Any] = {}

    async def fake_update(pid: str, **kwargs: Any) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        return _make_record()

    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", SimpleNamespace(update=fake_update), raising=False)

    body = LLMProviderUpdate(api_key="sk-new-key", base_url="https://api.example.com/v1")
    await update_llm_provider("p1", body=body, _auth={})

    assert "api_key_enc" in captured["kwargs"]
    assert captured["kwargs"]["api_key_enc"] != "sk-new-key"  # encrypted
    assert "api_key" not in captured["kwargs"]


@pytest.mark.asyncio
async def test_put_provider_updates_name_without_touching_omitted_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_update(pid: str, **kwargs: Any) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        return _make_record(name=kwargs.get("name", "anthropic"), base_url=kwargs["base_url"])

    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", SimpleNamespace(update=fake_update), raising=False)

    body = LLMProviderUpdate(name="updated", base_url="https://api.example.com/v1")
    await update_llm_provider("p1", body=body, _auth={})

    assert "name" in captured["kwargs"]
    assert captured["kwargs"]["name"] == "updated"
    assert captured["kwargs"]["base_url"] == "https://api.example.com/v1"
    assert "thinking_capability" not in captured["kwargs"]
    assert "thinking_format" not in captured["kwargs"]
    assert "is_default" not in captured["kwargs"]
    assert "model" not in captured["kwargs"]
    assert "api_key_enc" not in captured["kwargs"]


@pytest.mark.parametrize("field", ["name", "api_key", "model", "base_url", "is_default"])
@pytest.mark.asyncio
async def test_put_provider_rejects_null_on_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    """nullable=False 的列显式传 null 应返回 400，而不是让后端崩溃。"""

    async def fake_update(pid: str, **kwargs: Any) -> SimpleNamespace:
        raise AssertionError("registry.update 不应被调用")

    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", SimpleNamespace(update=fake_update), raising=False)

    body = LLMProviderUpdate(
        **{
            field: None,
            **({"base_url": "https://api.example.com/v1"} if field != "base_url" else {}),
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        await update_llm_provider("p1", body=body, _auth={})

    assert exc_info.value.status_code == 400
    assert field in exc_info.value.detail


def test_record_to_dict_includes_decrypted_api_key() -> None:
    record = _make_record(api_key_enc=encrypt("secret-key"))
    result = _record_to_dict(record)

    assert result["api_key"] == "secret-key"
