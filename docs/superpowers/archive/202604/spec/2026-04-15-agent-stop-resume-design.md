---
version: "1.0"
last_updated: 2026-04-16
status: implemented
integrated_to: gateway/agent-stop-resume.md
integrated_at: 2026-04-17
---

# Sub-Agent 生命周期控制：stop_agent + resume_agent

## 1. 背景与动机

当前架构（[three-tier-agent.md](../../architecture/spec/overview/three-tier-agent.md)）下，Sebastian 可以向下委派任务，但**无法主动中断或暂停已委派的 sub-agent session**。现有工具集只有：

- `delegate_to_agent` / `spawn_sub_agent` — 创建新 session
- `check_sub_agents` / `inspect_session` — 只读查看
- `reply_to_agent` — 仅对 `SessionStatus.WAITING`（sub-agent 主动让出）的 session 有效

一旦委派发出，Sebastian 只能被动等待 sub-agent 跑完或自己进入 WAITING。当出现以下情况时没有对应操作：

- 用户改主意，之前委派的任务已过时
- 上级发现方向错误，需要止损
- 需要暂停 sub-agent，和用户确认后再决定继续还是放弃

本 spec 补齐这一控制链路：新增 `stop_agent` 工具，改名并扩展 `reply_to_agent` 为 `resume_agent`。

### 不在本次范围

- **用户干预信号同步给 Sebastian**：用户在 sub-agent session 按暂停或插话时，当前不主动通知 Sebastian。未来如有需要再设计。
- **Sebastian 向运行中（ACTIVE）session 追加消息**：架构上不支持，本次不引入。
- **停止时 tool_call 的原子性保护**：沿用现有 `BaseAgent.cancel_session` 的硬中断语义，tool 调用中间态风险是既有问题，后续专项处理。

---

## 2. 设计概览

### 2.1 两个工具

| 工具 | 调用者 | 作用 |
|------|--------|------|
| `stop_agent(agent_type, session_id, reason="")` | Sebastian、组长 | 将指定 sub-agent session 从 `ACTIVE` 推进 `IDLE`，打断当前 stream，保留上下文可恢复 |
| `resume_agent(agent_type, session_id, instruction="")` | Sebastian、组长 | 将 `WAITING` 或 `IDLE` 的 session 恢复为 `ACTIVE` 并重启 run loop，可选追加指令 |

两个工具都以 `agent_type` 作首参，与 `delegate_to_agent` 签名风格对齐。后端会交叉校验传入的 `agent_type` 与 session 实际 `agent_type` 是否一致，不一致返回明确错误（见 §3.5、§4.4），顺便捕获 LLM 引用错误 session 的 bug。

`resume_agent` 取代现有 `reply_to_agent`（彻底改名，不保留别名）。

### 2.2 状态机位置

复用现有 `SessionStatus` 枚举（sebastian/core/types.py:28-37），**不新增状态**。利用既有边：

```
ACTIVE → IDLE          （stop_agent 推入）
IDLE   → ACTIVE        （resume_agent 恢复，原有边）
WAITING → ACTIVE       （resume_agent 恢复，原有边，原 reply_to_agent 语义）
```

### 2.3 与 cancel 的区别

- `stop_agent` → `IDLE`：暂停，保留上下文，**可恢复**。用于"也许之后继续"。
- 用户或系统取消 → `CANCELLED`：终止，不可恢复。session 走到终态。

Sebastian **不需要**主动 cancel 的能力——如果确定不再继续，让 session 停在 IDLE 直到自然归档即可。真正"要终结一个 session"是用户动作或系统生命周期决定，不是 orchestrator 的日常动作。

---

## 3. `stop_agent` 详细设计

### 3.1 签名

```python
@tool(
    name="stop_agent",
    description="暂停指定 sub-agent session 的执行，保留上下文以便恢复。",
    permission_tier=PermissionTier.LOW,
)
async def stop_agent(agent_type: str, session_id: str, reason: str = "") -> ToolResult:
    ...
```

### 3.2 执行步骤

1. **查找 session**：从 `index_store` 取 session 元信息，不存在则返回错误
2. **agent_type 交叉校验**：传入 `agent_type` 必须等于 session 实际 `agent_type`，不一致返回明确错误（见 §3.5）
3. **权限校验**：
   - Sebastian（depth=1）：可停任何 depth=2 或 depth=3 session
   - 组长（depth=2）：只能停 `parent_session_id == 当前 session_id` 的 depth=3 组员
   - 越权返回错误："无权停止该 session"
