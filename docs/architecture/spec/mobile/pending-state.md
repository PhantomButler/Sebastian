---
version: "1.0"
last_updated: 2026-04-23
status: implemented
---

# Chat PENDING 状态与即时停止

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 概述

修复对话页「用户按下发送 → 首个 SSE block 到达」之间的视觉空窗与不可取消两个体验问题。把「REST 在飞」和「REST 200 → 首 block」合并为一个语义——**PENDING（等待中、可停止）**。

---

## 2. 问题

按下发送后链路：

```
sendMessage()  → composerState=SENDING, agentAnimState=IDLE
REST 200       → composerState=IDLE_EMPTY（发送按钮立刻置灰）
首个 SSE block → composerState=STREAMING, agentAnimState=THINKING/STREAMING/WORKING
```

- **空窗期**（REST 200 → 首 block）顶部 AgentPill 处于 COLLAPSED 无动画、发送按钮已置灰
- **无法即时停止**：SendButton 只在 `STREAMING` 才显示停止图标；SENDING / IDLE_EMPTY 期间不可操作

---

## 3. 状态机变化

### ComposerState

```
IDLE_EMPTY / IDLE_READY / PENDING / STREAMING / CANCELLING
```

- 移除 `SENDING`，由 `PENDING` 统一表达「已发出、等待后端首个 block」
- `PENDING` 跨越：按下发送 → REST 返回 → 首个 SSE block 到达之前

### AgentAnimState

```
IDLE / PENDING / THINKING / STREAMING / WORKING
```

- 新增 `PENDING`，与 `ComposerState.PENDING` 同步起止

---

## 4. 后端竞态兜底（`_pending_cancel_intents`）

### 问题

`POST /api/v1/sessions/{id}/turns` 是 fire-and-forget：REST 立即返回 200，`run_streaming` 在后台多段 `await` 后才把 `_stream_inner` task 登记进 `_active_streams[session_id]`。

PENDING 期间 SendButton 即刻可点停止，若用户在 REST 200 到 `_active_streams` 登记之间点停止 → `cancel_session()` 读到 `None` → gateway 返回 404，后端 turn 仍在跑。

### 方案

在 `BaseAgent` 新增 `_pending_cancel_intents: dict[str, CancelIntent]`：

- **`cancel_session`**：流未登记或已完成时，写入 `_pending_cancel_intents`，返回 `True`（gateway 回 200）
- **`run_streaming`**：登记 `_active_streams` 后立即 `pop` 预取消记录，若存在则 `cancel` 当前 stream
- **TTL 清理**：60s 定时器自清未被消费的条目，避免内存泄漏

```
三段式取消生命周期：
_pending_cancel_intents（预取消）→ _cancel_requested（进行中）→ _completed_cancel_intents（已完成）
```

> **实现状态**：已完整实现，含 60s TTL 清理（`_schedule_pending_cancel_cleanup` / `_expire_pending_cancel`）。`core/README.md` 已记录语义与生命周期。

---

## 5. 行为改造点

| 触发点 | 改后 |
|--------|------|
| `sendMessage()` 入口 | `composerState=PENDING`，`agentAnimState=PENDING` |
| `sendTurn.onSuccess` | 不再改 composerState / agentAnimState，只做 sessionId 切换与 SSE 建连 |
| 首个 BlockStart 事件 | 转 `STREAMING`，自然离开 PENDING |
| `sendTurn.onFailure` | `composerState=IDLE_READY`，记录 error |
| 流中 `connectionFailed` | PENDING 状态下也回 `IDLE_EMPTY`（防止卡死） |

### 5.1 PENDING 退出时机

退出 PENDING = **首个 BlockStart 事件**（ThinkingBlockStart / TextBlockStart / ToolBlockStart），不是更早的 `TurnReceived`。

- `TurnReceived` 只做 silent ack（保持 `pendingTurnSessionId` / `currentAssistantMessageId`，不切状态）
- Pill 动画递进：`COLLAPSED → BREATHING → THINKING/ACTIVE`，无中间跳变

---

## 6. SendButton 视觉

| state | 图标 | tint | 可点 |
|-------|------|------|------|
| IDLE_EMPTY | 发送 | Neutral | 否 |
| IDLE_READY | 发送 | Primary | 是 |
| **PENDING** | **停止** | **Neutral 玻璃圆** | **是** |
| STREAMING | 停止 | Primary | 是 |
| CANCELLING | 进度环 | Neutral | 否 |

> **实现差异**：spec 原文 PENDING 图标 tint 为 Primary，代码实现为 Neutral 玻璃圆样式（注释明确标注 `PENDING | Neutral 玻璃圆 + 停止图标 | 是`）。

---

## 7. AgentPill BREATHING 模式

`AgentAnimState.PENDING` 映射到 `AgentPillMode.BREATHING`，由 `BreathingHalo` composable 渲染：

