---
version: "1.0"
last_updated: 2026-04-22
status: planned
integrated_to: mobile/timeline-hydration.md
integrated_at: 2026-04-23
---

# Mobile Timeline Hydration Design

## 背景

Session storage 迁移到 SQLite 后，后端开始返回 canonical
`timeline_items`。Android App 当前仍主要读取兼容 `messages`，导致重新进入
session 时只能恢复 user/assistant 纯文本，无法完整还原 thinking、tool call/result
和后续 context summary 节点。

本设计将 Android Chat 的 REST 历史恢复（hydration）切到完整 timeline。这里的
hydration 指 App 从后端读取已持久化的 `timeline_items`，并重建为 UI 直接使用的
`Message + ContentBlock`。同时，本设计收口新建 session 的实时 SSE race：App 生成
session id，先订阅 session stream，再发起 turn。WebSocket 不纳入本轮。

## 术语

- **REST 历史恢复（hydration）**：App 通过 REST 读取已持久化的 timeline，并重建为
  UI 领域模型 `Message + ContentBlock` 的过程。

## 目标

- Chat 页默认展示完整 session timeline，包括 archived 原文和 context summary。
- REST timeline 是历史事实源；SSE 只负责实时事件和短期 replay 补偿。
- 历史重载后的 UI 与实时 SSE 完成后的 UI 形态一致。
- 新建主对话和 SubAgent session 使用 client-generated session id，降低 REST/SSE 窗口期。
- 发送失败时撤回本地 user bubble，将文本恢复到 Composer，并提示用户重试。
- 为后续上下文压缩功能接入前端留下清晰 README 和模型入口。

## 非目标

- 不引入 WebSocket。
- 不做 delta offset / snapshot 协议增强。
- 不实现完整审计历史的单独页面；Chat 页本身展示完整 timeline。
- 不对 archived 原文做额外视觉标记。

## 后端接口语义

### Timeline 读取

`GET /api/v1/sessions/{session_id}?include_archived=true` 是 App 完整历史接口：

- 返回 `timeline_items`，包含 archived 原文、未归档内容和 `context_summary`。
- `timeline_items` 按真实写入顺序 `seq ASC` 返回。
- `effective_seq` 不参与 App UI 排序，仅服务 LLM context 视图。
- `messages` 继续作为 legacy fallback 返回。

`GET /api/v1/sessions/{session_id}` 不带 `include_archived` 时保持当前上下文视图，
用于旧调用方兼容。

本轮必须同步修改后端 store/route contract：`SessionStore.get_timeline_items()` 保留方法名，
但实现、docstring、README 和测试都要改为 audit timeline 语义：按 `seq ASC` 返回真实
写入顺序。当前按 `(effective_seq, seq)` 排序的测试需要改写。`get_context_timeline_items()`
继续按 `(effective_seq, seq)` 返回 LLM 当前上下文视图。

### Client-Generated Session ID

主对话 `POST /api/v1/turns` 使用现有 `session_id` 字段：

- `session_id == null`：保持旧行为，由后端生成 session id。
- `session_id != null` 且 session 不存在：后端用该 id 创建 session。
- `session_id != null` 且 session 已存在：向该 session 追加 turn。

SubAgent 新建接口 `POST /api/v1/agents/{agent_type}/sessions` 增加可选
`session_id`：

请求 body 为：

```json
{
  "content": "用户发给 SubAgent 的初始目标",
  "session_id": "client-generated-id 或 null"
}
```

`content` 仍为必填。

- 不传 `session_id`：保持旧行为，由后端生成。
- 传入且不存在：用该 id 创建 SubAgent session，并启动初始 turn。
- 传入且已存在，且该 session 的 `agent_type` 和 `goal` 与请求匹配：返回 `200` 和已有
  `session_id`，不重复启动初始 turn。该语义用于处理 App provisional create 响应丢失后的
  安全重试。
- 传入且已存在，但 agent 或 goal/content 不匹配：返回 `409 Conflict`。

已有 session 的后续 turn 继续走 `POST /api/v1/sessions/{session_id}/turns`。

`GET /api/v1/sessions/{session_id}/stream` 明确允许订阅尚未落库的 session id。当前
`SSEManager` 按事件 data 过滤，不校验 session 存在性；后续不应在该路由新增存在性
校验。

## Android 数据模型与映射

### DTO

`SessionDetailResponse` 增加：

```kotlin
@Json(name = "timeline_items")
val timelineItems: List<TimelineItemDto> = emptyList()
```

新增 `TimelineItemDto`，覆盖 App 所需字段：

- `id`
- `session_id`
- `agent_type`
- `seq`
- `kind`
- `role`
- `content`
- `payload`
- `archived`
- `turn_id`
- `provider_call_index`
- `block_index`
- `created_at`

