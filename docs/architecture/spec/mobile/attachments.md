---
version: "1.2"
last_updated: 2026-05-01
status: implemented
---

# 附件输入（图片与文本文件）

*← [Android 客户端索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景

Sebastian Android App 初期只支持纯文本输入。本功能覆盖 P0 目标：用户从 Android App 发送图片和有限文本文件，后端持久化附件并把附件纳入 session timeline，LLM 调用时按 provider 能力投影为可读上下文。

P0 范围以外（不实现）：AI 生成图片/文件、PDF/Office/音频/视频、大文件分片、对象存储、WebSocket。

---

## 2. 总体方案

「Attachment 一等资源 + Timeline 内容块 + REST 上传 + SSE 继续流式输出」

```
Android Composer
  → POST /api/v1/attachments
  → POST /api/v1/turns（携带 attachment_ids）
  → BaseAgent 读取 SessionStore context
  → session_context 按 provider message_format 投影附件
  → LLMProvider stream
  → 现有 SSE 事件返回文本/工具/状态
```

附件本体不写入 `session_items.content`，数据库只保存 metadata 和 blob 相对路径。附件作为 user message 所属 exchange 的一部分持久化。

---

## 3. 本地存储

```
<data_dir>/attachments/
  blobs/
    ab/
      <sha256>          # 内容寻址，同内容只存一份（去重）
  thumbs/
    ab/
      <sha256>.jpg      # 缩略图按 SHA 内容寻址（jpg/png/webp 之一）
  tmp/
```

生产默认：`~/.sebastian/data/attachments/`；开发：`~/.sebastian-dev/data/attachments/`。

规则：
- blob 文件名使用 sha256，不使用原始文件名
- 上传先写入 `tmp/`，校验通过后原子 rename 到 `blobs/<sha256-prefix-2chars>/<sha256>`
- 同内容二次上传跳过写文件（blob 已存在时 `created_blob=False`，直接入库新 record）
- 缩略图按 SHA 内容寻址：`thumbs/<sha[:2]>/<sha>.<ext>`，上传图片时同步生成（256×256，Pillow）
- 缩略图失败不影响原图上传（降级返回原图）
- 下载接口根据 DB metadata 定位 blob，不接受客户端传入任意路径

存储层详细实现（blob 去重、引用计数 cleanup、缩略图生成算法）见 [store/attachments.md](../store/attachments.md)。

---

## 4. 数据模型

`attachments` 表（`sebastian/store/models.py`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | ULID/UUID |
| `owner_user_id` | TEXT NULL | 预留多用户归属 |
| `session_id` | TEXT NULL | 被引用后写入 |
| `agent_type` | TEXT NULL | 被引用后写入 |
| `kind` | TEXT | `image` / `text_file` |
| `original_filename` | TEXT | 原始文件名，仅展示 |
| `mime_type` | TEXT | 服务端校验后的 MIME |
| `size_bytes` | INTEGER | 文件大小 |
| `sha256` | TEXT | 内容哈希 |
| `blob_path` | TEXT | 相对 attachments 根目录的路径 |
| `text_excerpt` | TEXT NULL | 文本文件预览（前 2000 字符） |
| `status` | TEXT | `uploaded` / `attached` / `orphaned` |
| `created_at` | DATETIME | |
| `attached_at` | DATETIME NULL | 被 timeline 引用时间 |
| `orphaned_at` | DATETIME NULL | 引用 session/timeline 删除时间 |

索引：
- `ix_attachments_status_created(status, created_at)`
- `ix_attachments_session(agent_type, session_id)`
- `ix_attachments_sha256(sha256)`

---

## 5. Timeline 表达

用户发送「文本 + 附件」时，写入同一个 exchange：

```
user_message
attachment
attachment
```

`attachment` item 示例（图片）：

```json
{
  "kind": "attachment",
  "role": "user",
  "content": "",
  "payload": {
    "attachment_id": "...",
    "kind": "image",
    "filename": "photo.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 123456,
    "sha256": "..."
  }
}
```

文本文件额外含 `"kind": "text_file"` 和 `"text_excerpt": "..."`。

Android `TimelineMapper` 将同一 exchange 内的 `user_message + attachment` 合并为一条 user bubble。

---

## 6. API 设计

### 6.1 上传附件

```http
POST /api/v1/attachments
Content-Type: multipart/form-data
Authorization: Bearer <jwt>

file=<binary>
kind=image|text_file
```

> **实现差异**：原 spec 设计响应字段为 `attachment_id`，`id` 曾为旧字段名；
> 当前实现（commit `10822f66`）统一为 `attachment_id`，与 timeline payload 一致。

响应（201）：

```json
{
  "attachment_id": "...",
  "kind": "image",
  "filename": "photo.jpg",
  "mime_type": "image/jpeg",
  "size_bytes": 123456,
  "sha256": "...",
  "text_excerpt": null,
  "status": "uploaded"
}
```

> **实现差异**：spec 原设计含 `download_url` 和 `thumbnail_url`；当前实现不含这两个字段。
> Android 客户端通过拼接 `$baseUrl/api/v1/attachments/$attachmentId` 构建 URL，P0 路径功能完整。

校验：
- 图片：`image/jpeg` / `image/png` / `image/webp` / `image/gif`，≤ 10 MB
- 文本文件：后缀 `.txt/.md/.csv/.json/.log`，≤ 2 MB，必须 UTF-8 可解码
- 单 turn 最多 5 个附件
- 服务端同时校验 MIME 与后缀

### 6.2 下载附件

```http
GET /api/v1/attachments/{attachment_id}
GET /api/v1/attachments/{attachment_id}/thumbnail
```

均需 JWT。`/thumbnail` 端点优先返回服务端生成的 256×256 缩略图；无缩略图时 fallback 返回原图（兼容老数据和生成失败场景）。

### 6.3 发送 turn（扩展）

```json
{
  "content": "帮我看看这张图",
  "session_id": "...",
  "attachment_ids": ["..."]
}
```

`content` 可为空，但 `content` 和 `attachment_ids` 不能同时为空。

turn 发送前后端执行（`_attachment_helpers.py`）：

1. 校验 content / attachment_ids 至少一个非空
2. 校验附件数量 ≤ 5
3. `validate_attachable()` 校验附件存在且状态为 `uploaded`
4. 校验 provider 图片能力（如有图片附件）
5. 校验文本文件 token 预算（≤ 100,000 tokens）
6. 写 `user_message` 和 `attachment` timeline items，状态改为 `attached`
7. 启动 `run_streaming()`

错误码：
- attachment 不存在 → 400（`AttachmentNotFoundError`）
- attachment 已被其他 turn 引用 → 409（`AttachmentConflictError`）
- 图片 provider 不支持 → 400
- 文本超 token 预算 → 400

---

## 7. Provider 能力

`supports_image_input: bool`（默认 `false`）和 `supports_text_file_input: bool`（默认 `true`）在 `LLMResolvedProvider`（`llm/registry.py`）和 `LLMCustomModelRecord`（`store/models.py`）中实现。

`supports_text_file_input` 对所有 provider 视为 `true`，因为文本文件由服务端解码后投影为普通文本。

### 文本文件投影

```
用户上传了文本文件：notes.md
```notes.md
<file content>
```
```

若超过 token 预算，返回 400；P0 不做自动摘要。

### 图片投影

Anthropic 路径：投影为 `image` content block。OpenAI-compatible 路径：P0 不迁移 Responses API，只有显式支持当前 chat-completions 多模态格式时才启用。

---

## 8. Android 实现

### 8.1 数据模型

**`ContentBlock`**（`data/model/ContentBlock.kt`）新增：

```kotlin
data class ImageBlock(
    override val blockId: String,
    val attachmentId: String,
    val filename: String,
    val mimeType: String,
    val sizeBytes: Long,
    val downloadUrl: String,
    val thumbnailUrl: String? = null,
) : ContentBlock()

data class FileBlock(
    override val blockId: String,
    val attachmentId: String,
    val filename: String,
    val mimeType: String,
    val sizeBytes: Long,
    val downloadUrl: String,
    val textExcerpt: String? = null,
) : ContentBlock()
```

**发送前模型**（`data/model/AttachmentModels.kt`）：

```kotlin
data class ModelInputCapabilities(
    val supportsImageInput: Boolean = false,
    val supportsTextFileInput: Boolean = true,
)

sealed class AttachmentUploadState {
    object Local : AttachmentUploadState()
    data class Uploading(val progress: Float = 0f) : AttachmentUploadState()
    data class Uploaded(val attachmentId: String) : AttachmentUploadState()
    data class Failed(val reason: String) : AttachmentUploadState()
}

data class PendingAttachment(
    val localId: String,
    val kind: AttachmentKind,
    val uri: Uri,
    val filename: String,
    val mimeType: String,
    val sizeBytes: Long,
    val uploadState: AttachmentUploadState = AttachmentUploadState.Local,
) {
    val attachmentId: String? get() = (uploadState as? Uploaded)?.attachmentId
}
```

> **实现增强**：`Uploading` 含 `progress: Float = 0f`，支持未来进度条 UI。

> **实现差异**：spec 原设计 `PendingAttachment` 有独立的 `downloadUrl`、`thumbnailUrl`、`errorMessage` 字段；
> 实现中 `attachmentId` 以计算属性实现；`errorMessage` 封装在 `AttachmentUploadState.Failed(reason)` 中；
> `downloadUrl`/`thumbnailUrl` 不在 `PendingAttachment` 上（P0 不需要，发送前用本地 uri 渲染预览）。

### 8.2 状态归属

两类模型分开，避免把本地选择态和已入库历史态混在一起：

- **发送前**：`PendingAttachment` 存在 `ChatUiState.pendingAttachments`，由 `ChatAttachmentManager` 管理
- **历史内容**：进入 timeline 后映射为 `ContentBlock.ImageBlock` / `ContentBlock.FileBlock`

`ChatViewModel` 持有：
- `pendingAttachments: List<PendingAttachment>`
- 当前 provider 能力快照：`inputCapabilities: ModelInputCapabilities`

### 8.3 Composer 附件工具栏

Composer 输入框左下角展示两个并排图标按钮（`AttachmentToolbar`）：

| 按钮 | 图标 | 行为 |
|------|------|------|
| 左：附件 | `Icons.Default.AttachFile` | 直接打开 SAF 文件选择器（限 `.txt/.md/.csv/.json/.log`） |
| 右：图片 | `Icons.Outlined.Image` | 先读 `supportsImageInput`，false 时 Toast 并返回，true 时打开 Photo Picker |

两个按钮均设 `Modifier.focusProperties { canFocus = false }`，点击不收起键盘。

深色模式图标颜色：`if (isSystemInDarkTheme()) Color(0xFF9E9E9E) else Color.Black`（两按钮共用）。

**组件位置**：`ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentSlot.kt`（文件名保留，内部 composable 已改名为 `AttachmentToolbar`）

> **实现差异**：原始 spec 设计文件改名为 `AttachmentToolbar.kt`；实际实现保留文件名 `AttachmentSlot.kt`，仅 composable 函数改名。

> **实现差异**：原始 spec 设计右侧图标为 `Icons.Default.Image`（filled）；实际实现使用 `Icons.Outlined.Image`（outline 变体）。

`onSend` 签名扩展：

```kotlin
onSend: (text: String, attachments: List<PendingAttachment>) -> Unit
```

发送规则：
- 文本为空但有附件时允许发送
- streaming 中禁用新增附件和发送，保留停止按钮
- 上传失败的附件不发送 turn

### 8.4 DTO 与 API

`AttachmentUploadResponseDto`（`data/remote/dto/AttachmentDto.kt`）：

```kotlin
data class AttachmentUploadResponseDto(
    @Json(name = "attachment_id") val attachmentId: String,
    @Json(name = "kind") val kind: String,
    @Json(name = "filename") val filename: String,
    @Json(name = "mime_type") val mimeType: String,
    @Json(name = "size_bytes") val sizeBytes: Long,
    @Json(name = "sha256") val sha256: String,
    @Json(name = "text_excerpt") val textExcerpt: String? = null,
    @Json(name = "status") val status: String,
)
```

`SendTurnRequest` 扩展 `attachmentIds: List<String> = emptyList()`。

### 8.5 TimelineMapper

`TimelineMapper` 是唯一把 `attachment` timeline item 映射为 `ContentBlock` 的入口。同一 exchange 下的 `user_message + attachment` 必须合并为一条 user bubble：

```
Message(role=USER)
  text = user_message.content
  blocks = [ImageBlock(...), FileBlock(...)]
```

`downloadUrl` 通过拼接 `"$baseUrl/api/v1/attachments/$attId"` 构建。

### 8.6 UI 渲染

- `ImageBlock`：渲染缩略图；点击后打开大图预览或下载原图
- `FileBlock`：渲染文件卡片，展示文件名、大小、后缀图标和可选 `textExcerpt`
- `PendingAttachment`：渲染在 `AttachmentPreviewBar`，展示本地缩略图/文件名/大小、上传中状态、失败原因、移除按钮

---

## 9. 生命周期与清理

状态流转：

- `uploaded`：上传完成，未被 timeline 引用
- `attached`：已被 timeline 引用
- `orphaned`：引用它的 session 已删除

session 删除时调用 `attachment_store.mark_session_orphaned()`，将关联 attachment 标记为 `orphaned`（`gateway/routes/sessions.py`）。

清理规则：
- `uploaded` 超过 24 小时未引用，可清理
- `orphaned` 超过 24 小时（`_ORPHAN_TTL`），可清理
- `attached` 永不自动清理

> **未实现**：`AttachmentStore.cleanup()` 已实现但未接入定期调度器。
> 清理任务需由 gateway lifespan 启动一个周期性后台任务来调用。

---

## 10. 错误处理

| 场景 | 行为 |
|------|------|
| 当前模型不支持图片 | Android Toast；后端 400 兜底 |
| 文件类型不支持 | Android 阻止；后端 400 兜底 |
| 文本文件非 UTF-8 | 后端 400，App 显示错误 |
| 上传成功但 turn 失败 | 附件保持 `uploaded`，24 小时后可清理 |
| attachment 不存在 | turn API 返回 400 |
| attachment 已被其他 turn 使用 | turn API 返回 409 |
| 单 turn 超过 5 个附件 | Android 阻止；后端 400 兜底 |
| 下载无权限 | 403 |
| 文本文件超 token 预算（100k） | 后端 400，P0 不自动摘要 |

---

## 11. 待完成

- `AttachmentStore.cleanup()` 接入 gateway lifespan 定期调度
- `upload_attachment` 响应补充 `download_url` / `thumbnail_url` 字段（P0 可接受，客户端自行拼接）
- 多用户权限扩展（P0 只有 owner 可访问）

---

## 12. Agent 发送附件（send_file）的 Android 显示

Agent 通过 `send_file` 工具发送的图片/文件，在 Android 端复用现有 `ImageBlock`/`FileBlock` UI，无需新增组件。改动集中在数据映射层。后端工具规格见 [capabilities/agent-file-send.md](../capabilities/agent-file-send.md)。

### 12.1 实时 SSE 映射

`StreamEvent.ToolExecuted` 增加可选 `artifact` 字段。

`ChatViewModel.handleEvent()` 处理 `ToolExecuted` 时：

- 若 `event.name == "send_file"` 且 `event.artifact != null`：
  - 找到对应 `toolId` 的 `ToolBlock`，原地替换为 `ImageBlock`/`FileBlock`
  - 不全量刷新消息列表（防止滚动位置变化/闪烁）
  - 找不到对应 `ToolBlock` 时，若当前 assistant message 存在，则追加附件 block 到末尾
  - 用 `attachment_id` 去重（防 SSE replay 或后续历史水合产生重复 block）
  - 当前 assistant message 不存在时，不创建临时消息；历史水合负责最终一致
- 否则沿用现有逻辑，将工具卡状态置为 DONE

失败时（`ToolFailed`）：保持现有工具卡错误显示，不生成附件 block。

### 12.2 历史 Timeline 水合

`TimelineMapper.buildAssistantBlocks()` 新增 `send_file` 特例：

- 找到 `tool_result` 对应的 `tool_call`，若工具名为 `send_file`
- 且 `tool_result.ok == true`
- 且 `tool_result.payload.artifact` 存在
- → 转为 `ImageBlock`/`FileBlock`，不生成 `ToolBlock`

其他工具不受影响。

水合链路：

```
GET /api/v1/sessions/{id}?include_archived=true
  → timeline_items
  → TimelineMapper 读取 tool_result.payload.artifact
  → ImageBlock / FileBlock
  → AttachmentBlocks 渲染
```

切走再切回 session、重启 App 后，Agent 发出的图片/文件仍能正常显示。

---

*← [Android 客户端索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