4. **状态校验**：只接受 `ACTIVE` 或 `STALLED`。其他状态（已是 IDLE/WAITING/COMPLETED 等）返回错误或幂等跳过（见 §3.3）
5. **打断执行**：取到 `state.agent_instances[agent_type]`，调 `agent.cancel_session(session_id, intent="stop")`（见 [sebastian/core/base_agent.py](../../../sebastian/core/base_agent.py) 中 `BaseAgent.cancel_session`）。这会 cancel `_active_streams` 里该 session 的 asyncio.Task
6. **写状态**：`session.status = IDLE`，`session_store.update_session` + `index_store.upsert`
7. **追加 system message**：向 session 对话历史追加一条 role=system 的消息：`[上级暂停] reason: {reason}`（reason 为空则省略 reason 部分）。这条消息在下次 resume 时会进入 LLM context，让 sub-agent 感知"自己被停过"
8. **发事件**：`EventType.SESSION_PAUSED`（新增，见 §5），payload 包含 `session_id, stopped_by, reason`
9. **返回**：`ToolResult(ok=True, output="已暂停 session {session_id}")`

### 3.3 幂等性

同一 session 重复 `stop_agent`：

- 已在 IDLE：返回 `ok=True, output="session 已是 IDLE 状态"`（幂等成功，不重复写历史）
- 已在 CANCELLED/COMPLETED/FAILED：作为失败返回（见 §3.5）

### 3.5 失败返回规范

所有失败路径的 `ToolResult.error` 必须显式告诉模型：**发生了什么 + 是否可重试 + 下一步动作**。参考 `delegate_to_agent/__init__.py:13-16` 的 `_MISSING_CONTEXT_ERROR` 风格。完整清单：

| 场景 | error 文本 |
|------|-----------|
| `session_id` 不存在 | `"找不到 session: {id}。请用 check_sub_agents 确认当前活跃 session 列表，不要用猜的 id 重试。"` |
| `agent_type` 与 session 实际 agent 不匹配 | `"session {id} 属于 {actual_agent_type}，不是你传入的 {claimed_agent_type}。请重新核对 check_sub_agents 输出里的 agent_type 字段再调用。"` |
| 权限不足（组长越层停 depth=2 或停非自己的组员） | `"无权停止 session {id}：你只能停止自己创建的子代理 session。请向 Sebastian 汇报需要停止该任务。"` |
| session 已终态（COMPLETED/FAILED/CANCELLED） | `"session {id} 已结束（status={status}），无法停止。如需查看结果，使用 inspect_session。"` |
| session 状态非 ACTIVE/STALLED（例如已是 IDLE/WAITING，**非幂等情形**由 §3.3 处理） | 本分支不应触发错误，见 §3.3 幂等处理 |
| agent 实例未初始化 | `"Agent {agent_type} 未初始化。这是运行时异常，请向上汇报，不要重试此工具。"` |
| `ToolCallContext` 缺失 | `"工具未从 agent 执行上下文中调用（内部 ToolCallContext 缺失）。请向上汇报'内部上下文缺失，无法执行 stop_agent'，不要重试此工具。"` |

关键原则：
- **错误里必须带上相关 id/状态值**，让模型能定位到具体对象
- **明确"该不该重试"**：能修正的（id 错、权限错）鼓励调其他工具澄清；不能修正的（运行时缺失）明确说"不要重试"
- **给下一步建议**：指向具体工具（check_sub_agents / inspect_session）或行为（向用户汇报）

### 3.4 与 cancel_session 底层的关系

`BaseAgent.cancel_session` 原语行为：把 session 加入 `_cancel_requested` 集合，cancel 对应 asyncio.Task，run loop 的 finally 块发 `TURN_CANCELLED` 事件并把 status 置为 `CANCELLED`。

**关键改动**：run loop 的 finally 需要区分"cancel 的意图"——如果是 `stop_agent` 触发的 cancel，最终 status 应该是 `IDLE` 而不是 `CANCELLED`。

实现方式：给 `_cancel_requested` 集合改为 `_cancel_requested: dict[str, Literal["cancel", "stop"]]`，finally 根据值决定终态。

---

