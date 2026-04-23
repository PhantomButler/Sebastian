---
integrated_to: mobile/pending-state.md
integrated_at: 2026-04-23
---

# Android Chat PENDING 状态与即时停止设计

- **日期**：2026-04-17
- **范围**：`ui/mobile-android/`（UI 层 + ChatViewModel 状态机）
- **动机**：修复对话页「用户按下发送 → 首个 SSE block 到达」之间的视觉空窗与不可取消的两个体验问题

## 1. 问题

按下发送后，当前链路：

```
sendMessage()  → composerState=SENDING, agentAnimState=IDLE
REST 200       → composerState=IDLE_EMPTY （发送按钮立刻置灰）
首个 SSE block → composerState=STREAMING, agentAnimState=THINKING/STREAMING/WORKING
```

- **空窗期**（REST 200 → 首 block）顶部 AgentPill 处于 COLLAPSED 无动画、发送按钮已置灰，用户无法判断消息是发成功、正在排队还是出错
- **无法即时停止**：`SendButton` 只在 `ComposerState.STREAMING` 才显示停止图标并可点；SENDING / IDLE_EMPTY 期间按钮不可操作，必须等首个 SSE block 到达
- 后端 `POST /api/v1/sessions/{id}/cancel` 与前端 `ChatViewModel.cancelTurn()` 其实都已支持，卡点完全在 UI 状态机

## 2. 方案总览

把「REST 在飞」和「REST 200 → 首 block」合并为一个语义 —— **PENDING（等待中、可停止）**。覆盖整段空窗，并在顶部 pill 给出呼吸动画、在发送按钮给出可点停止。

## 3. 状态机变化

### ComposerState

```
IDLE_EMPTY / IDLE_READY / PENDING / STREAMING / CANCELLING
```

- 移除 `SENDING`，由 `PENDING` 统一表达「已发出、等待后端首个 block」
- `PENDING` 跨越：按下发送 → REST 返回 → 首个 SSE block 到达之前
- 首个 block 到达时转 `STREAMING`（现有逻辑不变）

### AgentAnimState

```
IDLE / PENDING / THINKING / STREAMING / WORKING
```

- 新增 `PENDING`，与 `ComposerState.PENDING` 同步起止

## 3.5 后端竞态兜底（`_pending_cancel_intents`）

### 问题

`POST /api/v1/sessions/{id}/turns`（与 `/turns`）是 fire-and-forget：REST 立即返回 200，`run_streaming` 在后台先做多段 `await`（LLM provider 解析、session 查找、发 `TURN_RECEIVED`、episodic 加载 / 写入）后，才在 [base_agent.py:344](sebastian/core/base_agent.py:344) 把 `_stream_inner` task 登记进 `_active_streams[session_id]`。

PENDING 期间 SendButton 即刻可点停止，用户若在 REST 200 到 `_active_streams` 登记之间点停止 → `cancel_session()` 读到 `None` → gateway 返回 404，**后端 turn 仍在跑**，首字仍会吐出，前端陷入"刚取消又冒出来"的破碎状态。冷启动 / SQLite 慢 IO / 远程 provider 解析时，该窗口可达数百毫秒。

### 方案

在 `BaseAgent` 新增 `_pending_cancel_intents: dict[str, CancelIntent]`（与现有 `_cancel_requested` 并列但语义不同 —— 前者用于"流尚未登记时的预取消"，后者用于"流在跑时的取消请求"）。

**`cancel_session(session_id, intent)` 调整**（[base_agent.py:606](sebastian/core/base_agent.py:606)）：

```
stream = self._active_streams.get(session_id)
if stream is None or stream.done():
    self._pending_cancel_intents[session_id] = validated_intent  # 登记预取消
    # TTL 清理：asyncio.get_event_loop().call_later(60, _cleanup, session_id)
    return True   # gateway 回 200 ok，前端正常收尾等 turn.cancelled
# …既有逻辑不变
```

**`run_streaming` 登记处调整**（[base_agent.py:335-344](sebastian/core/base_agent.py:335)）：

