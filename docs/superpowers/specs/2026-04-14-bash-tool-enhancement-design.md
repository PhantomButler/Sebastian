# Bash Tool Enhancement Design

**日期**：2026-04-14  
**状态**：已批准，待实现  
**范围**：对齐 Claude Code BashTool 能力，提升 bash 工具稳定性与 agent 可靠性

---

## 背景

当前 `sebastian/capabilities/tools/bash/__init__.py` 实现简单，与 Claude Code BashTool 相比存在以下不足：

1. 无 `description` 参数，bash 调用对用户和日志完全不透明
2. 无静默命令识别（`mv`/`rm` 等无输出命令被当作"无输出异常"处理）
3. 无语义化退出码（`grep` 返回 1 被 LLM 误判为命令失败）
4. 长命令运行时无任何进度信号（App 端和用户完全黑盒）

**不在本次范围内**：abort/中断机制（需要改动 AgentLoop，另立任务）、后台任务（run_in_background）、大输出磁盘持久化。

---

## 目标

- `description` 参数：提升可观测性，日志记录命令意图
- `noOutputExpected`：静默命令无输出时返回 `"Done"`，防止 LLM 误判
- `returnCodeInterpretation`：白名单命令的语义化退出码，消除 LLM 对 grep/find 等 exit 1 的误判
- 进度心跳：长命令每 3s 通过 EventBus 推 `TOOL_RUNNING` 事件，App 显示"执行中 (Xs)"

---

## 方案选择

评估了三个方案：

- **方案 A**：全部改动收在 bash tool 内，进度只写日志。改动最小但 App 无进度反馈。
- **方案 B（选定）**：`ToolCallContext` 增加 `progress_cb` 回调，bash tool 通过 `_current_tool_ctx` 获取并发心跳。工具与 EventBus 解耦，复用现有 `TOOL_RUNNING` 事件类型。
- **方案 C**：AgentLoop 引入 `ToolProgress` 流式事件。架构侵入最大，远超本次收益。

---

## 架构设计

### 改动文件

| 文件 | 改动 |
|------|------|
| `sebastian/permissions/types.py` | `ToolCallContext` 增加 `progress_cb` 字段 |
| `sebastian/core/base_agent.py` | 创建 context 时绑定 `self._publish` 为 `progress_cb` |
| `sebastian/capabilities/tools/bash/__init__.py` | 实现全部 4 个功能点 |

**不改动**：`ToolResult`、`AgentLoop`、`stream_events.py`、`gate.py`、`registry.py`、SSE/EventBus/Gateway。

---

## 详细设计

### 1. ToolCallContext 增加 progress_cb

```python
# permissions/types.py
from collections.abc import Awaitable, Callable
from typing import Any

@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None
    agent_type: str = ""
    depth: int = 1
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]] | None = None
```

- `progress_cb` 默认 `None`，单测直接调用工具时无副作用
- 回调签名统一为 `(data: dict) -> Awaitable[None]`，工具层不感知 EventBus

### 2. base_agent.py 绑定 publish

在创建 `ToolCallContext` 处（`base_agent.py` 约 L445）新增一行：

```python
context = ToolCallContext(
    task_goal=self._current_task_goals.get(session_id, ""),
    session_id=session_id,
    task_id=task_id,
    agent_type=agent_context,
    depth=getattr(self, "_current_depth", {}).get(session_id, 1),
    progress_cb=lambda data: self._publish(
        session_id, EventType.TOOL_RUNNING, data
    ),
)
```

### 3. bash/__init__.py — 功能实现

#### 3.1 description 参数

```python
async def bash(
    command: str,
    timeout: int | None = None,
    description: str | None = None,
) -> ToolResult:
    logger.debug("bash[%s]: %s", description or command[:60], command)
```

- 进入函数 schema，model 可填写
- 仅写日志，不参与执行，不进 LLM 输出
- 会随 `input` dict 一起出现在 `TOOL_RUNNING` 事件的 `input` 字段里（App 可显示），不额外单独推送

#### 3.2 noOutputExpected — 静默命令集

```python
_SILENT_COMMANDS = {
    "mv", "cp", "rm", "mkdir", "rmdir", "chmod", "chown",
    "chgrp", "touch", "ln", "cd", "export", "unset", "wait",
}

def _is_silent_command(command: str) -> bool:
    base = command.strip().split()[0] if command.strip() else ""
    return base in _SILENT_COMMANDS
```

无输出时的 `empty_hint` 逻辑：

```python
if not stdout and not stderr:
    if _is_silent_command(command):
        empty_hint = "Done"
    else:
        empty_hint = f"Command exited with code {proc.returncode}, no output"
```

#### 3.3 returnCodeInterpretation — 语义化退出码白名单

