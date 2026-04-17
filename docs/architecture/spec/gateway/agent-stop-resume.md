---
version: "1.0"
last_updated: 2026-04-17
status: implemented
---

# Sub-Agent 生命周期控制：stop_agent + resume_agent

*← [Gateway 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与动机

三层 Agent 架构（[three-tier-agent.md](../overview/three-tier-agent.md)）下，Sebastian 可向下委派任务，但无法主动中断或暂停已委派的 sub-agent session。本 spec 补齐控制链路：新增 `stop_agent` 工具，将 `reply_to_agent` 改名并扩展为 `resume_agent`。

---

## 2. 两个工具

| 工具 | 调用者 | 作用 |
|------|--------|------|
| `stop_agent(agent_type, session_id, reason="")` | Sebastian、组长 | 将 sub-agent session 从 `ACTIVE` 推入 `IDLE`，打断当前 stream，保留上下文可恢复 |
| `resume_agent(agent_type, session_id, instruction="")` | Sebastian、组长 | 将 `WAITING` 或 `IDLE` 的 session 恢复为 `ACTIVE` 并重启 run loop，可选追加指令 |

`resume_agent` 取代原有 `reply_to_agent`（彻底改名，不保留别名）。

两个工具都以 `agent_type` 作首参，与 `delegate_to_agent` 签名风格对齐。后端交叉校验传入 `agent_type` 与 session 实际 `agent_type` 是否一致。

---

## 3. 状态机

复用现有 `SessionStatus`，**不新增状态**：

```
ACTIVE → IDLE          （stop_agent 推入）
IDLE   → ACTIVE        （resume_agent 恢复）
WAITING → ACTIVE       （resume_agent 恢复，原 reply_to_agent 语义）
```

与 cancel 的区别：
- `stop_agent` → `IDLE`：暂停，保留上下文，**可恢复**
- 用户/系统取消 → `CANCELLED`：终止，不可恢复

---

## 4. `stop_agent` 设计

### 签名

```python
@tool(
    name="stop_agent",
    description="暂停指定 sub-agent session 的执行，保留上下文以便恢复。",
    permission_tier=PermissionTier.LOW,
)
async def stop_agent(agent_type: str, session_id: str, reason: str = "") -> ToolResult:
    ...
```

### 执行步骤

1. **查找 session**：从 `index_store` 取元信息，不存在返回错误
2. **agent_type 交叉校验**：传入值必须等于 session 实际值，不一致返回明确错误
3. **权限校验**：Sebastian（depth=1）可停任何 depth=2/3 session；组长（depth=2）只能停自己的 depth=3 组员
4. **状态校验**：接受 `ACTIVE` 或 `STALLED`；`IDLE` 幂等返回 ok；终态返回错误
5. **打断执行**：调 `agent.cancel_session(session_id, intent="stop")`，cancel 对应 asyncio.Task
6. **写状态**：`session.status = IDLE`，update + upsert
7. **追加 system message**：`[上级暂停] reason: {reason}`（reason 为空则省略）
8. **发事件**：`EventType.SESSION_PAUSED`

### 幂等性

- 已在 `IDLE`：返回 `ok=True`，不重复写历史
- 已在 `CANCELLED/COMPLETED/FAILED`：作为失败返回

---

## 5. `resume_agent` 设计

### 演化自 `reply_to_agent`

两处扩展：
1. **接受状态扩展**：`WAITING | IDLE` 都可恢复（原来只接受 WAITING）
2. **instruction 可空**：空字符串表示"按原计划继续"，不向历史追加消息

### 签名

```python
@tool(
    name="resume_agent",
    description="恢复暂停（IDLE）或等待（WAITING）状态的 sub-agent，可选追加指令。",
    permission_tier=PermissionTier.LOW,
)
async def resume_agent(agent_type: str, session_id: str, instruction: str = "") -> ToolResult:
    ...
```

### 执行步骤

1. **查找 session** + **agent_type 交叉校验** + **权限校验**：同 stop_agent
2. **状态校验**：`session.status in {WAITING, IDLE}`
3. **可选追加消息**：`instruction != ""` 时 append；为空则跳过
4. **状态切回 ACTIVE** + **重启 run loop**：`asyncio.create_task(run_agent_session(...))`
5. **发事件**：`EventType.SESSION_RESUMED`

---

## 6. 底层改动：cancel intent

`BaseAgent._cancel_requested` 从 `set` 改为 `dict[str, CancelIntent]`，run loop 的 finally 根据意图决定终态：

- `intent="cancel"` → `CANCELLED`
- `intent="stop"` → `IDLE`

---

## 7. 事件类型

`protocol/events/types.py` 新增：

```python
SESSION_PAUSED  = "session.paused"
SESSION_RESUMED = "session.resumed"
```

Payload 字段：

| 字段 | SESSION_PAUSED | SESSION_RESUMED |
|------|---------------|----------------|
| session_id | ✓ | ✓ |
| agent_type | ✓ | ✓ |
| stopped_by / resumed_by | 触发方 session_id | 同左 |
| reason / instruction | reason（可空） | instruction（可空） |
| from_status | — | 原状态（WAITING / IDLE） |

### TURN_INTERRUPTED

`BaseAgent.run_turn_streaming` 在 stop 分支额外发出 turn 粒度的 `TURN_INTERRUPTED` 事件（复用既有 EventType），把"当前这一轮流式输出被软中断"暴露给 SSE/UI 层。

---

## 8. 工具注册

- **Sebastian**（`orchestrator/sebas.py`）：`allowed_tools` 新增 `stop_agent`，`reply_to_agent` → `resume_agent`
- **Sub-Agent**（`agents/_loader.py`）：`_SUBAGENT_PROTOCOL_TOOLS` 同步更新

### Android 显示名

`ToolDisplayName.kt` 新增映射：

```kotlin
"stop_agent" -> Display(
    title = "Stop Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}",
    summary = "",
)
"resume_agent" -> Display(
    title = "Resume Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}",
    summary = "",
)
```

---

## 9. 文件改动清单

| 文件/模块 | 变更 |
|----------|------|
| `sebastian/core/base_agent.py` | `_cancel_requested` 改为 dict，finally 根据 stop vs cancel 决定终态 |
| `sebastian/capabilities/tools/reply_to_agent/` | 重命名为 `resume_agent/`，扩展逻辑 |
| `sebastian/capabilities/tools/stop_agent/` | 新建 |
| `sebastian/protocol/events/types.py` | 新增 SESSION_PAUSED / SESSION_RESUMED |
| `sebastian/orchestrator/sebas.py` | allowed_tools 更新 |
| `sebastian/agents/_loader.py` | `_SUBAGENT_PROTOCOL_TOOLS` 更新 |
| `ui/mobile-android/.../ToolDisplayName.kt` | 新增 stop_agent / resume_agent 映射 |

---

## 10. 不在本 spec 范围内

- 用户干预信号同步给 Sebastian（用户在 sub-agent session 按暂停时，Sebastian 不知情）
- Sebastian 向运行中（ACTIVE）session 追加消息
- 停止时 tool_call 的原子性保护（沿用硬中断语义）

---

*← [Gateway 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