- **形态**：整个 pill 的边缘 halo 做彩虹渐变呼吸
- **渐变色**：`#6FC3FF → #9F7BFF → #7BE0D1 → #6FC3FF` 环形 gradient，每 2.4s 旋转 360°
- **呼吸**：halo alpha 在 0.35 ↔ 0.75 之间呼吸，周期 1.6s
- **档位切换**：IDLE → BREATHING 沿用 `animateContentSize` + `AnimatedContent` crossfade；BREATHING → THINKING/ACTIVE 沿用 80ms 防抖

详见 [agent-pill-animation.md](agent-pill-animation.md) §3 状态映射与 §8 BreathingHalo 动画。

---

## 8. 点停止的语义

### 有 sessionId（REST 已返回）

- `composerState=CANCELLING`，调用 `chatRepository.cancelTurn(sessionId)`
- 后端 `_pending_cancel_intents` 竞态兜底保证 cancel 永远成功
- 前端收 `TurnCancelled` 事件走与 `TurnInterrupted` 相同收尾逻辑
- 已显示的用户气泡保留

### 无 sessionId（REST 尚未返回）

- `sendTurnJob?.cancel()` 取消本地协程
- `composerState=IDLE_READY`，保留 Composer 文本（允许重发）
- 已显示的用户气泡保留

> **实现增强**：`sendTurnJob: Job?` 成员变量保存发送协程引用，支持本地取消。

---

## 9. `TurnCancelled` 事件

前端新增 SSE 事件消费：

```kotlin
// StreamEvent.kt
data class TurnCancelled(val sessionId: String, val partialContent: String) : StreamEvent()

// SseFrameDto.kt
"turn.cancelled" -> StreamEvent.TurnCancelled(data.getString("session_id"), data.optString("partial_content", ""))

// ChatViewModel.kt
is StreamEvent.TurnCancelled -> { /* flush deltas → IDLE_EMPTY */ }
```

> **实现差异**：spec 原文 `TurnCancelled` 只有 `sessionId` 字段，代码实现额外包含 `partialContent: String`（部分生成内容，用于展示未完成回复）。

---

## 10. PENDING 超时兜底

REST `sendTurn.onSuccess` 之后启动 15s 计时：

- 期间收到任何 SSE 事件 → 取消计时
- 15s 内无事件 → 通过 `ToastCenter` 提示「响应较慢，可点停止后重试」
- **不自动中断**，只给可读信号

**前台累计计时**：

- `onAppStop`：记录已走时长并 cancel 计时 Job
- `onAppStart`：若 `composerState == PENDING` 且已走时长 < 15s → 以剩余时长重启

---

## 11. 离线 / 后台恢复

`onAppStart` 若 `composerState == PENDING`：

- 调 `chatRepository.getMessages(activeSessionId)`：
  - 最新 assistant 已完成 → 强制 `IDLE_EMPTY`，重建 SSE
  - 否则 → 保持 PENDING，SSE 回放自然退出
- `activeSessionId == null`：保持 PENDING 等协程自然恢复

---

## 12. 涉及文件

| 文件 | 改动 |
|------|------|
| `viewmodel/ChatViewModel.kt` | 状态机改写（SENDING → PENDING），`sendTurnJob`，`pendingTimeoutJob`，`TurnCancelled` 处理 |
| `ui/composer/SendButton.kt` | PENDING 映射停止图标 + 可点 |
| `ui/chat/AgentPill.kt` | BREATHING mode 映射 |
| `ui/chat/AgentPillAnimations.kt` | `BreathingHalo` composable |
| `ui/theme/Color.kt` | 彩虹辅色（紫 / 青） |
| `data/model/StreamEvent.kt` | `TurnCancelled` 事件子类 |
| `data/remote/dto/SseFrameDto.kt` | `"turn.cancelled"` parser 分支 |
| `sebastian/core/base_agent.py` | `_pending_cancel_intents` + TTL 清理 + `run_streaming` 消费 |

---

## 13. 测试

### 后端

- 流未登记时 `cancel_session` → 写入 `_pending_cancel_intents`，返回 True
- `run_streaming` 登记 `_active_streams` 后消费预取消 → 立即 cancel → 发 `turn.cancelled`
- `_pending_cancel_intents` 60s TTL 到期自清
- 现有 cancel 路径语义不变

### 前端

- `sendMessage` → PENDING；`onSuccess` 后仍为 PENDING
- 首个 BlockStart 转 STREAMING；TurnReceived 不触发切换
- PENDING 下有 sessionId 走 `/cancel`；无 sessionId 走 `sendTurnJob?.cancel()`
- `TurnCancelled` 事件走等价于 `TurnInterrupted` 收尾
- 15s 超时触发提示；收到事件取消计时
- `onAppStart` PENDING 分支按最新消息角色决定保持/退回
- 计时器前台累计

---

## 14. 不在本 spec 范围内

- 发送失败自动重试
- 后端 cancel 协议语义变更（intent / 事件类型 / 路由均不变）
- 用户消息气泡状态指示器
- 全局 SSE / approval 链路
- PENDING 期间连接失败保留 PENDING + 手动重连优化

---

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
