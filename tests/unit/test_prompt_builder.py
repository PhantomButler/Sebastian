from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.types import ToolResult


def _make_registry_with_tools_and_skills() -> CapabilityRegistry:
    reg = CapabilityRegistry()

    async def fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="ok")

    reg.register_mcp_tool(
        "file_read",
        {"name": "file_read", "description": "Read a file", "input_schema": {}},
        fn,
    )
    reg.register_skill_specs([
        {
            "name": "web_research",
            "description": "Research the web",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
    ])
    return reg


@pytest.mark.asyncio
async def test_persona_section_injects_owner_name(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "Hello {owner_name}, I serve you."

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert "Eric" in agent.system_prompt
    assert "{owner_name}" not in agent.system_prompt


@pytest.mark.asyncio
async def test_tools_section_filtered_by_allowed_tools(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am {owner_name}."
        allowed_tools: list[str] | None = ["file_read"]
        allowed_skills: list[str] | None = []

    store = SessionStore(tmp_path / "sessions")
    reg = _make_registry_with_tools_and_skills()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert "file_read" in agent.system_prompt
    assert "web_research" not in agent.system_prompt


@pytest.mark.asyncio
async def test_skills_section_filtered_by_allowed_skills(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am {owner_name}."
        allowed_tools: list[str] | None = []
        allowed_skills: list[str] | None = ["web_research"]

    store = SessionStore(tmp_path / "sessions")
    reg = _make_registry_with_tools_and_skills()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert "web_research" in agent.system_prompt
    assert "file_read" not in agent.system_prompt


@pytest.mark.asyncio
async def test_agents_section_empty_by_default(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am {owner_name}."

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert "Sub-Agent" not in agent.system_prompt


@pytest.mark.asyncio
async def test_persona_with_extra_braces_does_not_crash(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "Hello {owner_name}. Use tools like: {\"key\": \"value\"}."

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert "Eric" in agent.system_prompt
    assert "{owner_name}" not in agent.system_prompt
