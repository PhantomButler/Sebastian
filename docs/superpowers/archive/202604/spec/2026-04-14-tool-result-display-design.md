---
integrated_to: capabilities/core-tools.md
integrated_at: 2026-04-17
---

# Tool Result 显示优化设计

**日期**：2026-04-14
**状态**：设计完成

## Context

当前后端对 tool call 的结果处理存在两个问题：

1. **人类侧丑**：展开 Android 端的 tool call 卡片「输出」区，看到的是 Python dict 的 repr 截断到 200 字，例如 Read 工具显示 `{'content': '1\tHello, this is a test file.\n', 'total_lines': 1, 'lines_read': 1, 'start_line': 1, 'truncated': False}`。真正对用户有展示价值的只是其中 `content` 字段，其它是给模型看的元数据。
2. **模型侧非标**：喂回 LLM 的 `tool_result` 内容也走 `str(result.output)` —— Python 的 `{'key': 'val'}` 带单引号、`False`/`True`/`None`，不是主流 LLM 训练语料中的 JSON。边缘 case（值里带单引号、嵌套对象）会让解析脆弱。

入口链路：

- 工具定义：`@tool` 装饰器（[sebastian/core/tool.py:140](../../../sebastian/core/tool.py)）
- 人类侧序列化：`str(result.output)[:200]` 写入 `result_summary` 事件和 `record["result"]` 持久化（[sebastian/core/base_agent.py:446-457](../../../sebastian/core/base_agent.py)）
- 模型侧序列化：`str(result.output)` 作为 `tool_result.content`（[sebastian/core/agent_loop.py:39-46](../../../sebastian/core/agent_loop.py)）
- 前端显示：Android `ContentBlock.ToolBlock.resultSummary` 经 `CollapsibleContent` 渲染

## 设计目标

- 人类侧：展开卡片「输出」区只显示该工具真正有价值的字段，不再显示原始 dict repr。
- 模型侧：用 JSON 替换 Python repr，提升 LLM 解析稳定性，不做截断保留完整信息。
- 新增 tool 的接入成本：宽松、就近维护，不强制；不写就走通用回退跑起来，想优雅再加字段。

## 设计

### 1. 数据模型：扩展 `ToolResult`

[sebastian/core/types.py:40](../../../sebastian/core/types.py) 给 `ToolResult` 增加一个可选字段：

```python
class ToolResult(BaseModel):
    ok: bool
    output: Any = None
    error: str | None = None
    empty_hint: str | None = None
    display: str | None = None   # 人类可读摘要；None → 走通用回退
```

`StreamToolResult`（[sebastian/core/stream_events.py:59](../../../sebastian/core/stream_events.py)）**不加** `display`。理由：它是 `agent_loop` 内部传递的"模型视角"结果，`base_agent` 从原始 `ToolResult` 直接读取 `display` 即可，不需要穿过这一层。

### 2. 模型侧：`_tool_result_content` 规范化

[sebastian/core/agent_loop.py:39](../../../sebastian/core/agent_loop.py) 改造：

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

- 字符串类 output（如 `delegate_to_agent`）保持裸字符串，不被包进 JSON 引号。
- dict / list → JSON。`ensure_ascii=False` 保中文可读；`default=str` 兜底 `Path` 等非标准类型。
- 不可序列化 → 回退 `str()`，保证不崩。
- **不截断** —— 模型需要完整上下文做决策。

### 3. 人类侧：`base_agent` 读 `display` + 通用回退

[sebastian/core/base_agent.py:446-457](../../../sebastian/core/base_agent.py) 引入私有函数：

```python
_DISPLAY_MAX = 4000

def _format_tool_display(result: ToolResult) -> str:
    if result.display is not None:
        text = result.display
    else:
        text = str(result.output) if result.output is not None else ""
    return text if len(text) <= _DISPLAY_MAX else text[:_DISPLAY_MAX] + "…"
```

然后在 tool 执行成功分支里：

```python
if result.ok:
    display = _format_tool_display(result)
    record["status"] = "done"
    record["result"] = display
    await self._publish(
        session_id,
        EventType.TOOL_EXECUTED,
        {"tool_id": ..., "name": ..., "result_summary": display},
    )
```

`_format_tool_display` 作为 `base_agent` 模块私有函数，不新建独立文件：它只有 10 行胶水逻辑，tool 作者扩展的是各自 `display=` 参数，不是这个函数。单文件、局部修改，不新增模块层级。

**失败分支不变**：`result.ok=False` 时 `record["result"] = result.error`，`display` 字段不参与。

