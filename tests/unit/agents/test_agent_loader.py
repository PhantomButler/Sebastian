from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock


def test_agent_config_has_new_fields():
    from sebastian.agents._loader import AgentConfig

    cfg = AgentConfig(
        agent_type="forge",
        name="ForgeAgent",
        description="编写代码",
        max_children=5,
        stalled_threshold_minutes=5,
        agent_class=object,  # placeholder
    )
    assert cfg.name == "ForgeAgent"
    assert cfg.max_children == 5
    assert cfg.stalled_threshold_minutes == 5


def test_agent_config_no_worker_count():
    from sebastian.agents._loader import AgentConfig

    field_names = {f.name for f in dataclasses.fields(AgentConfig)}
    assert "worker_count" not in field_names


def test_agent_config_has_allowed_fields() -> None:
    from sebastian.agents._loader import AgentConfig

    cfg = AgentConfig(
        agent_type="forge",
        name="ForgeAgent",
        description="test",
        max_children=3,
        stalled_threshold_minutes=5,
        agent_class=MagicMock(),
        allowed_tools=["file_read", "shell_exec"],
        allowed_skills=None,
    )
    assert cfg.allowed_tools == ["file_read", "shell_exec"]
    assert cfg.allowed_skills is None


def test_load_agents_reads_allowed_tools_from_manifest(tmp_path: Path) -> None:
    agent_dir = tmp_path / "myagent"
    agent_dir.mkdir()
    manifest = agent_dir / "manifest.toml"
    manifest.write_text(
        '[agent]\nname = "My Agent"\ndescription = "test"\n'
        'max_children = 1\nclass_name = "MyAgent"\n'
        'allowed_tools = ["file_read"]\nallowed_skills = []\n'
    )
    init = agent_dir / "__init__.py"
    init.write_text("class MyAgent: pass\n")

    from sebastian.agents._loader import load_agents

    configs = load_agents(extra_dirs=[tmp_path])
    cfg = next(c for c in configs if c.agent_type == "myagent")
    # 声明 allowed_tools 后 loader 会自动追加 5 个协议工具
    assert cfg.allowed_tools is not None
    assert set(cfg.allowed_tools) == {"file_read"} | {
        "ask_parent",
        "resume_agent",
        "stop_agent",
        "spawn_sub_agent",
        "check_sub_agents",
        "inspect_session",
    }
    assert cfg.allowed_skills == []


def test_load_agents_defaults_allowed_to_none_when_not_declared(tmp_path: Path) -> None:
    agent_dir = tmp_path / "myagent2"
    agent_dir.mkdir()
    manifest = agent_dir / "manifest.toml"
    manifest.write_text(
        '[agent]\nname = "My Agent"\ndescription = "test"\n'
        'max_children = 1\nclass_name = "MyAgent2"\n'
    )
    init = agent_dir / "__init__.py"
    init.write_text("class MyAgent2: pass\n")

    from sebastian.agents._loader import load_agents

    configs = load_agents(extra_dirs=[tmp_path])
    cfg = next(c for c in configs if c.agent_type == "myagent2")
    assert cfg.allowed_tools is not None
    assert set(cfg.allowed_tools) == PROTOCOL_TOOLS
    assert cfg.allowed_skills is None


def test_load_agents_reads_stalled_threshold_from_manifest(tmp_path: Path) -> None:
    agent_dir = tmp_path / "myagent3"
    agent_dir.mkdir()
    manifest = agent_dir / "manifest.toml"
    manifest.write_text(
        '[agent]\nname = "My Agent"\ndescription = "test"\n'
        'max_children = 1\nclass_name = "MyAgent3"\n'
        "stalled_threshold_minutes = 10\n"
    )
    init = agent_dir / "__init__.py"
    init.write_text("class MyAgent3: pass\n")

    from sebastian.agents._loader import load_agents

    configs = load_agents(extra_dirs=[tmp_path])
    cfg = next(c for c in configs if c.agent_type == "myagent3")
    assert cfg.stalled_threshold_minutes == 10


