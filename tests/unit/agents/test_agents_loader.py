from __future__ import annotations


def test_load_agents_returns_configs_for_manifest_dirs(tmp_path) -> None:
    """Loader reads manifest.toml and returns AgentConfig objects."""
    agent_dir = tmp_path / "testagent"
    agent_dir.mkdir()
    manifest_content = (
        "[agent]\n"
        'name = "Test Agent"\n'
        'description = "Does testing"\n'
        "max_children = 2\n"
        'class_name = "TestAgent"\n'
    )
    (agent_dir / "manifest.toml").write_text(manifest_content)
    (agent_dir / "__init__.py").write_text(
        "from sebastian.core.base_agent import BaseAgent\n\n"
        "class TestAgent(BaseAgent):\n    name = 'testagent'\n    system_prompt = 'test'\n"
    )

    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        from sebastian.agents._loader import load_agents

        configs = load_agents(extra_dirs=[tmp_path])
    finally:
        sys.path.remove(str(tmp_path))

    test_cfg = next((c for c in configs if c.agent_type == "testagent"), None)
    assert test_cfg is not None
    assert test_cfg.display_name == "Test Agent"
    assert test_cfg.description == "Does testing"
    assert test_cfg.max_children == 2


def test_load_agents_includes_builtin_agents() -> None:
    from sebastian.agents._loader import load_agents

    configs = load_agents()
    agent_types = {c.agent_type for c in configs}
    assert "code" in agent_types