## 4. `resume_agent` 详细设计

### 4.1 演化自 `reply_to_agent`

原 `reply_to_agent`（sebastian/capabilities/tools/reply_to_agent/__init__.py）负责"向 WAITING session 追加指令并重启 run loop"。`resume_agent` 在此基础上做两处扩展：

1. **接受状态扩展**：`WAITING | IDLE` 都可恢复（原来只接受 WAITING）
2. **instruction 可空**：空字符串表示"按原计划继续"，不向历史追加消息；非空才 append

### 4.2 签名

```python
@tool(
    name="resume_agent",
    description="恢复暂停（IDLE）或等待（WAITING）状态的 sub-agent，可选追加指令。",
    permission_tier=PermissionTier.LOW,
)
async def resume_agent(agent_type: str, session_id: str, instruction: str = "") -> ToolResult:
    ...
```

### 4.3 执行步骤

1. **查找 session**：同 stop_agent
2. **agent_type 交叉校验**：同 stop_agent，不一致返回明确错误
3. **权限校验**：同 stop_agent 的分层规则
4. **状态校验**：`session.status in {WAITING, IDLE}`，否则返回错误
5. **可选追加消息**：`instruction != ""` 时，`session_store.append_message(role="user", content=instruction)`；为空则跳过
6. **状态切回 ACTIVE**：`session.status = ACTIVE`，update + upsert
7. **重启 run loop**：`asyncio.create_task(run_agent_session(...))`，callback 记录失败
8. **发事件**：`EventType.SESSION_RESUMED`（新增，见 §5）
9. **返回**：`ToolResult(ok=True, output="已恢复 session {session_id}")`

### 4.4 失败返回规范

同 §3.5 原则。完整清单：

| 场景 | error 文本 |
|------|-----------|
| `session_id` 不存在 | `"找不到 session: {id}。请用 check_sub_agents 确认当前活跃 session 列表。"` |
| `agent_type` 与 session 实际 agent 不匹配 | `"session {id} 属于 {actual_agent_type}，不是你传入的 {claimed_agent_type}。请重新核对 check_sub_agents 输出。"` |
| 权限不足 | `"无权恢复 session {id}：你只能恢复自己创建的子代理 session。"` |
| session 状态不是 WAITING/IDLE | `"session {id} 当前 status={status}，无需恢复。ACTIVE 状态说明它正在执行，COMPLETED/FAILED/CANCELLED 说明已结束；请用 inspect_session 查看详情后再决定。"` |
| agent 实例未初始化 | `"Agent {agent_type} 未初始化。这是运行时异常，请向上汇报，不要重试此工具。"` |
| session 数据文件丢失 | `"找不到 session 数据: {id}。数据可能已被清理，请用 check_sub_agents 重新列出。"` |
| `ToolCallContext` 缺失 | `"工具未从 agent 执行上下文中调用（内部 ToolCallContext 缺失）。请向上汇报'内部上下文缺失，无法执行 resume_agent'，不要重试此工具。"` |

### 4.5 迁移步骤

1. 目录重命名：`sebastian/capabilities/tools/reply_to_agent/` → `resume_agent/`
2. 工具 `name` 字段改为 `"resume_agent"`
3. description 改为 §4.2 所述
4. 状态校验逻辑和 instruction 处理按 §4.1-4.3 调整
5. 测试文件：`tests/unit/capabilities/test_tool_reply_to_agent.py` → `test_tool_resume_agent.py`，用例扩展 IDLE 恢复路径和空 instruction 路径
6. 所有引用 `reply_to_agent` 的 prompt / allowed_tools 配置一次性改名（见 §6）
7. **不保留别名**：彻底删除 `reply_to_agent` 工具名

---

## 5. 事件类型

在 `sebastian/protocol/events/types.py` Session lifecycle 区段新增两项：

```python
SESSION_PAUSED  = "session.paused"    # stop_agent 触发
SESSION_RESUMED = "session.resumed"   # resume_agent 触发
```

Payload 字段：

| 字段 | SESSION_PAUSED | SESSION_RESUMED |
|------|---------------|----------------|
| session_id | ✓ | ✓ |
| agent_type | ✓ | ✓ |
| stopped_by / resumed_by | 触发方 session_id（Sebastian 或组长） | 同左 |
| reason / instruction | reason 文本（可空） | instruction 文本（可空） |
| from_status | — | 原状态（WAITING / IDLE） |
| timestamp | ✓ | ✓ |

