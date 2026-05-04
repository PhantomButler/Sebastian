from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sebastian.capabilities.tools.browser  # noqa: F401
from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.tool import get_tool
from sebastian.core.types import ToolResult
from sebastian.orchestrator.sebas import Sebastian
from sebastian.permissions.gate import PolicyGate
from sebastian.permissions.types import (
    ALL_TOOLS,
    PermissionTier,
    ToolCallContext,
)

BROWSER_TOOLS = {
    "browser_open",
    "browser_observe",
    "browser_act",
    "browser_capture",
    "browser_downloads",
}


@dataclass
class _Metadata:
    url: str
    title: str | None
    opened_by_browser_tool: bool


class _FakeManager:
    def __init__(self, metadata: _Metadata | None = None) -> None:
        self.metadata = metadata
        self.opened: list[str] = []
        self.acted: list[dict[str, Any]] = []
        self.target_metadata_result: dict[str, str] | None = None

    async def open(self, url: str) -> Any:
        self.opened.append(url)
        return MagicMock(ok=True, url="https://example.com/", title=None, error="")

    async def current_page_metadata(self) -> _Metadata | None:
        return self.metadata

    async def act(
        self,
        *,
        action: str,
        target: str | None = None,
        value: str | None = None,
        is_blocked: Any | None = None,
    ) -> dict[str, Any]:
        if is_blocked is not None and is_blocked(self.target_metadata_result):
            raise RuntimeError("blocked")
        self.acted.append({"action": action, "target": target, "value": value})
        return {"action": action, "download": None}

    async def target_metadata(self, target: str) -> dict[str, str]:
        return self.target_metadata_result or {"target": target}


def test_browser_tools_register_metadata() -> None:
    specs = {}
    for name in BROWSER_TOOLS:
        entry = get_tool(name)
        assert entry is not None
        specs[name] = entry[0]

    assert set(specs) == BROWSER_TOOLS
    assert all(spec.display_name for spec in specs.values())
    assert specs["browser_open"].permission_tier == PermissionTier.MODEL_DECIDES
    assert specs["browser_observe"].permission_tier == PermissionTier.MODEL_DECIDES
    assert specs["browser_observe"].review_preflight is not None
    assert specs["browser_act"].permission_tier == PermissionTier.MODEL_DECIDES
    assert specs["browser_capture"].permission_tier == PermissionTier.MODEL_DECIDES
    assert specs["browser_downloads"].permission_tier == PermissionTier.MODEL_DECIDES


def test_browser_tools_visible_only_through_sebastian_allowlist() -> None:
    assert BROWSER_TOOLS <= set(Sebastian.allowed_tools)

    registry = CapabilityRegistry()
    no_tools = {spec["name"] for spec in registry.get_callable_specs(None, None)}
    all_tools = {spec["name"] for spec in registry.get_callable_specs(ALL_TOOLS, None)}

    assert BROWSER_TOOLS.isdisjoint(no_tools)
    assert BROWSER_TOOLS <= all_tools


def test_custom_extension_agent_without_allowed_tools_gets_no_browser_tools(
    tmp_path: Path,
) -> None:
    from sebastian.agents._loader import load_agents

    agent_dir = tmp_path / "browserless"
    agent_dir.mkdir()
    (agent_dir / "manifest.toml").write_text(
        '[agent]\nclass_name = "BrowserlessAgent"\ndescription = "no browser"\n',
        encoding="utf-8",
    )
    (agent_dir / "__init__.py").write_text("class BrowserlessAgent: pass\n", encoding="utf-8")

    config = next(c for c in load_agents(extra_dirs=[tmp_path]) if c.agent_type == "browserless")

    assert isinstance(config.allowed_tools, list)
    assert BROWSER_TOOLS.isdisjoint(set(config.allowed_tools))


def test_builtin_sub_agent_manifests_do_not_declare_browser_tools() -> None:
    agents_dir = Path("sebastian/agents")
    for manifest in agents_dir.glob("*/manifest.toml"):
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        allowed = set(data.get("agent", data).get("allowed_tools") or [])
        assert BROWSER_TOOLS.isdisjoint(allowed), manifest


@pytest.mark.asyncio
async def test_tool_context_without_allowlist_cannot_execute_browser_open() -> None:
    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output={}))
    gate = PolicyGate(registry, reviewer=MagicMock(), approval_manager=MagicMock())

    result = await gate.call(
        "browser_open",
        {"url": "https://example.com/"},
        ToolCallContext(
            task_goal="open page",
            session_id="s1",
            task_id="t1",
            agent_type="forge",
            allowed_tools=None,
        ),
    )

    assert result.ok is False
    assert "not in allowed_tools" in (result.error or "")
    registry.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_open_uses_gateway_browser_manager() -> None:
    from sebastian.capabilities.tools.browser import browser_open

    manager = _FakeManager()
    fake_state = MagicMock(browser_manager=manager)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_open("https://example.com/")

    assert result.ok is True
    assert result.output == {
        "url": "https://example.com/",
        "title": None,
        "status": "opened",
    }
    assert result.display == "Opened https://example.com/"
    assert manager.opened == ["https://example.com/"]