```
current_stream = asyncio.create_task(self._stream_inner(...))
self._active_streams[session_id] = current_stream
# 兜底：登记前或登记瞬间若已有预取消，立即中止
pending = self._pending_cancel_intents.pop(session_id, None)
if pending is not None:
    self._cancel_requested[session_id] = pending
    current_stream.cancel()
try:
    return await current_stream
# …既有 finally 不变（统一走 cancel 收尾发 turn.cancelled）
```

TTL 清理：`_pending_cancel_intents` 条目若 60s 内未被 `run_streaming` 消费（例如 turn 从未真正启动），定时器自清，避免内存泄漏。

### 属性

- Gateway `/cancel` 端点、`CancelIntent` 枚举、`turn.cancelled` / `turn.response` 事件协议均不变 —— 只补实现竞态
- 前端无需 retry，PENDING 期间 `/cancel` 永远得到 200 + 最终的 `turn.cancelled` 事件
- `_pending_cancel_intents` 与现有 `_cancel_requested` / `_completed_cancel_intents` 组成三段式生命周期：预取消 → 进行中取消 → 已完成取消

## 4. 行为改造点

| 触发点 | 现状 | 改后 |
|--------|------|------|
| `sendMessage()` 入口 | `composerState=SENDING`，`agentAnimState=IDLE` | `composerState=PENDING`，`agentAnimState=PENDING` |
| `sendTurn.onSuccess` | 立即 `composerState=IDLE_EMPTY`（导致按钮置灰） | **不再改 composerState / agentAnimState**，只做 sessionId 切换与 SSE 建连 |
| 首个 block 事件（Thinking/Text/Tool BlockStart） | 转 `STREAMING`，切对应 agentAnimState | 同现 —— 自然离开 PENDING |
| `sendTurn.onFailure` | `composerState=IDLE_READY`，记录 error | 同现 |
| 流中 `connectionFailed` 重置 | 若 `SENDING`/`STREAMING` 回 `IDLE_EMPTY` | 把 `SENDING` 换成 `PENDING` 的判断；**PENDING 状态下连接失败也回 `IDLE_EMPTY`**（防止 PENDING 卡死） |

### 4.1 PENDING 退出时机

退出 PENDING = **首个 BlockStart 事件**（`ThinkingBlockStart` / `TextBlockStart` / `ToolBlockStart`），不是更早的 `TurnReceived`。

- `TurnReceived` 只做 silent ack（保持既有行为：设 `pendingTurnSessionId` / `currentAssistantMessageId`，不切 composerState / agentAnimState）
- 保留 BREATHING 动画覆盖「TurnReceived → 首 Block」这段"已确认收到、正在准备生成"的空档，比过早切 THINKING（此时 LLM 尚未真正推理）更贴近语义
- pill 动画递进：`COLLAPSED → BREATHING → THINKING/ACTIVE` 一次性完成，无中间跳变

## 5. SendButton 视觉

| state | 图标 | tint | 可点 |
|-------|------|------|------|
| IDLE_EMPTY | 发送 | Neutral | 否 |
| IDLE_READY | 发送 | Primary | 是 |
| **PENDING** | **停止** | **Primary** | **是** |
| STREAMING | 停止 | Primary | 是 |
| CANCELLING | 进度环 | Neutral | 否 |

PENDING 与 STREAMING 在按钮层视觉一致（停止图标 + Primary），语义都是「当前 turn 在进行中，点击停止」。

## 6. AgentPill 视觉：多色彩虹呼吸

新增 `AgentPillMode.BREATHING`，由 `AgentAnimState.PENDING` 映射：

- **形态**：不加尾巴动画（不出现光团 / HUD），整个 pill 的边缘 halo 做彩虹渐变呼吸
- **渐变色**：在 accent 蓝 `#6FC3FF` / `#9FD6FF` 基础上扩展为多色循环，例如 `#6FC3FF → #9F7BFF → #7BE0D1 → #6FC3FF` 环形 gradient，每 2.4s 缓慢旋转 360°
- **呼吸**：halo 整体 alpha 在 0.35 ↔ 0.75 之间呼吸，周期 1.6s
- **半径**：与 THINKING / ACTIVE 的发光半径保持一致（不加大）
- **档位切换**：
  - IDLE → BREATHING：沿用现有 `animateContentSize` + `AnimatedContent` crossfade
  - BREATHING → THINKING / ACTIVE：沿用 80ms 防抖后 fade crossfade，halo 淡出、尾部动画淡入

