from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace
from typing import Any

import pytest

from sebastian.gateway.routes.llm_providers import (
    LLMProviderUpdate,
    update_llm_provider,
)


def _make_record(**overrides: Any) -> SimpleNamespace:
    now = _dt.datetime.now()
    base = {
        "id": "p1",
        "name": "anthropic",
        "provider_type": "anthropic",
        "base_url": None,
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

    monkeypatch.setattr(
        state, "llm_registry", SimpleNamespace(update=fake_update), raising=False
    )

    body = LLMProviderUpdate(thinking_capability=None)
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

    monkeypatch.setattr(
        state, "llm_registry", SimpleNamespace(update=fake_update), raising=False
    )

    body = LLMProviderUpdate(name="updated")
    await update_llm_provider("p1", body=body, _auth={})

    assert "name" in captured["kwargs"]
    assert captured["kwargs"]["name"] == "updated"
    assert "thinking_capability" not in captured["kwargs"]
    assert "base_url" not in captured["kwargs"]
    assert "thinking_format" not in captured["kwargs"]
    assert "is_default" not in captured["kwargs"]
    assert "model" not in captured["kwargs"]
    assert "api_key_enc" not in captured["kwargs"]


@pytest.mark.asyncio
async def test_put_provider_clears_base_url_with_explicit_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式传 base_url=None 时应调用 registry 把 base_url 清空。"""
    captured: dict[str, Any] = {}

    async def fake_update(pid: str, **kwargs: Any) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        return _make_record(base_url=None)

    import sebastian.gateway.state as state

    monkeypatch.setattr(
        state, "llm_registry", SimpleNamespace(update=fake_update), raising=False
    )

    body = LLMProviderUpdate(base_url=None)
    await update_llm_provider("p1", body=body, _auth={})

    assert "base_url" in captured["kwargs"]
    assert captured["kwargs"]["base_url"] is None


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

    monkeypatch.setattr(
        state, "llm_registry", SimpleNamespace(update=fake_update), raising=False
    )

    body = LLMProviderUpdate(api_key="sk-new-key")
    await update_llm_provider("p1", body=body, _auth={})

    assert "api_key_enc" in captured["kwargs"]
    assert captured["kwargs"]["api_key_enc"] != "sk-new-key"  # encrypted
    assert "api_key" not in captured["kwargs"]