def test_load_agents_defaults_stalled_threshold_to_5(tmp_path: Path) -> None:
    agent_dir = tmp_path / "myagent4"
    agent_dir.mkdir()
    manifest = agent_dir / "manifest.toml"
    manifest.write_text(
        '[agent]\nname = "My Agent"\ndescription = "test"\n'
        'max_children = 1\nclass_name = "MyAgent4"\n'
    )
    init = agent_dir / "__init__.py"
    init.write_text("class MyAgent4: pass\n")

    from sebastian.agents._loader import load_agents

    configs = load_agents(extra_dirs=[tmp_path])
    cfg = next(c for c in configs if c.agent_type == "myagent4")
    assert cfg.stalled_threshold_minutes == 5


PROTOCOL_TOOLS = {
    "ask_parent",
    "resume_agent",
    "stop_agent",
    "spawn_sub_agent",
    "check_sub_agents",
    "inspect_session",
}


def _write_agent(tmp_path: Path, agent_name: str, class_name: str, toml_body: str) -> None:
    agent_dir = tmp_path / agent_name
    agent_dir.mkdir()
    (agent_dir / "manifest.toml").write_text(toml_body)
    (agent_dir / "__init__.py").write_text(f"class {class_name}: pass\n")


def test_allowed_tools_unset_injects_protocol_only(tmp_path: Path) -> None:
    """未声明 allowed_tools → protocol tools only."""
    from sebastian.agents._loader import load_agents

    _write_agent(
        tmp_path,
        "noscope",
        "NoscopeAgent",
        '[agent]\nclass_name = "NoscopeAgent"\ndescription = "no scope"\n',
    )
    configs = {c.agent_type: c for c in load_agents(extra_dirs=[tmp_path])}
    final = configs["noscope"].allowed_tools
    assert final is not None
    assert set(final) == PROTOCOL_TOOLS


def test_allowed_tools_empty_list_injects_protocol_only(tmp_path: Path) -> None:
    """allowed_tools=[] → final 恰好等于 5 个协议工具。"""
    from sebastian.agents._loader import load_agents

    _write_agent(
        tmp_path,
        "minimal",
        "MinimalAgent",
        '[agent]\nclass_name = "MinimalAgent"\ndescription = "minimal"\nallowed_tools = []\n',
    )
    configs = {c.agent_type: c for c in load_agents(extra_dirs=[tmp_path])}
    final = configs["minimal"].allowed_tools
    assert final is not None
    assert set(final) == PROTOCOL_TOOLS


def test_allowed_tools_list_appends_protocol(tmp_path: Path) -> None:
    """allowed_tools=['Read'] → final 为 Read + 5 个协议工具，无重复。"""
    from sebastian.agents._loader import load_agents

    _write_agent(
        tmp_path,
        "reader",
        "ReaderAgent",
        '[agent]\nclass_name = "ReaderAgent"\ndescription = "reader"\nallowed_tools = ["Read"]\n',
    )
    configs = {c.agent_type: c for c in load_agents(extra_dirs=[tmp_path])}
    final = configs["reader"].allowed_tools
    assert final is not None
    assert set(final) == {"Read"} | PROTOCOL_TOOLS
    assert len(final) == len(set(final))


def test_allowed_tools_all_string_uses_explicit_all_sentinel(tmp_path: Path) -> None:
    """allowed_tools='ALL' is the only manifest spelling for unrestricted tools."""
    from sebastian.agents._loader import load_agents
    from sebastian.permissions.types import ALL_TOOLS

    _write_agent(
        tmp_path,
        "allscope",
        "AllscopeAgent",
        '[agent]\nclass_name = "AllscopeAgent"\ndescription = "all"\nallowed_tools = "ALL"\n',
    )
    configs = {c.agent_type: c for c in load_agents(extra_dirs=[tmp_path])}
    assert configs["allscope"].allowed_tools is ALL_TOOLS