暗主题复用 `AgentAccentDark` 为 gradient 主色基准，亮主题复用 `AgentAccentLight`，附加的紫 / 青辅色新增到 `ui/theme/Color.kt`。

## 7. 点停止的语义

在 PENDING 状态下点击 SendButton：

- 若 `activeSessionId != null`：
  - `composerState=CANCELLING`（与现有 STREAMING 停止一致），调用 `chatRepository.cancelTurn(sessionId)`
  - 后端 `cancel_session()` 默认 intent=`"cancel"`，发出 `turn.cancelled` + `turn.response` 两个 SSE 事件
  - 前端需**新增 `TurnCancelled` 事件处理**（见 §9 改动文件），在 handleEvent 中走与 `TurnInterrupted` 相同的收尾逻辑：flush deltas → `IDLE_EMPTY`
  - 若 `TurnCancelled` 解析缺失，`turn.cancelled` 会被当作 `Unknown` 丢弃，UI 靠后续 `TurnResponse` 事件兜底恢复——功能不坏但语义丢失
  - **已显示的用户气泡保留**，不撤回
- 若 `activeSessionId == null`（首次对话、REST 尚未返回）：
  - 直接取消本地 `sendTurn` 协程，不经过 CANCELLING（没有远端请求可等）
  - **前置条件**：`sendMessage()` 需将 `sendTurn` 的 `Job` 保存为 ViewModel 成员变量（如 `sendTurnJob`），以便在此处调用 `sendTurnJob?.cancel()`
  - `composerState=IDLE_READY`，保留 Composer 文本（允许用户重发或编辑）
  - **已显示的用户气泡保留**，不撤回
  - 为后续编辑消息功能预留：下一轮从（未来可编辑的）用户消息继续

### 7.1 离线 / 后台恢复对 PENDING 的处理

- `onAppStop`（`ProcessLifecycleOwner.ON_STOP`）：cancel `sseJob`，**不改 composerState / agentAnimState**（PENDING 语义需要跨越后台期）
- `onAppStart`（`ProcessLifecycleOwner.ON_START`）若当前 `composerState == PENDING`：
  - **不走 `switchSession`**（会全量清空消息 + 重置状态，破坏用户视觉上下文）
  - 调一次 `chatRepository.getMessages(activeSessionId)`：
    - 若最新一条 role == assistant 且 `done == true` → 后台期 turn 已完成 → 强制 `composerState = IDLE_EMPTY`，`agentAnimState = IDLE`，重建 SSE 连接（`Last-Event-ID` 回放剩余事件）
    - 否则（最新仍是 user 或 assistant 未完成）→ 保持 PENDING，重建 SSE 连接由 `Last-Event-ID` 回放补齐事件，首个 BlockStart 会自然退出 PENDING
  - `activeSessionId == null`（PENDING 期间 REST 尚未返回就切后台）：极小概率场景，onAppStart 无 session 可查，保持 PENDING 等 `sendTurn` 协程自然恢复（`viewModelScope` 的协程在后台挂起时 IO 仍可能完成）或用户手动停止

## 8. PENDING 超时兜底

REST `sendTurn.onSuccess` 之后启动一个 15s 计时：

- 期间收到任何 SSE 事件（不仅首 block，任何事件都算）→ 取消计时
- 15s 内无任何事件 → 通过现有 `ToastCenter` 或 `ErrorBanner` 提示「响应较慢，可点停止后重试」
- **不自动中断**，只给出可读的信号；用户可选择继续等或点停止

计时状态保存在 ChatViewModel 内部，session 切换 / cancel / TurnResponse / TurnInterrupted / TurnCancelled 时清除。

**前台累计计时**：计时器以"前台累计时长"为准，不计后台时间：

- `onAppStop`：若计时器在跑 → 记录已走时长并 cancel 计时 `Job`
- `onAppStart`：若 `composerState == PENDING` 且已走时长 < 15s → 以剩余时长（15s - 已走）重启计时
- 避免用户切后台后回来就立刻看到"响应较慢"提示

## 9. 涉及改动文件