事件消费方暂时只有日志和未来可能的 UI 标记。**本次不接入 Sebastian 的感知链路**（动作 B 不做）。

### 5.1 `TURN_INTERRUPTED`（turn 粒度补充）

`SESSION_PAUSED` 是 session 粒度的语义事件，由 `stop_agent` 工具发出；但 `BaseAgent.run_turn_streaming`
在 stop 分支额外会发出 **turn 粒度**的 `TURN_INTERRUPTED` 事件，用来把"当前这一轮流式输出被软中断"的事实暴露给 SSE/UI 层，避免 UI 等不到 `TURN_RESPONSE` 收尾。

- 事件名复用既有 `EventType.TURN_INTERRUPTED`（由 block-level SSE 引入）
- 与 `TURN_CANCELLED` 的区别：`TURN_CANCELLED` 对应硬取消（cancel intent），`TURN_INTERRUPTED` 对应软暂停（stop intent），两者互斥

Payload：

| 字段 | 说明 |
|------|------|
| agent_type | session 所属 agent 类型 |
| intent | 固定为 `"stop"` |
| partial_content | 中断时刻已累积的 partial 文本（可空） |

消费方同上（日志 / UI 标记）。

---

## 6. 工具注册与权限

### 6.1 allowed_tools 配置

受影响的工具可见性配置：

- **Sebastian**（`sebastian/orchestrator/sebas.py`）：allowed_tools 中 `reply_to_agent` → `resume_agent`；新增 `stop_agent`
- **Sub-Agent**（`sebastian/agents/_loader.py`）：`_SUBAGENT_PROTOCOL_TOOLS` 中 `reply_to_agent` → `resume_agent`，并追加 `stop_agent`（对声明了 `allowed_tools` 的 agent 自动注入）

### 6.2 组员（depth=3）

当前实现中 depth=2/3 共用同一套协议工具清单（`_loader.py` 自动注入），因此 depth=3 组员也可见 `resume_agent` / `stop_agent`。实际权限由工具内部基于 `ToolCallContext` 做硬校验（depth>=3 直接拒绝），避免组员管理 sibling 或自身 session。

### 6.3 权限校验实现位置

Sebastian vs 组长的作用域差异（组长只能停自己的组员）**写在工具函数内部**，通过 `ToolCallContext` 拿到调用方的 session 信息，对比目标 session 的 `parent_session_id`。不依赖 allowed_tools 这层做精细控制——allowed_tools 只决定"能不能调"，工具内部决定"能作用于哪些 session"。

### 6.4 App 端显示名

后端 tool 名为 snake_case，Android 客户端需要在 [ToolDisplayName.kt](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt) 加映射（参考已有的 `delegate_to_agent`：`title = "Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}"`），否则卡片 header 直接显示 `stop_agent` 不美观。

由于 `stop_agent` / `resume_agent` 的首参就是 `agent_type`，`ToolCallInputExtractor.extractInputSummary` 会把 `agent_type` 作为 KEY_PRIORITY 第一项取出（`agent_type` 应已在优先级表中，因为 `delegate_to_agent` 也用），所以 `rawSummary` 拿到的就是目标 agent 名。

```kotlin
// 在 ToolDisplayName.resolve() 的 when 里追加
"stop_agent" -> Display(
    title = "Stop Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}",
    summary = "",
)
"resume_agent" -> Display(
    title = "Resume Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}",
    summary = "",
)
```

格式与 `delegate_to_agent` 的 `Agent: Forge` 风格对齐，summary 留空。

确认 [ToolCallInputExtractor.KEY_PRIORITY](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallInputExtractor.kt) 已包含 `agent_type`；如已存在（应该如此，`delegate_to_agent` 已用），无需改动。

**不在后端 @tool 装饰器加 display_name 字段**——现有体系的 PascalCase 直用、snake_case 客户端映射已经覆盖所有情况，引入后端字段属于重复抽象。

---

## 7. 测试要点

### 7.1 stop_agent

