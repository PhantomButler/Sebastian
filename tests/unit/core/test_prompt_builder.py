from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.types import ToolResult
from sebastian.permissions.types import ALL_TOOLS, AllToolsSentinel


def _make_registry_with_tools() -> CapabilityRegistry:
    reg = CapabilityRegistry()

    async def fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="ok")

    reg.register_mcp_tool(
        "file_read",
        {"name": "file_read", "description": "Read a file", "input_schema": {}},
        fn,
    )
    return reg


def _build_prompt(
    tmp_path: Path,
    allowed_tools: list[str] | AllToolsSentinel | None,
) -> str:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am your butler."

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("sebastian.core.base_agent.settings") as mock_settings:
        mock_settings.sebastian_model = "claude-opus-4-6"
        mock_settings.llm_max_tokens = 16000
        mock_settings.workspace_dir = tmp_path / "workspace"
        agent = MyAgent(reg, store, allowed_tools=allowed_tools)

    return agent.system_prompt


@pytest.mark.asyncio
async def test_persona_section_appears_in_system_prompt(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "Hello, I serve you."

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert "Hello, I serve you." in agent.system_prompt


@pytest.mark.asyncio
async def test_system_prompt_includes_skill_management_bootstrap(tmp_path: Path) -> None:
    system_prompt = _build_prompt(tmp_path, ["Bash"])

    assert "## Skill Management" in system_prompt
    assert "When Bash is available" in system_prompt
    assert "search local Skills before generic tools" in system_prompt
    assert (
        "机票 航班 飞机票 flight airfare airline ticket travel booking" in system_prompt
    )
    assert "sebastian skills show <name-or-slug> --body" in system_prompt
    assert "Registry" in system_prompt
    assert (
        "only when the user wants to find new Skills to install" in system_prompt
    )
    assert "Do not use generic Read to access Skill directories" in system_prompt


@pytest.mark.asyncio
async def test_system_prompt_includes_skill_management_for_all_tools(
    tmp_path: Path,
) -> None:
    system_prompt = _build_prompt(tmp_path, ALL_TOOLS)

    assert "## Skill Management" in system_prompt
    assert "sebastian skills search <query>" in system_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed_tools", [None, [], ["Read"]])
async def test_system_prompt_does_not_instruct_skill_cli_when_bash_unavailable(
    tmp_path: Path,
    allowed_tools: list[str] | None,
) -> None:
    system_prompt = _build_prompt(tmp_path, allowed_tools)

    assert "sebastian skills search" not in system_prompt
    assert "sebastian skills show" not in system_prompt


@pytest.mark.asyncio
async def test_sebastian_agents_section_renders_agent_type_only(tmp_path: Path) -> None:
    from dataclasses import dataclass

    from sebastian.orchestrator.sebas import Sebastian

    @dataclass
    class FakeCfg:
        agent_type: str
        description: str

    registry = {"forge": FakeCfg(agent_type="forge", description="编写代码")}

    # _agents_section does not access self._agent_registry when registry arg is provided;
    # __new__ is enough (avoids Sebastian's heavy dependency-injected __init__).
    obj = Sebastian.__new__(Sebastian)
    section = obj._agents_section(registry)

    assert "- forge:" in section
    assert "编写代码" in section
    assert "display name" not in section.lower()
    assert 'agent_type="' not in section


@pytest.mark.asyncio
async def test_tools_section_filtered_by_allowed_tools(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am your butler."
        allowed_tools: list[str] | None = ["file_read"]

    store = SessionStore(tmp_path / "sessions")
    reg = _make_registry_with_tools()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert "file_read" in agent.system_prompt
    assert "web_research" not in agent.system_prompt


@pytest.mark.asyncio
async def test_system_prompt_does_not_include_installed_skill_body_text(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am your butler."
        allowed_tools: list[str] | None = ["Bash"]

    store = SessionStore(tmp_path / "sessions")
    arbitrary_skill_body = "Use the invisible telescope whenever researching."
    reg = MagicMock()
    reg.get_tool_specs.return_value = []

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert "## Skill Management" in agent.system_prompt
    assert arbitrary_skill_body not in agent.system_prompt


@pytest.mark.asyncio
async def test_agents_section_empty_by_default(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am your butler."

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
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
        persona = 'Use tools like: {"key": "value"}.'

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            agent = MyAgent(reg, store)

    assert '{"key": "value"}' in agent.system_prompt