| 文件 | 改动 |
|------|------|
| `viewmodel/ChatViewModel.kt` | 状态机改写（SENDING → PENDING），onSuccess 不再重置 composerState，新增 PENDING 超时计时，保存 `sendTurnJob` 供本地取消，新增 `TurnCancelled` 处理分支 |
| `ui/composer/SendButton.kt` | PENDING 映射到停止图标 + 可点 |
| `ui/chat/AgentPill.kt` | 新增 BREATHING mode |
| `ui/chat/AgentPillAnimations.kt` | 新增 `BreathingHalo` composable（彩虹 gradient + alpha 呼吸） |
| `ui/theme/Color.kt` | 新增彩虹辅色（紫 / 青） |
| `data/model/StreamEvent.kt` | 新增 `TurnCancelled` 事件密封子类（`data class TurnCancelled(val sessionId: String) : StreamEvent()`） |
| `data/remote/dto/SseFrameDto.kt` | SSE parser 新增 `"turn.cancelled"` → `StreamEvent.TurnCancelled` 分支 |
| `viewmodel/README.md` | 更新状态机表格；补充 `onAppStart` PENDING 分支说明 |
| `../../sebastian/core/base_agent.py` | 新增 `_pending_cancel_intents: dict[str, CancelIntent]` 与 TTL 清理；`cancel_session` 在流未登记时写入预取消；`run_streaming` 登记 `_active_streams` 后消费预取消立即 cancel |
| `../../sebastian/core/README.md` | 记录 `_pending_cancel_intents` 语义与三段式取消生命周期 |
| `../../sebastian/gateway/routes/README.md` | 补充 `POST /sessions/{id}/cancel` 端点文档（当前缺失） |

## 10. 测试策略

- **后端单元测试**（`tests/unit/core/test_base_agent_cancel.py`）：
  - 流尚未登记时调 `cancel_session` → 写入 `_pending_cancel_intents`，返回 True
  - `run_streaming` 登记 `_active_streams` 后若 `_pending_cancel_intents` 有记录 → 立即 cancel → 发 `turn.cancelled`
  - `_pending_cancel_intents` 60s TTL 到期自清
  - 现有 cancel 路径（流在跑时 cancel）语义不变
- **后端集成测试**（`tests/integration/gateway/test_gateway_sessions.py`）：
  - `POST /turns` 返回 200 后立刻 `POST /sessions/{id}/cancel` → 不 404，session stream 收到 `turn.cancelled` 事件
  - 对上述两种路径断言最终 `_active_streams` / `_pending_cancel_intents` 均被清空
- **前端单元测试**（`viewmodel/ChatViewModelTest`）：
  - sendMessage → composerState = PENDING、agentAnimState = PENDING
  - sendTurn.onSuccess 后 composerState 仍为 PENDING
  - 首个 ThinkingBlockStart / TextBlockStart / ToolBlockStart 事件到达后转 STREAMING；`TurnReceived` 不触发切换
  - PENDING 下 cancelTurn 走 `/cancel` 分支；无 sessionId 时 `sendTurnJob?.cancel()` 且保留 Composer 文本 + 用户气泡
  - `turn.cancelled` 事件走 `TurnCancelled` 分支，等价于 `TurnInterrupted` 收尾
  - 15s 超时触发提示 flow；收到任意事件可取消计时
  - `onAppStart` 在 PENDING 下调 `getMessages` 并按最后一条消息角色决定保持 / 退回 IDLE_EMPTY
  - 计时器前台累计：onAppStop 暂停、onAppStart 按剩余时长重启
- **UI 预览**（Compose Preview）：AgentPill 四档（COLLAPSED / BREATHING / THINKING / ACTIVE）静态截图，BreathingHalo 单独预览
- **联调验证**：本地 gateway + 模拟器，手动触发四种路径（慢 LLM / 正常 / PENDING 期间 cancel / PENDING 期间切后台再回来）观察 pill + 按钮过渡

## 11. 非目标（YAGNI）

- 不做「发送失败自动重试」
- 不改后端 cancel **协议语义**（intent 默认值 / 事件类型 / 路由均保持不变）；后端仅补 `_pending_cancel_intents` 竞态兜底实现（见 §3.5），前端补 `turn.cancelled` 事件消费
- 不给用户消息气泡加状态指示器（未来编辑消息功能会独立处理）
- 不修改全局 SSE / approval 链路
- 不做「PENDING 期间连接失败保留 PENDING + 手动重连」优化：当前 PENDING → IDLE_EMPTY 的安全回退 + SSE 重连事件回放已能自愈，保留 PENDING 需要配套重连 UI，放 follow-up