```python
_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "grep":  {1: "No matches found (not an error)"},
    "find":  {1: "No matches found (not an error)"},
    "diff":  {1: "Files differ (not an error)"},
    "test":  {1: "Condition false (not an error)"},
    "[":     {1: "Condition false (not an error)"},
}

def _interpret_exit_code(command: str, returncode: int) -> str | None:
    base = command.strip().split()[0] if command.strip() else ""
    return _EXIT_CODE_SEMANTICS.get(base, {}).get(returncode)
```

有解释时附在 `display` 末尾：

```python
interpretation = _interpret_exit_code(command, proc.returncode)
if interpretation:
    display = f"{display}\n(exit {proc.returncode}: {interpretation})" if display else f"(exit {proc.returncode}: {interpretation})"
```

#### 3.4 进度心跳

心跳协程：

```python
async def _heartbeat(
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]],
    stop_event: asyncio.Event,
    tool_id_hint: str,
) -> None:
    start = time.monotonic()
    interval = 3.0
    while True:
        try:
            await asyncio.wait_for(
                asyncio.shield(stop_event.wait()), timeout=interval
            )
            break  # stop_event set，退出
        except TimeoutError:
            elapsed = int(time.monotonic() - start)
            try:
                await progress_cb({"elapsed_seconds": elapsed})
            except Exception:
                logger.warning("bash heartbeat publish failed", exc_info=True)
```

在 bash 主函数中：

```python
ctx = _current_tool_ctx.get(None)
stop_event = asyncio.Event()
heartbeat_task: asyncio.Task[None] | None = None

if ctx and ctx.progress_cb:
    heartbeat_task = asyncio.create_task(
        _heartbeat(ctx.progress_cb, stop_event, "bash")
    )
try:
    stdout_bytes, stderr_bytes = await asyncio.wait_for(
        proc.communicate(), timeout=float(effective_timeout)
    )
except TimeoutError:
    proc.kill()
    await proc.wait()
    return ToolResult(ok=False, error=f"Command timed out after {effective_timeout}s")
finally:
    stop_event.set()
    if heartbeat_task:
        await heartbeat_task
```

---

## 数据流

### LLM 收到的输出对比

| 场景 | 改前 | 改后 |
|------|------|------|
| `mv a b` 成功 | `"Command exited with code 0, no output"` | `"Done"` |
| `grep foo bar` 返回 1 | stderr 当错误展示 | `"(exit 1: No matches found (not an error))"` |
| 命令跑 10s | 无信号 | App 收到 3 次心跳（3s/6s/9s）|
| 任意命令有 description | 无 | `logger.debug` 记录 |

### App 收到的 SSE 事件（进度心跳）

```json
{
  "type": "tool.running",
  "data": {
    "session_id": "2026-...",
    "tool_id": "toolu_xxx",
    "name": "Bash",
    "input": {"command": "npm run build", "description": "Build Android project"},
    "elapsed_seconds": 6,
    "ts": "2026-04-14T10:00:06Z"
  }
}
```

App 判断 `data.elapsed_seconds` 存在即为进度心跳，展示"执行中 (6s)"。

---

## 错误处理

| 情况 | 处理方式 |
|------|---------|
| 心跳 publish 抛异常 | `logger.warning` 吞掉，命令正常继续 |
| 命令 < 3s 完成 | `stop_event` 提前 set，心跳协程从未发出事件，零副作用 |
| TimeoutError | finally 中 set stop_event，heartbeat_task await 后退出 |
| `_current_tool_ctx` 未设置（单测） | `ctx` 为 None，跳过心跳，无副作用 |
| `progress_cb` 为 None | 跳过心跳任务创建 |

---

## 测试覆盖

| 测试 | 验证点 |
|------|--------|
| `test_bash_silent_command_empty_hint` | `mv` 无输出时 `empty_hint == "Done"` |
| `test_bash_nonsilent_command_empty_hint` | `python` 无输出时含 exit code 信息 |
| `test_bash_grep_exit_1_interpretation` | grep 返回 1 时 display 含语义解释 |
| `test_bash_grep_exit_0_no_interpretation` | grep 返回 0 时无多余附加信息 |
| `test_bash_diff_exit_1_interpretation` | diff 返回 1 时语义化 |
| `test_bash_description_logged` | description 写入 logger.debug，不进 output |
| `test_bash_heartbeat_fires` | 命令耗时 > 3s 时 progress_cb 被调用 |
| `test_bash_heartbeat_no_fire_short_command` | 命令 < 3s 时 progress_cb 从未调用 |
| `test_bash_no_ctx_no_heartbeat` | 无 _current_tool_ctx 时正常执行，无副作用 |

---

## 实现顺序

1. `permissions/types.py` — 加 `progress_cb` 字段
2. `core/base_agent.py` — 绑定 `progress_cb`
3. `capabilities/tools/bash/__init__.py` — 实现 4 个功能点
4. 单测

每步独立可测，不影响现有功能。