@pytest.mark.asyncio
async def test_browser_open_returns_unavailable_without_manager() -> None:
    from sebastian.capabilities.tools.browser import browser_open

    fake_state = MagicMock(browser_manager=None)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_open("https://example.com/")

    assert result.ok is False
    assert "Browser service is unavailable" in (result.error or "")
    assert "Do not retry automatically" in (result.error or "")


@pytest.mark.asyncio
async def test_browser_observe_preflight_enriches_reviewer_input() -> None:
    registry = CapabilityRegistry()
    manager = _FakeManager(
        _Metadata(
            url="https://example.com/account?token=secret",
            title="Account",
            opened_by_browser_tool=True,
        )
    )
    fake_state = MagicMock(browser_manager=manager)
    context = ToolCallContext(
        task_goal="inspect current page",
        session_id="s1",
        task_id="t1",
        agent_type="sebastian",
        allowed_tools=ALL_TOOLS,
    )

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        preflight = await registry.review_preflight("browser_observe", {"max_chars": 500}, context)

    assert preflight.ok is True
    assert preflight.review_input == {
        "max_chars": 500,
        "current_url": "https://example.com/account",
        "title": "Account",
        "opened_by_browser_tool": True,
    }


@pytest.mark.asyncio
async def test_browser_observe_preflight_blocks_unowned_or_missing_page() -> None:
    registry = CapabilityRegistry()
    context = ToolCallContext(
        task_goal="inspect current page",
        session_id="s1",
        task_id="t1",
        agent_type="sebastian",
        allowed_tools=ALL_TOOLS,
    )

    for metadata in (None, _Metadata("https://example.com/", "Home", False)):
        manager = _FakeManager(metadata)
        fake_state = MagicMock(browser_manager=manager)
        with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
            preflight = await registry.review_preflight("browser_observe", {}, context)

        assert preflight.ok is False
        assert "Do not retry automatically" in (preflight.error or "")


@pytest.mark.asyncio
async def test_browser_act_rejects_unknown_action_and_password_typing() -> None:
    from sebastian.capabilities.tools.browser import browser_act

    manager = _FakeManager(_Metadata("https://example.com/", "Home", True))
    fake_state = MagicMock(browser_manager=manager)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        unknown = await browser_act("drag", target="#thing")
        password = await browser_act("type", target="input[type=password]", value="secret123")

    assert unknown.ok is False
    assert "Unknown browser action" in (unknown.error or "")
    assert password.ok is False
    assert "credential-sensitive" in (password.error or "")
    assert manager.acted == []


@pytest.mark.asyncio
async def test_browser_act_delegates_small_action_surface_to_manager() -> None:
    from sebastian.capabilities.tools.browser import browser_act

    manager = _FakeManager(_Metadata("https://example.com/", "Home", True))
    manager.target_metadata_result = {"tag": "button", "text": "Open menu"}
    fake_state = MagicMock(browser_manager=manager)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_act("click", target="text=Open menu")

    assert result.ok is True
    assert result.output == {"action": "click", "download": None}
    assert manager.acted == [{"action": "click", "target": "text=Open menu", "value": None}]


@pytest.mark.asyncio
async def test_browser_act_blocks_high_impact_target_metadata() -> None:
    from sebastian.capabilities.tools.browser import browser_act

    manager = _FakeManager(_Metadata("https://example.com/", "Home", True))
    manager.target_metadata_result = {"tag": "button", "text": "Delete account"}
    fake_state = MagicMock(browser_manager=manager)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_act("click", target="button.danger")

    assert result.ok is False
    assert "blocked" in (result.error or "")
    assert manager.acted == []


@pytest.mark.asyncio
async def test_browser_act_blocks_form_submit_metadata() -> None:
    from sebastian.capabilities.tools.browser import browser_act

    manager = _FakeManager(_Metadata("https://example.com/", "Home", True))
    manager.target_metadata_result = {
        "tag": "button",
        "text": "Continue",
        "isSubmitControl": "true",
        "formHasFields": "true",
        "formInputTypes": "email password",
        "formInputNames": "email password current-password",
    }
    fake_state = MagicMock(browser_manager=manager)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_act("click", target="button.continue")

    assert result.ok is False
    assert "blocked" in (result.error or "")
    assert manager.acted == []


@pytest.mark.asyncio
async def test_browser_act_press_blocks_sensitive_target_metadata() -> None:
    from sebastian.capabilities.tools.browser import browser_act

    manager = _FakeManager(_Metadata("https://example.com/", "Home", True))
    manager.target_metadata_result = {"tag": "input", "type": "password", "name": "pin"}
    fake_state = MagicMock(browser_manager=manager)

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        result = await browser_act("press", target="#pin", value="Enter")

    assert result.ok is False
    assert "blocked" in (result.error or "")
    assert manager.acted == []
