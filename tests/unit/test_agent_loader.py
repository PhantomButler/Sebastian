from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from sebastian.agents._loader import AgentConfig, load_agents


def test_agent_config_has_allowed_fields() -> None:
    cfg = AgentConfig(
        agent_type="code",
        name="Code Agent",
        description="test",
        worker_count=3,
        agent_class=MagicMock(),
        allowed_tools=["file_read", "shell_exec"],
        allowed_skills=None,
    )
    assert cfg.allowed_tools == ["file_read", "shell_exec"]
    assert cfg.allowed_skills is None


def test_load_agents_reads_allowed_tools_from_manifest(tmp_path: Path) -> None:
    # 创建一个最小 agent 目录
    agent_dir = tmp_path / "myagent"
    agent_dir.mkdir()
    manifest = agent_dir / "manifest.toml"
    manifest.write_text(
        '[agent]\nname = "My Agent"\ndescription = "test"\n'
        'worker_count = 1\nclass_name = "MyAgent"\n'
        'allowed_tools = ["file_read"]\nallowed_skills = []\n'
    )

    # 创建一个假 module
    init = agent_dir / "__init__.py"
    init.write_text("class MyAgent: pass\n")

    configs = load_agents(extra_dirs=[tmp_path])
    assert len(configs) == 1
    cfg = configs[0]
    assert cfg.allowed_tools == ["file_read"]
    assert cfg.allowed_skills == []


def test_load_agents_defaults_allowed_to_none_when_not_declared(tmp_path: Path) -> None:
    agent_dir = tmp_path / "myagent2"
    agent_dir.mkdir()
    manifest = agent_dir / "manifest.toml"
    manifest.write_text(
        '[agent]\nname = "My Agent"\ndescription = "test"\n'
        'worker_count = 1\nclass_name = "MyAgent2"\n'
    )
    init = agent_dir / "__init__.py"
    init.write_text("class MyAgent2: pass\n")

    configs = load_agents(extra_dirs=[tmp_path])
    assert len(configs) == 1
    assert configs[0].allowed_tools is None
    assert configs[0].allowed_skills is None
