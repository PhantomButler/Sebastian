# Tool Result 显示优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `ToolResult` 加 `display` 字段，把模型侧 tool_result content 改走 JSON，把人类侧 result_summary 改为读 `display`（回退 `str(output)[:4000]`），并给 6 个核心工具（Read/Bash/Grep/Glob/Write/Edit）填上 display。

**Architecture:** 数据模型加一个可选字段 → 两个序列化点分开优化（模型侧 JSON、人类侧 display+截断）→ 工具层就近填 display。新老 session 共用同一字段、不迁移。

**Tech Stack:** Python 3.12+, Pydantic, pytest, 已有 `@tool` 装饰器体系。

**Spec:** `docs/superpowers/specs/2026-04-14-tool-result-display-design.md`

---

## File Structure

- **修改**：
  - `sebastian/core/types.py` — `ToolResult` 加 `display: str | None = None`
  - `sebastian/core/agent_loop.py` — `_tool_result_content` 改 JSON 序列化
  - `sebastian/core/base_agent.py` — 引入 `_format_tool_display`，替换 2 处 `str(output)[:200]`
  - `sebastian/capabilities/tools/{read,bash,grep,glob,write,edit}/__init__.py` — 各填 `display`
  - `sebastian/capabilities/tools/README.md` — 新增 "可选：display" 小节
  - `tests/unit/capabilities/test_tool_result_content.py` — `test_nonempty_dict_output_uses_str` 改名为 `*_uses_json`，断言值改 JSON
  - 各工具现有单测（`test_tools_{read,grep,glob,write,edit}.py`）加 display 断言
- **新建**：
  - `tests/unit/core/test_tool_display_format.py` — `_format_tool_display` 单元测试
  - `tests/unit/capabilities/test_tools_bash.py` — Bash tool 目前没独立单测，本次新增并覆盖 display

---

## Task 1: `ToolResult` 加 `display` 字段

**Files:**
- Modify: `sebastian/core/types.py:40-46`
- Test: `tests/unit/core/test_types.py`（若已存在 ToolResult 测试则追加，否则新增测试）

- [ ] **Step 1: Write the failing test**

追加到 `tests/unit/core/test_types.py` 末尾（若文件不存在则新建，保持 `from __future__ import annotations` 开头）：

```python
def test_tool_result_display_defaults_to_none() -> None:
    from sebastian.core.types import ToolResult
    r = ToolResult(ok=True, output={"k": "v"})
    assert r.display is None


def test_tool_result_display_accepts_string() -> None:
    from sebastian.core.types import ToolResult
    r = ToolResult(ok=True, output={"k": "v"}, display="human-readable")
    assert r.display == "human-readable"
```

- [ ] **Step 2: Run tests, verify they fail**

```
pytest tests/unit/core/test_types.py::test_tool_result_display_defaults_to_none \
       tests/unit/core/test_types.py::test_tool_result_display_accepts_string -v
```
Expected: FAIL (AttributeError 或 ValidationError — `display` 不存在)

- [ ] **Step 3: Add the field**

修改 `sebastian/core/types.py:40-46`，`ToolResult` 类加一行：

```python
class ToolResult(BaseModel):
    """Result of a tool execution."""

    ok: bool
    output: Any = None
    error: str | None = None
    empty_hint: str | None = None
    display: str | None = None
```

- [ ] **Step 4: Run tests, verify they pass**

```
pytest tests/unit/core/test_types.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/types.py tests/unit/core/test_types.py
git commit -m "$(cat <<'EOF'
feat(core): ToolResult 增加可选 display 字段

为后续人类侧 result_summary 读取 tool 自定义展示文本做准备。None 表示走通用回退。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 模型侧 `_tool_result_content` 走 JSON

**Files:**
- Modify: `sebastian/core/agent_loop.py:39-46`
- Test: `tests/unit/capabilities/test_tool_result_content.py`

- [ ] **Step 1: 修改现有失败断言 + 新增覆盖**

修改 `tests/unit/capabilities/test_tool_result_content.py:91-94`。原来：

```python
def test_nonempty_dict_output_uses_str(self) -> None:
    output = {"stdout": "", "returncode": 0}
    r = _make_result(output=output)
    assert _tool_result_content(r) == str(output)
