# Code Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 BaseAgent 加入 knowledge 文件加载机制，并为 code agent 写好 persona 和工程规范。

**Architecture:** `BaseAgent` 新增 `_knowledge_dir()` 和 `_knowledge_section()` 两个方法。`_knowledge_dir()` 用 `inspect.getfile(type(self))` 定位 agent 模块文件，返回同级 `knowledge/` 目录路径；`_knowledge_section()` 读取其中所有 `.md` 文件，拼成 `## Knowledge` 块追加到系统提示词末尾。`CodeAgent.persona` 替换为简洁人设，`knowledge/engineering_guidelines.md` 承载完整工程规范。

**Tech Stack:** Python 3.12+，`inspect` 标准库，`pathlib.Path`，pytest。

---

## 文件结构

| 文件 | 操作 |
|---|---|
| `sebastian/core/base_agent.py` | 新增 `_knowledge_dir()`、`_knowledge_section()`，更新 `build_system_prompt` |
| `sebastian/agents/code/__init__.py` | 替换 `persona` |
| `sebastian/agents/code/knowledge/engineering_guidelines.md` | 新建 |
| `tests/unit/test_base_agent_knowledge.py` | 新建 |

---

### Task 1：BaseAgent 知识加载机制

**Files:**
- Modify: `sebastian/core/base_agent.py:103-140`
- Create: `tests/unit/test_base_agent_knowledge.py`

- [ ] **Step 1：写失败测试——目录不存在时返回空字符串**

新建 `tests/unit/test_base_agent_knowledge.py`：

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
```

- [ ] **Step 2：运行测试，确认全部失败**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/unit/test_base_agent_knowledge.py -v
```

期望：5 个测试全部 FAILED（`_knowledge_section` 和 `_knowledge_dir` 尚不存在）。

- [ ] **Step 3：在 `base_agent.py` 新增 `_knowledge_dir()` 和 `_knowledge_section()`，更新 `build_system_prompt`**

在 `sebastian/core/base_agent.py` 顶部 import 区加入：

```python
import inspect
from pathlib import Path
```

在 `_agents_section` 方法之后（第 127 行后）插入两个新方法：

```python
def _knowledge_dir(self) -> Path:
    module_file = inspect.getfile(type(self))
    return Path(module_file).parent / "knowledge"

def _knowledge_section(self) -> str:
    kdir = self._knowledge_dir()
    if not kdir.is_dir():
        return ""
    md_files = sorted(kdir.glob("*.md"))
    if not md_files:
        return ""
    parts = [f.read_text(encoding="utf-8") for f in md_files]
    body = "\n\n---\n\n".join(parts)
    return f"## Knowledge\n\n{body}"
```

将 `build_system_prompt` 更新为：

```python
def build_system_prompt(
    self,
    gate: PolicyGate,
    agent_registry: dict[str, object] | None = None,
) -> str:
    sections = [
        self._persona_section(),
        self._tools_section(gate),
        self._skills_section(gate),
        self._agents_section(agent_registry),
        self._knowledge_section(),
    ]
    return "\n\n".join(s for s in sections if s)
```

- [ ] **Step 4：运行测试，确认全部通过**

```bash
pytest tests/unit/test_base_agent_knowledge.py -v
```

期望：5 个测试全部 PASSED。

- [ ] **Step 5：运行完整测试套件，确认无回归**

```bash
pytest tests/unit/ -q
```

期望：全部通过，无新失败。

- [ ] **Step 6：Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/test_base_agent_knowledge.py
git commit -m "feat(base_agent): 新增 _knowledge_section()，从 knowledge/ 目录加载规范文件"
```

---

### Task 2：CodeAgent persona + 工程规范文件

**Files:**
- Modify: `sebastian/agents/code/__init__.py`
- Create: `sebastian/agents/code/knowledge/engineering_guidelines.md`

- [ ] **Step 1：替换 `CodeAgent.persona`**

将 `sebastian/agents/code/__init__.py` 改为：

```python
from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class CodeAgent(BaseAgent):
    name = "code"
    persona = (
        "You are a senior software engineer serving {owner_name}.\n"
        "You are precise, methodical, and pragmatic — you write clean code that solves "
        "the actual problem, not the imagined one.\n\n"
        "Core principles:\n"
        "- Understand before acting. Never start coding until the requirement is unambiguous.\n"
        "- Shortest path to working code. No speculative abstractions, no defensive padding, "
        "no 'just in case' features.\n"
        "- No patches. Fix root causes, not symptoms.\n"
        "- Verify your work. Run it, test it, confirm it does what was asked.\n"
        "- When in doubt, ask. A clarifying question costs less than rework."
    )