`ChatRepository.getMessages(sessionId)` 改为请求
`GET /sessions/{id}?include_archived=true`。若 `timeline_items` 非空，优先使用 timeline
mapper；否则 fallback 到 legacy `messages`。

### Domain Model

`ContentBlock` 新增：

```kotlin
data class SummaryBlock(
    override val blockId: String,
    val text: String,
    val expanded: Boolean = false,
    val sourceSeqStart: Long? = null,
    val sourceSeqEnd: Long? = null,
) : ContentBlock()
```

`ContentBlock.isDone` 对 `SummaryBlock` 恒为 `true`。

### Timeline Mapper

Mapper 先按 `seq ASC` 排序，再投影到 `Message`：

- `user_message`：独立 `Message(role=USER, text=content)`。
- assistant-side items 按 `(turn_id, provider_call_index)` 聚合为 assistant message。
- REST 历史恢复后的 `Message.id` 必须稳定可复算：
  - user message：`timeline-${sessionId}-${seq}`。
  - assistant group：`timeline-${sessionId}-${turnId}-${providerCallIndex}`；若缺少
    `turn_id` 或 `provider_call_index`，退化为 `timeline-${sessionId}-${firstSeq}`。
  - summary message：`timeline-${sessionId}-summary-${seq}`。
- REST 历史恢复后的 `Message.createdAt` 使用该 message 组内第一条 timeline item 的
  `created_at`。
- 从 timeline 重建出的 `ContentBlock.blockId` 也必须稳定可复算：
  - thinking/text/tool_call 有 `turn_id + provider_call_index + block_index` 时：
    `timeline-${sessionId}-${turnId}-${providerCallIndex}-${blockIndex}`。
  - tool block 优先使用 tool_call item 的 block id；只有孤立 tool_result 时使用
    `timeline-${sessionId}-tool-result-${seq}`。
  - summary block：`timeline-${sessionId}-summary-block-${seq}`。
  - 缺少 turn/block 坐标的普通 block 退化为 `timeline-${sessionId}-block-${seq}`。
- `thinking`：`ContentBlock.ThinkingBlock(done=true, text=content,
  durationMs=payload.duration_ms)`。
- `assistant_message`：`ContentBlock.TextBlock(done=true, text=content)`。
- `tool_call + tool_result`：按 `tool_call_id` 合并为一个 `ContentBlock.ToolBlock`。
  - 有 result 且 `ok=true`：`DONE`。
  - 有 result 且 `ok=false` 或 `payload.error`：`FAILED`。
  - 无 result：`PENDING`。当前 timeline 不持久化 `tool_running` marker，REST 历史恢复
    不推断 `RUNNING`。
  - 找不到 call 的 result 降级为 tool block，避免内容丢失。
- `context_summary`：独立 assistant message，包含一个 `SummaryBlock`。
- `system_event`、`raw_block` 默认不显示。

archived 与 non-archived item 使用同样 UI，不增加淡化或标签。`context_summary` 本身
就是压缩分界。

## 实时与 REST 历史恢复流程

### SSE Replay 边界

REST timeline 是历史事实源。SSE replay 只用于补当前 gateway 进程内短期实时窗口：

- App 为每个活跃 session 保存 `lastDeliveredSseEventId`。
- `SseClient` / repository 需要向 ViewModel 暴露 SSE event id，例如
  `SseEnvelope(eventId: String?, event: StreamEvent)`。
- ViewModel 处理事件后更新该 session 的 last event id。
- App 回前台、切 session 或重连时，先 REST hydrate 完整 timeline，再用保存的
  `lastDeliveredSseEventId` 连接 SSE，补后台期间 buffer 中的新事件。
- 若已有 session 没有 last event id，不从 `0` replay，只普通连接。
- 新建 provisional session 的首次连接允许 `Last-Event-ID: 0`，用于补订阅登记前可能
  已发布的事件。

App 只做 block/tool 级幂等，不做 delta offset 去重：

- `block.start` 遇到已存在 `blockId` 不重复 append。
- `block.stop` 只更新已有 block 的 done/duration。
- `tool.running/executed/failed` 按 `toolId` 更新已有 block。
- `turn.response` 只结束状态，不追加内容。
- delta 重复不做协议级修复；避免重复的主要机制是准确的 Last-Event-ID cursor。

Replay buffer 丢失、过期或 gateway 重启时，App 退化为 REST timeline 最终一致。

### 新建主对话

