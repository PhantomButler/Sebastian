from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_agent(knowledge_dir: Path | None):
    """创建一个 knowledge_dir 可控的 TestAgent 实例。"""
    from sebastian.core.base_agent import BaseAgent

    class TestAgent(BaseAgent):
        name = "test"

        def _knowledge_dir(self) -> Path:
            return knowledge_dir  # type: ignore[return-value]

    from sebastian.store.session_store import SessionStore
    store = MagicMock(spec=SessionStore)
    gate = MagicMock()
    gate.get_tool_specs.return_value = []
    gate.get_skill_specs.return_value = []
    return TestAgent(gate, store)


def test_knowledge_section_empty_when_no_dir(tmp_path: Path) -> None:
    """knowledge/ 目录不存在时 _knowledge_section 返回空字符串。"""
    agent = _make_agent(tmp_path / "nonexistent")
    assert agent._knowledge_section() == ""


def test_knowledge_section_empty_when_dir_has_no_md(tmp_path: Path) -> None:
    """knowledge/ 目录存在但无 .md 文件时返回空字符串。"""
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "notes.txt").write_text("ignored")
    agent = _make_agent(kdir)
    assert agent._knowledge_section() == ""


def test_knowledge_section_reads_single_file(tmp_path: Path) -> None:
    """读取单个 .md 文件，返回包含其内容的 Knowledge 块。"""
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "guide.md").write_text("# Guide\n\nDo good work.")
    agent = _make_agent(kdir)
    section = agent._knowledge_section()
    assert section.startswith("## Knowledge")
    assert "# Guide" in section
    assert "Do good work." in section


def test_knowledge_section_reads_multiple_files_alphabetically(tmp_path: Path) -> None:
    """多个 .md 文件按字母顺序拼接。"""
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "b_rules.md").write_text("B content")
    (kdir / "a_intro.md").write_text("A content")
    agent = _make_agent(kdir)
    section = agent._knowledge_section()
    assert section.index("A content") < section.index("B content")


def test_build_system_prompt_includes_knowledge(tmp_path: Path) -> None:
    """build_system_prompt 将 knowledge 节追加在最后。"""
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "rules.md").write_text("Always test your code.")
    agent = _make_agent(kdir)
    prompt = agent.system_prompt
    assert "Always test your code." in prompt
    # knowledge 在最后——在 persona 之后
    persona_pos = prompt.find("You are Sebastian")
    knowledge_pos = prompt.find("Always test your code.")
    assert knowledge_pos > persona_pos