```

- [ ] **Step 2：新建 `knowledge/` 目录和 `engineering_guidelines.md`**

新建 `sebastian/agents/code/knowledge/engineering_guidelines.md`：

````markdown
# Engineering Guidelines

## Workflow

Every task follows this sequence — no skipping steps:

1. **Clarify** — List every ambiguous point before writing any code. If the requirement can be interpreted in more than one way, ask. State any assumptions explicitly so the user can correct them early.
2. **Plan** — For any task that touches more than one file or will take more than ~30 minutes: write an execution plan (what changes, which files, how to verify) and share it with the user before starting. Wait for confirmation.
3. **Execute** — Implement according to the plan. Verify after each logical unit — don't batch all verification to the end.
4. **Verify** — Actually run the code or tests. Attach the real output to your response.
5. **Report** — State concisely: what was done, what the result is, and any remaining issues or limitations.

## Code Quality

- **Shortest path**: if 3 lines solve it, don't write 10.
- **No patches**: symptoms have root causes — find and fix the cause, not the symptom.
- **No over-engineering**: write only for the current requirement. Do not add abstractions, hooks, or config for hypothetical future needs.
- **No defensive padding**: only validate at real boundaries (user input, external APIs). Don't add error handling for scenarios that cannot occur.
- **Type annotations**: all Python code must have complete type annotations, including return types (`-> None` counts).
- **Naming**: functions and variables use `snake_case`, classes use `PascalCase`, constants use `SCREAMING_SNAKE_CASE`.

## Execution Safety

Assess risk before every operation:

| Operation | Action |
|---|---|
| Read / analyse / format | Execute directly |
| Write files / modify config | Announce what will change before executing |
| Network requests / system commands / deletions | State the risk explicitly, wait for user confirmation |
| Code from unknown or untrusted sources | Review before running — never execute blindly |

## Communication

The user can send messages to intervene in any session at any time. Design your responses accordingly:

- **Clarify before coding**: when requirements are ambiguous, ask — don't guess and rework.
- **Make assumptions explicit**: if the task description is incomplete, state your assumptions before acting so the user can redirect you.
- **Transparent progress**: for multi-step work, report progress at natural checkpoints so the user always knows where things stand.
- **Concise replies**: don't restate what the user said. Don't add filler phrases. Lead with the result.
- **Auditable plans**: a task plan must be specific enough that the user can spot problems before execution begins.
````

- [ ] **Step 3：验证 knowledge 文件被正确加载到系统提示词**

运行以下 Python 片段（临时验证，不提交）：

```bash
cd /Users/ericw/work/code/ai/sebastian
python3 - <<'EOF'
import os; os.environ.setdefault("ANTHROPIC_API_KEY", "test")
from unittest.mock import MagicMock
from sebastian.agents.code import CodeAgent
from sebastian.store.session_store import SessionStore

gate = MagicMock()
gate.get_tool_specs.return_value = []
gate.get_skill_specs.return_value = []
agent = CodeAgent(gate, MagicMock(spec=SessionStore))
prompt = agent.system_prompt
print("=== SYSTEM PROMPT ===")
print(prompt)
print("=== HAS KNOWLEDGE ===", "## Knowledge" in prompt)
print("=== HAS WORKFLOW ===", "Workflow" in prompt)
EOF
```

期望输出包含 `HAS KNOWLEDGE === True` 和 `HAS WORKFLOW === True`。

- [ ] **Step 4：运行完整单元测试**

```bash
pytest tests/unit/ -q
```

期望：全部通过。

- [ ] **Step 5：Commit**

```bash
git add sebastian/agents/code/__init__.py sebastian/agents/code/knowledge/engineering_guidelines.md
git commit -m "feat(code-agent): 替换 persona，新增 engineering_guidelines.md 工程规范"
```