1. App 生成 `clientSessionId`。
2. 设置 `activeSessionId = clientSessionId`，并记录 `provisionalSessionId`。
3. 追加本地 user bubble。
4. 先启动 `/sessions/{clientSessionId}/stream`，首次连接使用 `Last-Event-ID: 0`。
5. POST `/turns`，body 传 `session_id = clientSessionId`。
6. REST 成功后清空 provisional 标记，刷新 session list。
7. REST 失败后：
   - 停止 SSE。
   - 移除刚追加的 user bubble。
   - `activeSessionId = null`。
   - composer 状态回到可发送。
   - 发 `RestoreComposerText(text)` 和 toast `发送失败，请重试`。

### 已有主对话

- 不生成新 id。
- 追加本地 user bubble 后 POST `/turns`，带现有 `session_id`。
- 失败后移除该 user bubble，恢复 composer 文本，active session 保持不变。
- 成功后由 SSE 负责实时输出。

### SubAgent Session

新 SubAgent session 使用与主对话相同的 provisional id 流程，但 POST 目标为
`/agents/{agent_type}/sessions`，body 带 `session_id`。

已有 SubAgent session 继续使用 `POST /sessions/{session_id}/turns`。失败回滚 user bubble
和 composer text，active session 保持不变。

### UI Effect

Composer 文本恢复是一次性 UI 事件，不进入持久 `ChatUiState`。新增统一 effect：

```kotlin
sealed interface ChatUiEffect {
    data class RestoreComposerText(val text: String) : ChatUiEffect
    data class ShowToast(val message: String) : ChatUiEffect
}
```

实现时可逐步兼容现有 toast flow，但最终 ChatScreen 应订阅 `ChatUiEffect`。恢复文本时
覆盖当前 Composer 文本，因为该事件紧跟发送失败发生。

## UI 展示

REST 历史恢复后的 `Message.blocks` 与实时 SSE 完成后的形态一致，继续使用现有
`MessageBubble` / `AssistantMessageBlocks`。

新增 `SummaryCard`：

- 在 `AssistantMessageBlocks` 中处理 `SummaryBlock`。
- 标题为 `Compressed summary`。
- 默认折叠，可展开。
- 展开后使用 Markdown 渲染 summary 文本。
- 样式接近 `ThinkingCard`，但语义独立，不复用 ThinkingBlock。

summary 显示在真实 `seq` 位置，即被压缩原文之后，表达“以上内容已压缩为摘要”。
archived 原文、thinking、tool block 均按普通历史内容显示。

## 测试策略

后端：

- `GET /sessions/{id}?include_archived=true` 的 `timeline_items` 按 `seq ASC` 返回。
- `get_timeline_items()` 测试和 docstring 锁定 audit timeline 语义。
- `POST /turns` 使用 client-provided `session_id` 创建新主 session。
- `POST /agents/{agent_type}/sessions` 支持可选 `session_id`。
- 重复 `session_id` 创建 SubAgent session 返回 `409`。

Android data 层：

- `SessionDetailResponse` 解析 `timeline_items`。
- timeline mapper 映射 user/text/thinking/tool_call/tool_result/context_summary。
- tool_call/tool_result 按 `tool_call_id` 合并。
- UI 排序使用 `seq ASC`，忽略 `effective_seq`。
- legacy `messages` fallback 保留。

Android ViewModel：

- 新主对话生成 client session id，并用该 id 启动 SSE 和 POST。
- 新 session POST 失败后移除 user bubble、activeSessionId 回 null、发
  `RestoreComposerText` 和 toast。
- 已有 session POST 失败后 activeSessionId 不变，移除 user bubble，恢复文本。
- SubAgent 新 session 成功/失败覆盖同样流程。
- hydrate 后使用保存的 last event id 连接 SSE。
- 重复 block start 不重复 append block。

Android UI / README：

- `SummaryBlock` 默认折叠，toggle 后切换 expanded。
- `SummaryCard` 标题为 `Compressed summary`。
- 更新 `ui/mobile-android/README.md`、`ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md`。
- 如存在 chat UI 子目录 README，同步说明 SummaryBlock 和 timeline hydration 接入点；否则在上级 UI README 补充。

## 验证命令

```bash
pytest tests/unit/store tests/integration/gateway -q
ruff check sebastian/ tests/

cd ui/mobile-android
./gradlew :app:testDebugUnitTest
./gradlew :app:compileDebugKotlin
```

## 风险与取舍

- SSE replay 仍是进程内 buffer，不跨 gateway 重启，不保证长期可靠。
- 不做 delta offset 去重；重复 delta 的极端场景后续可通过 offset 或 snapshot 协议优化。
- client-generated session id 降低新建 session race，但 session 只有后端落库成功后才算正式创建。
- 完整 audit timeline 默认展示 archived 原文，后续如历史过长，需要再设计虚拟列表、分页或压缩可视化优化。
