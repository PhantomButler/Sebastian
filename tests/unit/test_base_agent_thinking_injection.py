"""base_agent 从 ResolvedProvider 派生 thinking_effort 的注入测试。

验证 base_agent 内部从 llm_registry.get_provider() 返回的 ResolvedProvider
直接读取 thinking_effort / thinking_adaptive，而不是依赖方法入参透传。

三个场景：
- effort 模式（adaptive=False, effort="high"）→ chat_stream 收到 thinking_effort="high"
- adaptive 模式（adaptive=True, effort="high"）→ chat_stream 收到 thinking_effort="adaptive"
- off 模式（adaptive=False, effort=None）→ chat_stream 收到 thinking_effort=None
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.base_agent import BaseAgent
from sebastian.core.types import Session
from sebastian.llm.registry import ResolvedProvider
from sebastian.store.session_store import SessionStore


class _TestAgent(BaseAgent):
    name = "test_agent"


async def _make_agent(tmp_path, resolved_provider: ResolvedProvider) -> tuple[_TestAgent, dict]:
    """构造一个注入了 llm_registry 的 TestAgent，返回 (agent, captured_kwargs)。"""
    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(id="inject-session", agent_type="test_agent", title="Injection test")
    )

    registry = AsyncMock()
    registry.get_provider = AsyncMock(return_value=resolved_provider)

    agent = _TestAgent(MagicMock(), store, llm_registry=registry)

    captured: dict = {}

    async def fake_stream(*args, **kwargs):
        captured.update(kwargs)
        from sebastian.core.stream_events import TurnDone

        yield TurnDone(full_text="ok")

    agent._loop.stream = fake_stream  # type: ignore[attr-defined]
    # 标记 provider 未注入，让 run_streaming 走 registry 分支
    agent._provider_injected = False

    return agent, captured


def _make_resolved(
    thinking_effort: str | None,
    thinking_adaptive: bool,
) -> ResolvedProvider:
    provider = MagicMock()
    provider.message_format = "anthropic"
    return ResolvedProvider(
        provider=provider,
        model="claude-opus-4-6",
        thinking_effort=thinking_effort,
        thinking_adaptive=thinking_adaptive,
        capability="adaptive" if thinking_adaptive else "effort",
    )


@pytest.mark.asyncio
async def test_base_agent_derives_effort_from_resolved_provider(tmp_path) -> None:
    """effort 模式：ResolvedProvider.thinking_effort="high", adaptive=False
    → loop.stream 收到 thinking_effort="high"。
    """
    resolved = _make_resolved(thinking_effort="high", thinking_adaptive=False)
    agent, captured = await _make_agent(tmp_path, resolved)

    result = await agent.run_streaming("hello", "inject-session")

    assert result == "ok"
    assert captured.get("thinking_effort") == "high"


@pytest.mark.asyncio
async def test_base_agent_derives_adaptive_sentinel_from_resolved_provider(tmp_path) -> None:
    """adaptive 模式：ResolvedProvider.thinking_adaptive=True, effort="high"
    → loop.stream 收到 thinking_effort="adaptive"（sentinel 字符串）。
    """
    resolved = _make_resolved(thinking_effort="high", thinking_adaptive=True)
    agent, captured = await _make_agent(tmp_path, resolved)

    result = await agent.run_streaming("hello", "inject-session")

    assert result == "ok"
    assert captured.get("thinking_effort") == "adaptive"


@pytest.mark.asyncio
async def test_base_agent_derives_none_when_thinking_off(tmp_path) -> None:
    """off 模式：ResolvedProvider.thinking_effort=None, adaptive=False
    → loop.stream 收到 thinking_effort=None。
    """
    resolved = _make_resolved(thinking_effort=None, thinking_adaptive=False)
    agent, captured = await _make_agent(tmp_path, resolved)

    result = await agent.run_streaming("hello", "inject-session")

    assert result == "ok"
    assert captured.get("thinking_effort") is None