```

改为：

```python
def test_nonempty_dict_output_uses_json(self) -> None:
    output = {"stdout": "hello", "returncode": 0}
    r = _make_result(output=output)
    assert _tool_result_content(r) == '{"stdout": "hello", "returncode": 0}'

def test_nonempty_dict_output_preserves_chinese(self) -> None:
    output = {"msg": "你好"}
    r = _make_result(output=output)
    assert _tool_result_content(r) == '{"msg": "你好"}'

def test_nonempty_list_output_uses_json(self) -> None:
    r = _make_result(output=["a", "b"])
    assert _tool_result_content(r) == '["a", "b"]'

def test_unserializable_output_falls_back_to_str(self) -> None:
    class Opaque:
        def __str__(self) -> str:
            return "opaque-value"
    r = _make_result(output=Opaque())
    # json.dumps 对 Opaque 实例走 default=str，落回 "opaque-value" 的 JSON 字符串
    assert _tool_result_content(r) == '"opaque-value"'
```

- [ ] **Step 2: 运行测试，确认失败**

```
pytest tests/unit/capabilities/test_tool_result_content.py -v
```
Expected: 前 3 个新 test FAIL（输出是 Python repr 而非 JSON）

- [ ] **Step 3: 改 `_tool_result_content`**

`sebastian/core/agent_loop.py` 顶部已有 `import json`。若没有则加上。修改 `_tool_result_content`（第 39-46 行）为：

```python
def _tool_result_content(result: ToolResult) -> str:
    if not result.ok:
        return f"Error: {result.error}"
    if result.empty_hint:
        return result.empty_hint
    if _is_empty_output(result.output):
        return "<empty output>"
    output = result.output
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(output)
```

- [ ] **Step 4: 运行测试，确认通过**

```
pytest tests/unit/capabilities/test_tool_result_content.py -v
```
Expected: PASS

全量跑一遍以防其它地方依赖旧行为：

```
pytest tests/ -x -q
```

Expected: 全绿（若有其它测试在断言 `str(dict)` 的模型侧输出，同步修正为 JSON 字符串）。

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/agent_loop.py tests/unit/capabilities/test_tool_result_content.py
git commit -m "$(cat <<'EOF'
feat(core): 模型侧 tool_result content 走 JSON 序列化

dict/list output 用 json.dumps(ensure_ascii=False, default=str)；
字符串 output 保持裸字符串不加引号；不可序列化回退 str()。
消除 Python dict repr 的单引号 / False / None 对 LLM 解析的噪声。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 人类侧 `_format_tool_display` + 接线

**Files:**
- Create: `tests/unit/core/test_tool_display_format.py`
- Modify: `sebastian/core/base_agent.py`（引入函数 + 替换 2 处 `str(output)[:200]`）

- [ ] **Step 1: 写纯函数的失败测试**

新建 `tests/unit/core/test_tool_display_format.py`：

```python
from __future__ import annotations

from sebastian.core.base_agent import _DISPLAY_MAX, _format_tool_display
from sebastian.core.types import ToolResult


class TestFormatToolDisplay:
    def test_display_field_used_when_present(self) -> None:
        r = ToolResult(ok=True, output={"content": "raw"}, display="clean")
        assert _format_tool_display(r) == "clean"

    def test_falls_back_to_str_output_when_display_is_none(self) -> None:
        r = ToolResult(ok=True, output={"k": "v"})
        assert _format_tool_display(r) == "{'k': 'v'}"

    def test_empty_output_returns_empty_string(self) -> None:
        r = ToolResult(ok=True, output=None)
        assert _format_tool_display(r) == ""

    def test_truncates_overlong_display(self) -> None:
        long_text = "x" * (_DISPLAY_MAX + 50)
        r = ToolResult(ok=True, display=long_text)
        formatted = _format_tool_display(r)
        assert len(formatted) == _DISPLAY_MAX + 1  # +1 for ellipsis
        assert formatted.endswith("…")

    def test_truncates_overlong_fallback_output(self) -> None:
        long_output = "y" * (_DISPLAY_MAX + 50)
        r = ToolResult(ok=True, output=long_output)
        formatted = _format_tool_display(r)
        assert len(formatted) == _DISPLAY_MAX + 1
        assert formatted.endswith("…")