## 12. 审核发现记录（2026-04-17）

代码审核中发现的问题，已纳入本 spec 对应修正：

### 12.1 `turn.cancelled` SSE 事件不匹配（已纳入 §7、§9）

**问题**：后端 `cancel_session()` 默认 intent=`"cancel"`，发出 `turn.cancelled` 事件。Android 端 `SseFrameParser` 只解析了 `turn.interrupted`（对应 intent=`"stop"`，由 `stop_agent` 工具发出），**不认识 `turn.cancelled`**。`StreamEvent` 也缺少 `TurnCancelled` 子类。

**影响**：用户点停止后，`turn.cancelled` 被当作 `Unknown` 丢弃，UI 靠后续 `turn.response` 事件兜底恢复。功能不坏，但 cancel 语义丢失。

**修正**：前端新增 `StreamEvent.TurnCancelled` + parser 分支 + handleEvent 处理。详见 §7、§9。

### 12.2 `activeSessionId == null` 本地取消需保存 Job 引用（已纳入 §7）

**问题**：当前 `cancelTurn()` 遇 `activeSessionId == null` 直接 `return`（不操作）。Spec 要求"直接取消本地 `sendTurn` 协程"，但 `sendMessage()` 未保存 `sendTurn` 的 `Job` 引用，无法从外部取消。

**修正**：`sendMessage()` 中将 `chatRepository.sendTurn(...)` 的协程 Job 保存为 `sendTurnJob: Job?` 成员变量。PENDING 下无 sessionId 时调用 `sendTurnJob?.cancel()`。

### 12.3 `connectionFailed` 需覆盖 PENDING 回退（已纳入 §4）

**问题**：当网络中断导致 SSE 连接失败时，现有逻辑将 `SENDING`/`STREAMING` 回退到 `IDLE_EMPTY`。新增 `PENDING` 后，如果 PENDING 状态下连接失败也需要同样回退，否则 PENDING 会卡死（按钮一直显示停止但实际无法操作）。

**修正**：`connectionFailed` 处理中把 `SENDING` 的判断改为 `PENDING`，确保覆盖。

### 12.4 后端 routes README 文档缺失（已纳入 §9）

**问题**：`sebastian/gateway/routes/README.md` 的修改导航表遗漏了 `POST /sessions/{id}/cancel` 端点（实现在 `sessions.py:389-403`），只列出了 task-level 的 cancel 端点。

**修正**：补充该端点文档。

### 12.5 后端 `_active_streams` 登记竞态（已纳入 §3.5、§9、§10）

**问题**：`POST /turns` 是 fire-and-forget，REST 200 立刻返回，但 `run_streaming` 要跨多段 await 后才把 `_stream_inner` task 登记进 `_active_streams`（[base_agent.py:302-344](sebastian/core/base_agent.py:302)）。PENDING 期间 SendButton 即可点停止，若用户在 REST 200 到 `_active_streams` 登记之间点停止 → `cancel_session()` 读到 None → gateway 404，后端 turn 仍在跑，首字仍会吐出。

**影响**：前端陷入"刚取消又冒出来"的破碎状态；冷启动 / SQLite 慢 IO / 远程 provider 解析时窗口达数百毫秒，非罕见。

**方案对比**：

| 方向 | 正确性 | 失败路径 | 采用 |
|------|-------|---------|------|
| 前端 retry + 本地降级 | 概率性（retry 预算覆盖不了冷启动窗口） | retry 耗尽后本地取消，后端 turn 脱缰继续跑 | ✗ |
| 后端 `_pending_cancel_intents` | 确定性，无 race | gateway 永远 200 + 最终 `turn.cancelled` | ✓ |

**修正**：后端加 `_pending_cancel_intents: dict[str, CancelIntent]` 预取消表（带 60s TTL），`cancel_session` 在流未登记时写入、`run_streaming` 登记后立即消费。Intent / 事件类型 / 路由协议不变。详见 §3.5。
