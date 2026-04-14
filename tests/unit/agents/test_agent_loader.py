from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock


def test_agent_config_has_new_fields():
    from sebastian.agents._loader import AgentConfig

    cfg = AgentConfig(
        agent_type="code",
        name="CodeAgent",
        display_name="铁匠",
        description="编写代码",
        max_children=5,
        stalled_threshold_minutes=5,
        agent_class=object,  # placeholder
    )
    assert cfg.display_name == "铁匠"
    assert cfg.max_children == 5
    assert cfg.stalled_threshold_minutes == 5


def test_agent_config_no_worker_count():
    from sebastian.agents._loader import AgentConfig

    field_names = {f.name for f in dataclasses.fields(AgentConfig)}
    assert "worker_count" not in field_names


def test_agent_config_has_allowed_fields() -> None:
    from sebastian.agents._loader import AgentConfig

    cfg = AgentConfig(
        agent_type="code",
        name="CodeAgent",
        display_name="Code Agent",
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
    assert cfg.allowed_tools == ["file_read"]
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
    assert cfg.allowed_tools is None
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