- ACTIVE session 被停 → IDLE，run loop cancelled，历史有 system message
- STALLED session 被停 → IDLE
- 重复 stop（IDLE → IDLE）→ 幂等 ok
- 停已 COMPLETED session → 错误，error 文本符合 §3.5 清单
- Sebastian 停 depth=3 组员（跨层）→ 允许
- 组长停非自己的 depth=3 组员 → 拒绝，error 文本符合 §3.5 清单
- 组长停 depth=2 session → 拒绝
- session_id 不存在 → error 文本指向 check_sub_agents
- 每条错误路径单独断言 error 文本包含关键关键字（session id、当前 status、下一步建议），防止退化为模糊错误

### 7.2 resume_agent

- WAITING + 非空 instruction → ACTIVE，追加消息，run loop 重启（原 reply_to_agent 路径回归）
- WAITING + 空 instruction → ACTIVE，不追加消息，run loop 重启
- IDLE + 非空 instruction → ACTIVE，追加消息，run loop 重启
- IDLE + 空 instruction → ACTIVE，不追加消息，run loop 重启
- ACTIVE session 调 resume → 错误，error 文本符合 §4.4 清单
- CANCELLED session 调 resume → 错误
- 权限场景同 stop_agent
- 每条错误路径断言 error 文本包含关键关键字和下一步建议

### 7.3 端到端

stop → resume 往返：session 对话历史完整，sub-agent 在 resume 后看到 `[上级暂停]` system message 并能基于它调整行为。

> 当前状态：单元测试已覆盖 stop/resume 各自的工具路径与 session_runner 状态分叉；完整 stop → resume 往返的集成用例尚未落地，后续视上线反馈补。

---

## 8. 影响面清单

| 文件/模块 | 变更 |
|----------|------|
| `sebastian/core/base_agent.py` | `_cancel_requested` 改为 dict，finally 根据 stop vs cancel 决定终态 |
| `sebastian/core/types.py` | 不需要改（IDLE 已存在）|
| `sebastian/capabilities/tools/reply_to_agent/` | 重命名为 `resume_agent/`，扩展逻辑 |
| `sebastian/capabilities/tools/stop_agent/` | 新建 |
| `sebastian/protocol/events/types.py` | 新增 SESSION_PAUSED / SESSION_RESUMED |
| `sebastian/orchestrator/sebas.py` | allowed_tools 改名 + 新增 stop_agent |
| `sebastian/agents/_loader.py` | `_SUBAGENT_PROTOCOL_TOOLS` 更新为 `resume_agent` + `stop_agent` |
| `tests/unit/capabilities/test_tool_reply_to_agent.py` | 改名 + 扩展用例 |
| `tests/unit/capabilities/test_tool_stop_agent.py` | 新建 |
| `sebastian/capabilities/README.md` | 工具清单更新 |
| `sebastian/capabilities/tools/README.md` | 同上 |
| `sebastian/agents/README.md` | 若涉及 reply_to_agent 描述则更新 |
| `docs/architecture/spec/agents/permission.md` | 若提到 reply_to_agent 则更新 |
| `docs/architecture/spec/overview/three-tier-agent.md` | §3.3 状态机示意补 ACTIVE→IDLE via stop_agent、§5 工具列表补 stop_agent 并把 reply_to_agent 改名 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt` | 新增 stop_agent / resume_agent 两条映射（见 §6.4）|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallInputExtractor.kt` | 若 `KEY_PRIORITY` 未含 `session_id`，追加 |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolCallInputExtractorTest.kt` | 补 session_id 提取用例 |

---

## 9. 既有风险与后续

### 本次不处理但需登记

1. **tool_call 中间态**：`stop_agent` 硬中断正在进行的 tool 调用可能留下副作用（文件半写、请求已发）。需要后续做 tool 层面的原子性/checkpoint 机制。
2. **用户干预 Sebastian 感知链路**：用户在 sub-agent session 按暂停或插话 cancel 时，Sebastian 不知情。后续可能通过 `SESSION_PAUSED`（cancel_by=user 场景复用）+ 注入 Sebastian 的 system context 实现。
3. **Stalled session 的 stop 语义**：STALLED session 可以直接 stop 推入 IDLE，但"stalled"本身意味着 run loop 可能已经没在响应，cancel 是否能生效需要验证。

### 后续相关设计入口

当动作 B（用户干预通知）要做时，在本 spec 基础上扩展即可：`SESSION_PAUSED` 事件携带 `paused_by="user"` 并订阅到 Sebastian context。届时新开 spec。

---

*← 返回 [Specs 根目录](../../superpowers/specs/)*