```

- [ ] **Step 2: 运行测试，确认失败**

```
pytest tests/unit/core/test_tool_display_format.py -v
```
Expected: FAIL (ImportError — `_format_tool_display` / `_DISPLAY_MAX` 不存在)

- [ ] **Step 3: 在 base_agent 加函数 + 常量**

在 `sebastian/core/base_agent.py` 现有 import 之后（紧邻文件开头、所有 `from` 结束后）加：

```python
_DISPLAY_MAX = 4000


def _format_tool_display(result: ToolResult) -> str:
    """把 ToolResult 转成人类可读的 result_summary 字符串。

    优先使用 tool 自己提供的 display；否则回退 str(output)。
    任意一种都会截断到 _DISPLAY_MAX 字符，超长加 `…`。
    """
    if result.display is not None:
        text = result.display
    elif result.output is not None:
        text = str(result.output)
    else:
        text = ""
    if len(text) > _DISPLAY_MAX:
        return text[:_DISPLAY_MAX] + "…"
    return text
```

确认 `ToolResult` 已从 `sebastian.core.types` 导入（文件顶部已存在）。注意：已有 `ToolResult as StreamToolResult` 这种 rename import，底层 Pydantic `ToolResult` 需要原名引用——如果文件里用的是 rename 后的 `StreamToolResult`，额外加一行 `from sebastian.core.types import ToolResult`。

- [ ] **Step 4: 运行纯函数测试，确认通过**

```
pytest tests/unit/core/test_tool_display_format.py -v
```
Expected: PASS

- [ ] **Step 5: 替换 base_agent 里 2 处 `str(output)[:200]`**

修改 `sebastian/core/base_agent.py:446-457`（tool 成功分支）：

```python
else:
    if result.ok:
        display = _format_tool_display(result)
        record["status"] = "done"
        record["result"] = display
        await self._publish(
            session_id,
            EventType.TOOL_EXECUTED,
            {
                "tool_id": event.tool_id,
                "name": event.name,
                "result_summary": display,
            },
        )
