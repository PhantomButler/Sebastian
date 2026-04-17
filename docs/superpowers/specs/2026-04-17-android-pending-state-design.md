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

## 4. 行为改造点

| 触发点 | 现状 | 改后 |
|--------|------|------|
| `sendMessage()` 入口 | `composerState=SENDING`，`agentAnimState=IDLE` | `composerState=PENDING`，`agentAnimState=PENDING` |
| `sendTurn.onSuccess` | 立即 `composerState=IDLE_EMPTY`（导致按钮置灰） | **不再改 composerState / agentAnimState**，只做 sessionId 切换与 SSE 建连 |
| 首个 block 事件（Thinking/Text/Tool BlockStart） | 转 `STREAMING`，切对应 agentAnimState | 同现 —— 自然离开 PENDING |
| `sendTurn.onFailure` | `composerState=IDLE_READY`，记录 error | 同现 |
| 流中 `connectionFailed` 重置 | 若 `SENDING`/`STREAMING` 回 `IDLE_EMPTY` | 把 `SENDING` 换成 `PENDING` 的判断；**PENDING 状态下连接失败也回 `IDLE_EMPTY`**（防止 PENDING 卡死） |

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

## 8. PENDING 超时兜底

REST `sendTurn.onSuccess` 之后启动一个 15s 计时：

- 期间收到任何 SSE 事件（不仅首 block，任何事件都算）→ 取消计时
- 15s 内无任何事件 → 通过现有 `ToastCenter` 或 `ErrorBanner` 提示「响应较慢，可点停止后重试」
- **不自动中断**，只给出可读的信号；用户可选择继续等或点停止

计时状态保存在 ChatViewModel 内部，session 切换 / cancel / TurnResponse / TurnInterrupted / TurnCancelled 时清除。

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
| `viewmodel/README.md` | 更新状态机表格 |
| `../../sebastian/gateway/routes/README.md` | 补充 `POST /sessions/{id}/cancel` 端点文档（当前缺失） |

## 10. 测试策略

- **单元测试**（`viewmodel/ChatViewModelTest`）：
  - sendMessage → composerState = PENDING、agentAnimState = PENDING
  - sendTurn.onSuccess 后 composerState 仍为 PENDING
  - 首个 ThinkingBlockStart / TextBlockStart / ToolBlockStart 事件到达后转 STREAMING
  - PENDING 下 cancelTurn 走 `/cancel` 分支；无 sessionId 时本地取消且保留 Composer 文本
  - 15s 超时触发提示 flow；收到任意事件可取消计时
- **UI 预览**（Compose Preview）：AgentPill 四档（COLLAPSED / BREATHING / THINKING / ACTIVE）静态截图，BreathingHalo 单独预览
- **联调验证**：本地 gateway + 模拟器，手动触发三种路径（慢 LLM / 正常 / cancel）观察 pill + 按钮过渡

## 11. 非目标（YAGNI）

- 不做「发送失败自动重试」
- 不改后端 cancel 语义（intent、事件类型、路由均保持不变；前端补 `turn.cancelled` 消费不算改后端）
- 不给用户消息气泡加状态指示器（未来编辑消息功能会独立处理）
- 不修改全局 SSE / approval 链路

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
