---
version: "1.0"
last_updated: 2026-04-23
status: implemented
---

# Mobile Timeline Hydration

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 背景

Session storage 迁移到 SQLite 后，后端返回 canonical `timeline_items`。Android App 需要从 REST 读取已持久化的 `timeline_items`，重建为 UI 直接使用的 `Message + ContentBlock`。同时收号新建 session 的实时 SSE race：App 生成 session id，先订阅 stream，再发起 turn。

## 术语

- **REST 历史恢复（hydration）**：App 通过 REST 读取已持久化的 timeline，重建为 `Message + ContentBlock` 的过程。

## 目标

- Chat 页展示完整 session timeline（含 archived 原文和 context summary）。
- REST timeline 是历史事实源；SSE 只负责实时事件和短期 replay 补偿。
- 历史重载后的 UI 与实时 SSE 完成后的 UI 形态一致。
- 新建主对话和 SubAgent session 使用 client-generated session id。
- 发送失败时撤回本地 user bubble，恢复 Composer 文本。

## 后端接口语义

### Timeline 读取

`GET /api/v1/sessions/{session_id}?include_archived=true` 是 App 完整历史接口：

- 返回 `timeline_items`，包含 archived 原文、未归档内容和 `context_summary`。
- `timeline_items` 按真实写入顺序 `seq ASC` 返回。
- `effective_seq` 不参与 App UI 排序，仅服务 LLM context 视图。
- `messages` 继续作为 legacy fallback 返回。

`get_timeline_items()` 实现 audit timeline 语义：按 `seq ASC` 返回真实写入顺序。`get_context_timeline_items()` 继续按 `(effective_seq, seq)` 返回 LLM 当前上下文视图。

### Client-Generated Session ID

主对话 `POST /api/v1/turns` 使用 `SendTurnRequest.session_id`：

- `session_id == null`：后端生成 session id。
- `session_id != null` 且 session 不存在：后端用该 id 创建 session。
- `session_id != null` 且 session 已存在：向该 session 追加 turn。

SubAgent 新建接口 `POST /api/v1/agents/{agent_type}/sessions` 使用 `CreateSessionRequest.session_id`：

- `session_id` 可选，null 时后端生成。
- 传入且不存在：用该 id 创建 SubAgent session，启动初始 turn。
- 传入且已存在且 agent/goal 匹配：返回 `200`，不重复启动。
- 传入但 agent/goal 不匹配：返回 `409 Conflict`。

`GET /api/v1/sessions/{session_id}/stream` 不校验 session 存在性。

## Android 数据模型与映射

### DTO

`SessionDetailResponse` 包含：

```kotlin
val session: SessionDto
val messages: List<MessageDto>
val timelineItems: List<TimelineItemDto> = emptyList()
```

`TimelineItemDto` 覆盖：id, session_id, agent_type, seq, kind, role, content, payload, archived, turn_id, provider_call_index, block_index, created_at。

`ChatRepository.getMessages(sessionId)` 请求 `include_archived=true`，优先使用 `timelineItems`，fallback 到 `messages`。

### Domain Model

`ContentBlock` 包含 `SummaryBlock`：

```kotlin
data class SummaryBlock(
    override val blockId: String,
    val text: String,
    val expanded: Boolean = false,
    val sourceSeqStart: Long? = null,
    val sourceSeqEnd: Long? = null,
) : ContentBlock()
```

### Timeline Mapper

`TimelineMapper.kt` 中 `List<TimelineItemDto>.toMessagesFromTimeline()` 按 `seq ASC` 排序后投影到 `Message`：

- `user_message`：独立 `Message(role=USER)`。
- assistant-side items 按 `(turn_id, provider_call_index)` 聚合为 assistant message。
- `thinking` → `ThinkingBlock(done=true)`。
- `assistant_message` → `TextBlock(done=true)`。
- `tool_call + tool_result` 按 `tool_call_id` 合并为 `ToolBlock`。
- `context_summary` → 独立 assistant message，含 `SummaryBlock`。
- `system_event`、`raw_block` 默认不显示。

Message.id 和 ContentBlock.blockId 从 timeline 坐标稳定可复算，格式为 `timeline-${sessionId}-${turnId}-${providerCallIndex}-${blockIndex}`，缺少坐标时退化到 seq-based id。

## 实时与 REST 历史恢复流程

### SSE Replay 边界

REST timeline 是历史事实源。SSE replay 只补当前 gateway 进程内短期实时窗口：

- `SseEnvelope(eventId: String?, event: StreamEvent)` 暴露 SSE event id。
- App 为每个活跃 session 保存 `lastDeliveredSseEventId`。
- 回前台/切 session/重连时：先 REST hydrate 完整 timeline，再用 last event id 连接 SSE。
- 新建 provisional session 首次连接允许 `Last-Event-ID: 0`。

幂等策略：`block.start` 遇到已存在 `blockId` 不重复 append，`block.stop` 只更新已有 block。

### 新建主对话

1. App 生成 `clientSessionId`，设置 `activeSessionId`。
2. 追加本地 user bubble。
3. 先启动 `/sessions/{clientSessionId}/stream`（`Last-Event-ID: 0`）。
4. `POST /turns`，body 带 `session_id = clientSessionId`。
5. 成功：清空 provisional 标记，刷新 session list。
6. 失败：停止 SSE、移除 user bubble、activeSessionId 回 null、发 `RestoreComposerText` + toast。

### 已有主对话

不生成新 id。POST 带现有 `session_id`。失败后移除 user bubble，恢复 composer text。

### SubAgent Session

新 SubAgent 使用相同 provisional id 流程，POST 目标为 `/agents/{agentType}/sessions`。

### UI Effect

```kotlin
sealed interface ChatUiEffect {
    data class RestoreComposerText(val text: String) : ChatUiEffect
    data class ShowToast(val message: String) : ChatUiEffect
}
```

## UI 展示

REST 历史恢复后的 `Message.blocks` 与实时 SSE 完成后的形态一致。

`SummaryCard` composable：

- 标题为 `Compressed summary`。
- 默认折叠，可展开。
- 展开后使用 Markdown 渲染。
- archived 原文按普通历史内容显示，无额外标记。

## 测试覆盖

后端：

- `GET /sessions/{id}?include_archived=true` 的 `timeline_items` 按 `seq ASC` 返回
- `POST /turns` 支持可选 `session_id`
- `POST /agents/{agentType}/sessions` 支持可选 `session_id`、409 冲突

Android data 层：

- `SessionDetailResponse` 解析 `timeline_items`
- Timeline mapper 映射所有 kind
- tool_call/tool_result 按 `tool_call_id` 合并
- UI 排序使用 `seq ASC`
- legacy `messages` fallback

Android ViewModel：

- client session id 生成和 SSE/POST 流程
- 失败后 user bubble 移除和 effect 发送
- hydrate 后使用 last event id 连接 SSE

验证命令：

```bash
pytest tests/unit/store tests/integration/gateway -q
ruff check sebastian/ tests/
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest :app:compileDebugKotlin
```

---

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