```

（同一分支内的 `else:`（tool 失败）保持 `record["result"] = result.error or ""` 不动。）

- [ ] **Step 6: 跑 base_agent 现有单测，确认不破坏**

```
pytest tests/unit/core/ -v
```
Expected: PASS。若有测试断言 `result_summary == "{'k': 'v'}"` 这种 200 字截断格式，改断言为新格式（字符串不截断、或 display 路径）。

- [ ] **Step 7: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/core/test_tool_display_format.py
git commit -m "$(cat <<'EOF'
feat(core): base_agent 改用 _format_tool_display 产出 result_summary

引入 _format_tool_display 纯函数：优先 ToolResult.display，回退 str(output)，
统一截断到 4000 字。替换原来 2 处 str(result.output)[:200]。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Read tool 填 `display`

**Files:**
- Modify: `sebastian/capabilities/tools/read/__init__.py`
- Test: `tests/unit/capabilities/test_tools_read.py`

- [ ] **Step 1: 加失败测试**

追加到 `tests/unit/capabilities/test_tools_read.py` 末尾：

```python
async def test_read_display_is_content_field(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.read import read as read_tool
    f = tmp_path / "hi.txt"
    f.write_text("Hello\nWorld\n")
    result = await read_tool(file_path=str(f))
    assert result.ok
    # display 仅包含 content 文本（带 cat -n 前缀），不含 total_lines 等元数据
    assert result.display == result.output["content"]
    assert "total_lines" not in (result.display or "")
```

（如果文件头没有 `from pathlib import Path` / `import pytest` / `pytestmark = pytest.mark.asyncio`，参照同文件已有 async test 的 setup。）

- [ ] **Step 2: 跑测试确认失败**

```
pytest tests/unit/capabilities/test_tools_read.py::test_read_display_is_content_field -v
```
Expected: FAIL (`result.display is None`)

- [ ] **Step 3: 在 Read tool return 前塞 display**

修改 `sebastian/capabilities/tools/read/__init__.py:61-71` 附近，改为：

```python
output = {
    "content": content,
    "total_lines": total_lines,
    "lines_read": len(selected),
    "start_line": start + 1,
    "truncated": (start + max_lines) < total_lines,
}
return ToolResult(
    ok=True,
    output=output,
    display=content,
    empty_hint=empty_hint,
)
```

- [ ] **Step 4: 跑测试确认通过**

```
pytest tests/unit/capabilities/test_tools_read.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/read/__init__.py tests/unit/capabilities/test_tools_read.py
git commit -m "feat(tools): Read 填 display=content，去除 UI 侧元数据噪声

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Bash tool 填 `display` + 新增单测文件

**Files:**
- Modify: `sebastian/capabilities/tools/bash/__init__.py`
- Create: `tests/unit/capabilities/test_tools_bash.py`

- [ ] **Step 1: 新建 Bash tool 测试文件，写失败测试**

新建 `tests/unit/capabilities/test_tools_bash.py`：

```python
from __future__ import annotations

import pytest

from sebastian.capabilities.tools.bash import bash

pytestmark = pytest.mark.asyncio


async def test_bash_display_is_stdout_on_success() -> None:
    r = await bash(command="printf 'hello'")
    assert r.ok
    assert r.display == "hello"


async def test_bash_display_appends_stderr_on_nonzero_exit() -> None:
    # 写到 stderr 并以非 0 码退出
    r = await bash(command="printf 'boom' >&2; exit 1")
    assert r.ok  # Bash tool 的 ok 不等于 returncode==0
    assert r.display is not None
    assert "--- stderr ---" in r.display
    assert "boom" in r.display


async def test_bash_display_omits_stderr_on_zero_exit() -> None:
    # stderr 有内容但 returncode=0（很多 CLI 写 info 到 stderr）
    r = await bash(command="printf 'out'; printf 'noise' >&2; exit 0")
    assert r.ok
    assert r.display == "out"
    assert "noise" not in (r.display or "")
```

- [ ] **Step 2: 跑测试确认失败**

```
pytest tests/unit/capabilities/test_tools_bash.py -v
```
Expected: FAIL (`display is None`)

- [ ] **Step 3: 改 Bash tool**

修改 `sebastian/capabilities/tools/bash/__init__.py:63-72`：

```python
    if proc.returncode != 0 and stderr:
        display = f"{stdout}\n--- stderr ---\n{stderr}" if stdout else f"--- stderr ---\n{stderr}"
    else:
        display = stdout

    return ToolResult(
        ok=True,
        output={
            "stdout": stdout,
            "stderr": stderr,
            "returncode": proc.returncode,
            "truncated": truncated,
        },
        display=display,
        empty_hint=empty_hint,
    )
```

- [ ] **Step 4: 跑测试确认通过**

```
pytest tests/unit/capabilities/test_tools_bash.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/bash/__init__.py tests/unit/capabilities/test_tools_bash.py
git commit -m "feat(tools): Bash 填 display=stdout（失败时追加 stderr）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Grep tool 填 `display`

**Files:**
- Modify: `sebastian/capabilities/tools/grep/__init__.py`
- Test: `tests/unit/capabilities/test_tools_grep.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/capabilities/test_tools_grep.py` 末尾：

```python
async def test_grep_display_is_output_field(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.grep import grep as grep_tool
    f = tmp_path / "a.txt"
    f.write_text("alpha\nbeta foo gamma\n")
    r = await grep_tool(pattern="foo", path=str(tmp_path))
    assert r.ok
    assert r.display == r.output["output"]
    assert "backend" not in (r.display or "")
    assert "truncated" not in (r.display or "")
```

- [ ] **Step 2: 跑测试确认失败**

```
pytest tests/unit/capabilities/test_tools_grep.py::test_grep_display_is_output_field -v
```
Expected: FAIL

- [ ] **Step 3: 改 Grep tool**

修改 `sebastian/capabilities/tools/grep/__init__.py:125-132`：

```python
    return ToolResult(
        ok=True,
        output={
            "output": output,
            "truncated": truncated,
            "backend": backend,
        },
        display=output,
    )
```

- [ ] **Step 4: 跑测试确认通过**

```
pytest tests/unit/capabilities/test_tools_grep.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/grep/__init__.py tests/unit/capabilities/test_tools_grep.py
git commit -m "feat(tools): Grep 填 display=output（去除 backend / truncated 元数据）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Glob tool 填 `display`

**Files:**
- Modify: `sebastian/capabilities/tools/glob/__init__.py`
- Test: `tests/unit/capabilities/test_tools_glob.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/capabilities/test_tools_glob.py` 末尾：

```python
async def test_glob_display_is_newline_joined_files(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.glob import glob as glob_tool
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("y")
    r = await glob_tool(pattern="*.py", path=str(tmp_path))
    assert r.ok
    assert r.display is not None
    lines = set(r.display.split("\n"))
    assert lines == {"a.py", "b.py"}
```

- [ ] **Step 2: 跑测试确认失败**

```
pytest tests/unit/capabilities/test_tools_glob.py::test_glob_display_is_newline_joined_files -v
```
Expected: FAIL

- [ ] **Step 3: 改 Glob tool**

修改 `sebastian/capabilities/tools/glob/__init__.py:42-49`：

```python
    return ToolResult(
        ok=True,
        output={
            "files": files,
            "count": len(files),
            "truncated": truncated,
        },
        display="\n".join(files),
    )
```

- [ ] **Step 4: 跑测试确认通过**

```
pytest tests/unit/capabilities/test_tools_glob.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/glob/__init__.py tests/unit/capabilities/test_tools_glob.py
git commit -m "feat(tools): Glob 填 display=files join 换行

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Write tool 填 `display`

**Files:**
- Modify: `sebastian/capabilities/tools/write/__init__.py`
- Test: `tests/unit/capabilities/test_tools_write.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/capabilities/test_tools_write.py` 末尾：

```python
async def test_write_display_is_summary_line(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.write import write as write_tool
    target = tmp_path / "out.txt"
    r = await write_tool(file_path=str(target), content="hi")
    assert r.ok
    assert r.display == f"Wrote 2 bytes to {target}"
```

- [ ] **Step 2: 跑测试确认失败**

```
pytest tests/unit/capabilities/test_tools_write.py::test_write_display_is_summary_line -v
```
Expected: FAIL

- [ ] **Step 3: 改 Write tool**

修改 `sebastian/capabilities/tools/write/__init__.py:34-42`：

```python
        _file_state.invalidate(path)
        bytes_written = len(content.encode("utf-8"))
        return ToolResult(
            ok=True,
            output={
                "file_path": path,
                "action": action,
                "bytes_written": bytes_written,
            },
            display=f"Wrote {bytes_written} bytes to {path}",
        )
```

- [ ] **Step 4: 跑测试确认通过**

```
pytest tests/unit/capabilities/test_tools_write.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/write/__init__.py tests/unit/capabilities/test_tools_write.py
git commit -m "feat(tools): Write 填 display 为单行 \"Wrote N bytes to path\"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: Edit tool 填 `display`

**Files:**
- Modify: `sebastian/capabilities/tools/edit/__init__.py`
- Test: `tests/unit/capabilities/test_tools_edit.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/capabilities/test_tools_edit.py` 末尾：

```python
async def test_edit_display_is_summary_line(tmp_path: Path) -> None:
    from sebastian.capabilities.tools import _file_state
    from sebastian.capabilities.tools.edit import edit as edit_tool
    target = tmp_path / "src.py"
    target.write_text("foo bar foo")
    _file_state.record_read(str(target))  # Edit 要求先 read

    r = await edit_tool(file_path=str(target), old_string="foo", new_string="baz")
    assert r.ok
    assert r.display == f"Replaced 1 occurrence(s) in {target}"
```

- [ ] **Step 2: 跑测试确认失败**

```
pytest tests/unit/capabilities/test_tools_edit.py::test_edit_display_is_summary_line -v
```
Expected: FAIL

- [ ] **Step 3: 改 Edit tool**

修改 `sebastian/capabilities/tools/edit/__init__.py:66`：

```python
        _file_state.invalidate(path)
        return ToolResult(
            ok=True,
            output={"file_path": path, "replacements": replacements},
            display=f"Replaced {replacements} occurrence(s) in {path}",
        )
```

- [ ] **Step 4: 跑测试确认通过**

```
pytest tests/unit/capabilities/test_tools_edit.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/edit/__init__.py tests/unit/capabilities/test_tools_edit.py
git commit -m "feat(tools): Edit 填 display 为单行 \"Replaced N occurrence(s) in path\"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 10: tools/README.md 增加 "display 约定" 小节

**Files:**
- Modify: `sebastian/capabilities/tools/README.md`

- [ ] **Step 1: 读一下现有 README 结构确定插入位置**

```bash
cat sebastian/capabilities/tools/README.md | head -80
```

找一个讲 `@tool` / `ToolResult` 的章节，把新小节插在其后。

- [ ] **Step 2: 追加 "可选：填写 display" 小节**

```markdown
## 可选：填写 `display`

`ToolResult` 有一个可选的 `display: str | None` 字段，用于给 UI 展示的「输出」区提供干净文本。

- 不填（默认 `None`）时，runtime 会回退用 `str(output)[:4000]`。对 output 是字符串的工具（如 `delegate_to_agent`）回退已经够用；对 dict output 则会显示 Python repr，UI 上不好看。
- 填了 display 就用 display。典型做法是从 `output` 里抽用户真正关心的字段：

```python
return ToolResult(
    ok=True,
    output={"content": content, "total_lines": n, "truncated": flag},
    display=content,  # UI 只需看内容
)
```

给模型的 `tool_result` 仍然是完整 `output`，display 不会泄漏给 LLM。
```

- [ ] **Step 3: Commit**

```bash
git add sebastian/capabilities/tools/README.md
git commit -m "docs(tools): 说明 ToolResult.display 字段约定和回退行为

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 11: 回归测试 + lint

- [ ] **Step 1: 全量 pytest**

```bash
pytest tests/ -x -q
```

Expected: 全绿。

若某个 `test_base_agent*.py` 里有对 `result_summary` 的老断言被打破（原来期望 `"{'k': 'v'}"` 这种形式），更新断言——应当期望该工具的新 display（或 str(output) 回退）。

- [ ] **Step 2: ruff + mypy**

```bash
ruff check sebastian/ tests/
ruff format --check sebastian/ tests/
mypy sebastian/
```

Expected: 无错误。若 ruff format 有 diff，跑 `ruff format sebastian/ tests/` 修复后加入上一个 commit 或新建一个 `style:` commit。

- [ ] **Step 3: 若有 fix，commit**

```bash
git add -u
git commit -m "style: ruff format / mypy 修复

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

若无改动，跳过本步。

---

## Self-Review 结果

- **Spec 覆盖**：`ToolResult.display` 字段（Task 1）✅；模型侧 JSON（Task 2）✅；人类侧 `_format_tool_display`（Task 3）✅；Read/Bash/Grep/Glob/Write/Edit 六个核心 tool（Task 4-9）✅；README 约定（Task 10）✅；回归（Task 11）✅。非目标明确排除的：内部工具不改、老 session 不迁移、前端不改 —— plan 里也确认未改动。
- **Placeholder scan**：无 TBD/TODO；所有 step 都含具体代码或命令。
- **Type/名字一致性**：`_format_tool_display` / `_DISPLAY_MAX` / `display` 字段名称全文一致；各 tool return 的 kwarg 都是 `display=`；测试里 `r.display` 访问一致。
- **手动验证**：spec 里的端到端手验（启动 `./scripts/dev.sh` 在 App 里触发工具）留给用户执行，不在 plan 的自动化步骤里。
