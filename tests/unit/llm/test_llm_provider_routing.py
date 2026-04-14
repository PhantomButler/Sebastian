from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_provider_falls_back_to_default_when_no_manifest_llm() -> None:
    """agent_type 的 manifest 无 [llm] 块时，get_provider 返回 default provider。"""
    from sebastian.llm.registry import LLMProviderRegistry

    registry = LLMProviderRegistry(MagicMock())
    mock_provider = MagicMock()
    registry.get_default_with_model = AsyncMock(
        return_value=(mock_provider, "claude-3-5-sonnet-20241022")
    )

    with patch("sebastian.llm.registry._read_manifest_llm", return_value=None):
        provider, model = await registry.get_provider("code")

    assert provider is mock_provider
    assert model == "claude-3-5-sonnet-20241022"


@pytest.mark.asyncio
async def test_get_provider_uses_manifest_llm_when_present() -> None:
    """manifest [llm] 有 provider_type + model 时，get_provider 用对应的 DB 记录。"""
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.models import LLMProviderRecord

    registry = LLMProviderRegistry(MagicMock())
    manifest_llm = {"provider_type": "openai", "model": "gpt-4o"}
    mock_record = MagicMock(spec=LLMProviderRecord)
    mock_record.provider_type = "openai"

    mock_provider = MagicMock()
    registry._instantiate = MagicMock(return_value=mock_provider)
    registry._get_by_type = AsyncMock(return_value=mock_record)

    with patch("sebastian.llm.registry._read_manifest_llm", return_value=manifest_llm):
        provider, model = await registry.get_provider("some_agent")

    assert provider is mock_provider
    assert model == "gpt-4o"
    registry._get_by_type.assert_awaited_once_with("openai")


@pytest.mark.asyncio
async def test_get_provider_without_agent_type_returns_default() -> None:
    """agent_type=None 时，get_provider 直接返回 default。"""
    from sebastian.llm.registry import LLMProviderRegistry

    registry = LLMProviderRegistry(MagicMock())
    mock_provider = MagicMock()
    registry.get_default_with_model = AsyncMock(return_value=(mock_provider, "default-model"))

    provider, model = await registry.get_provider(None)

    assert provider is mock_provider
    assert model == "default-model"


@pytest.mark.asyncio
async def test_get_provider_falls_back_when_no_db_record_for_type() -> None:
    """manifest 指定 provider_type 但 DB 无对应记录时，fallback 到 default。"""
    from sebastian.llm.registry import LLMProviderRegistry

    registry = LLMProviderRegistry(MagicMock())
    manifest_llm = {"provider_type": "openai", "model": "gpt-4o"}
    mock_provider = MagicMock()
    registry.get_default_with_model = AsyncMock(return_value=(mock_provider, "default-model"))
    registry._get_by_type = AsyncMock(return_value=None)

    with patch("sebastian.llm.registry._read_manifest_llm", return_value=manifest_llm):
        provider, model = await registry.get_provider("some_agent")

    assert provider is mock_provider  # fallback to default
    assert model == "default-model"


@pytest.mark.asyncio
async def test_base_agent_run_streaming_uses_injected_llm_registry() -> None:
    """run_streaming 通过注入的 llm_registry 获取 provider，不 import gateway.state。"""
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import (
        TextBlockStart,
        TextBlockStop,
        TextDelta,
    )
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.session_store import SessionStore
    from tests.unit.core.test_agent_loop import MockLLMProvider

    # ProviderCallEnd is needed for the mock to complete
    try:
        from sebastian.core.stream_events import ProviderCallEnd

        events = [
            TextBlockStart(block_id="b0"),
            TextDelta(block_id="b0", delta="hi"),
            TextBlockStop(block_id="b0", text="hi"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    except ImportError:
        events = [
            TextBlockStart(block_id="b0"),
            TextDelta(block_id="b0", delta="hi"),
            TextBlockStop(block_id="b0", text="hi"),
        ]

    mock_provider = MockLLMProvider(events)
    mock_registry = MagicMock(spec=LLMProviderRegistry)
    mock_registry.get_provider = AsyncMock(return_value=(mock_provider, "test-model"))

    class TestAgent(BaseAgent):
        name = "code"
        system_prompt = "test"

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())

    from sebastian.memory.episodic_memory import EpisodicMemory

    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        gate=MagicMock(),
        session_store=session_store,
        llm_registry=mock_registry,
    )
    agent._episodic = episodic_mock

    result = await agent.run("hello", session_id="sess-h9")
    assert result == "hi"
    mock_registry.get_provider.assert_awaited_once_with("code")


@pytest.mark.asyncio
async def test_registry_passes_thinking_capability_to_provider() -> None:
    from unittest.mock import MagicMock

    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="test",
        provider_type="anthropic",
        api_key_enc="",
        model="claude-opus-4-6",
        thinking_capability="adaptive",
    )
    registry = LLMProviderRegistry(db_factory=MagicMock())

    import sebastian.llm.crypto as crypto

    original_decrypt = crypto.decrypt
    crypto.decrypt = lambda _enc: "fake-key"
    try:
        provider = registry._instantiate(record)
    finally:
        crypto.decrypt = original_decrypt

    from sebastian.llm.anthropic import AnthropicProvider

    assert isinstance(provider, AnthropicProvider)
    assert provider._capability == "adaptive"


@pytest.mark.asyncio
async def test_registry_passes_thinking_capability_to_openai_provider() -> None:
    from unittest.mock import MagicMock

    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="test",
        provider_type="openai",
        api_key_enc="",
        model="o3",
        thinking_format=None,
        thinking_capability="effort",
    )
    registry = LLMProviderRegistry(db_factory=MagicMock())

    import sebastian.llm.crypto as crypto

    original_decrypt = crypto.decrypt
    crypto.decrypt = lambda _enc: "fake-key"
    try:
        provider = registry._instantiate(record)
    finally:
        crypto.decrypt = original_decrypt

    from sebastian.llm.openai_compat import OpenAICompatProvider

    assert isinstance(provider, OpenAICompatProvider)
    assert provider._capability == "effort"