**截断长度**：`_DISPLAY_MAX = 4000`。原先 200 字看不到内容；Android `CollapsibleContent` 会对 >5 行做二次折叠、>30 行再截断，所以放到 4000 不会导致 UI 卡顿。

### 4. 核心 tool 填 `display`

本次一并改 6 个核心工具，其它内部工具（`ask_parent` / `check_sub_agents` / `inspect_session` / `todo_write` / `spawn_sub_agent` / `reply_to_agent`）本次不动，走回退。

| Tool | `display` 值 |
|---|---|
| Read | `output["content"]` |
| Bash | `stdout`；若 `returncode != 0` 且 `stderr` 非空，追加 `"\n--- stderr ---\n" + stderr` |
| Grep | `output["output"]` |
| Glob | `"\n".join(files)` |
| Write | `f"Wrote {bytes_written} bytes to {file_path}"` |
| Edit | `f"Replaced {replacements} occurrence(s) in {file_path}"` |

`delegate_to_agent` 的 output 本来就是字符串（`"已安排Coder处理：..."`），回退路径直接拿到干净文本，**不用填 display**。

每个 tool 的改动就是在 `return ToolResult(...)` 前先算好 display 字符串，把 `display=display` 作为关键字参数传入。

### 5. 新增 tool 的体验

宽松模式——**不写 display 不报错**，装饰器不做校验。

- 新 tool 跑起来后在 UI 上看到 `{'key': 'val'}` 那一刻，作者会自发想加 display。
- 给模型用的"内部工具"（如 `check_sub_agents`）不该展示在 UI，也不强迫加 display。
- [sebastian/capabilities/tools/README.md](../../../sebastian/capabilities/tools/README.md) 加一节 **"可选：填写 `display`"**，说明回退行为 + 3 行示例，新 tool 作者抄即可。

### 6. 持久化与前端读取

只有一张布、新旧两块油漆：

- 所有 tool block 写入 `assistant_blocks[n]["result"]` 字段（[base_agent.py:448](../../../sebastian/core/base_agent.py)），新老数据共用同一列。
- Android `MessageDto` 把 `b.result` 直接映射到 `ContentBlock.ToolBlock.resultSummary`（[MessageDto.kt:46](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MessageDto.kt)），不区分格式。
- **所以不需要迁移、不需要双读逻辑**：老 session 回放还是 Python repr 丑字符串，新 session 是干净 display，共存即可。
- 前端（Android + 未来 iOS/Web）**不需要改动**。

## 改动清单

| 动作 | 文件 |
|---|---|
| 改 | [sebastian/core/types.py](../../../sebastian/core/types.py)（`ToolResult` +1 field） |
| 改 | [sebastian/core/agent_loop.py](../../../sebastian/core/agent_loop.py)（`_tool_result_content` 改走 JSON） |
| 改 | [sebastian/core/base_agent.py](../../../sebastian/core/base_agent.py)（引入 `_format_tool_display`，替换 2 处 `str(output)[:200]`） |
| 改 | `sebastian/capabilities/tools/{read,bash,grep,glob,write,edit}/__init__.py`（6 个 tool 填 `display`） |
| 改 | [sebastian/capabilities/tools/README.md](../../../sebastian/capabilities/tools/README.md)（加 "display 约定" 小节） |
| 新增 | `tests/unit/test_tool_display_formatting.py` |
| 更新 | 各 tool 的现有单测（若存在）加 `result.display` assert |

## 测试

1. **新增** `tests/unit/test_tool_display_formatting.py`：
   - `_format_tool_display`：display 非 None / display None 回退 / 超长截断 / output=None
   - `_tool_result_content`：失败 → `"Error: ..."` / empty_hint / `<empty output>` / 字符串 output 裸返回 / dict → JSON / 不可序列化回退 `str()`
2. **更新** 各 tool 单测，加 `result.display` 的 assert。
3. **回归** `pytest tests/` 全绿；`ruff check` + `mypy sebastian/` 通过。
4. **端到端手验**（用户执行）：`./scripts/dev.sh` 启动，Android 端触发 Read/Bash/Grep/Glob/Write/Edit 工具调用，确认展开「输出」区显示干净内容；对比老 session 回放仍是旧格式（佐证不破坏兼容）。

## 非目标

- 不改 `ask_parent` / `check_sub_agents` / `inspect_session` / `todo_write` / `spawn_sub_agent` / `reply_to_agent` 这些内部工具的 display（本次不需要，走回退够用）。
- 不迁移老 session 的 `record["result"]`。
- 不改前端（Android / 未来 iOS/Web）显示逻辑。
- 不对 `display` 做多语言 / 主题化 / markdown 渲染（纯字符串）。
