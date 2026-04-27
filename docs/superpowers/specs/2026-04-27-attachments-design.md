---
version: "1.0"
last_updated: 2026-04-27
status: planned
---

# 图片与文本文件附件输入设计

## 1. 背景

Sebastian Android App 当前只支持纯文本输入。用户无法在对话中发送图片，也无法把本地文本文件作为上下文交给 Agent 分析。

本设计覆盖 P0：用户从 Android App 发送图片和有限文本文件，后端持久化附件并把附件纳入 session timeline，LLM 调用时按 provider 能力投影为可读上下文。P0 不覆盖 AI 生成图片、AI 生成文件、PDF/Office、音频、视频、大文件分片、对象存储或 WebSocket。

## 2. 目标与非目标

### 2.1 目标

- Android Composer 左下角新增附件按钮，点击后选择「图片」或「文件」。
- 图片选择前先检查当前 provider/model 是否支持图片输入，不支持时直接 Toast，不打开图片选择器。
- 文本文件支持 `.txt` / `.md` / `.csv` / `.json` / `.log`。
- 附件上传后随同 turn 发送，历史 session 可恢复并展示附件。
- 后端用本地数据目录持久化 blob，用 SQLite 持久化 metadata。
- REST 负责附件上传和 turn 发起，SSE 协议保持不变。
- 后端在 turn 开始前做最终能力校验，防止客户端状态过期或绕过 UI。

### 2.2 非目标

- 不实现 AI 图片生成或文件生成工具链。
- 不实现 PDF、Word、Excel、视频、音频支持。
- 不迁移 OpenAI provider 到 Responses API。
- 不引入 WebSocket。
- 不引入 S3/MinIO 等对象存储。
- 不做附件管理页或跨设备同步。

## 3. 总体方案

采用「Attachment 一等资源 + Timeline 内容块 + REST 上传 + SSE 继续流式输出」。

```text
Android Composer
  → POST /api/v1/attachments
  → POST /api/v1/turns 或 /sessions/{id}/turns，携带 attachment_ids
  → BaseAgent 读取 SessionStore context
  → session_context 按 provider message_format 投影附件
  → LLMProvider stream
  → 现有 SSE 事件返回文本/工具/状态
```

附件本体不写入 `session_items.content`，数据库只保存 metadata 和 blob 相对路径。Timeline 是对话历史的权威来源，附件作为 user message 所属 exchange 的一部分持久化。

## 4. 本地存储设计

附件数据放在 Sebastian v2 数据目录下：

```text
<data_dir>/attachments/
  blobs/
    ab/
      <sha256>
  thumbs/
    <attachment_id>.jpg
  tmp/
```

其中生产环境默认是 `~/.sebastian/data/attachments/`，开发环境是 `~/.sebastian-dev/data/attachments/`。

规则：

- blob 文件名使用 sha256，不使用原始文件名。
- 原始文件名只存 DB metadata。
- 上传先写入 `tmp/`，校验通过后原子 rename 到 `blobs/<sha256-prefix>/<sha256>`。
- 图片缩略图可在 P0 生成，存入 `thumbs/`；缩略图失败不影响原图上传。
- 下载接口根据 DB metadata 定位 blob，不接受客户端传入任意路径。

## 5. 数据模型

新增 `attachments` 表：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 附件 ID，ULID/UUID |
| `owner_user_id` | TEXT NULL | 预留多用户归属，P0 可为空或 owner |
| `session_id` | TEXT NULL | 被引用后写入所属 session |
| `agent_type` | TEXT NULL | 被引用后写入所属 agent |
| `kind` | TEXT | `image` / `text_file` |
| `original_filename` | TEXT | 原始文件名，仅展示 |
| `mime_type` | TEXT | 服务端校验后的 MIME |
| `size_bytes` | INTEGER | 文件大小 |
| `sha256` | TEXT | 内容哈希 |
| `blob_path` | TEXT | 相对 attachments 根目录的路径 |
| `text_excerpt` | TEXT NULL | 文本文件预览，限制长度 |
| `status` | TEXT | `uploaded` / `attached` / `orphaned` |
| `created_at` | DATETIME | 创建时间 |
| `attached_at` | DATETIME NULL | 被 timeline 引用时间 |
| `orphaned_at` | DATETIME NULL | 引用 session/timeline 删除时间 |

索引：

- `ix_attachments_status_created(status, created_at)`
- `ix_attachments_session(agent_type, session_id)`
- `ix_attachments_sha256(sha256)`

## 6. Timeline 表达

用户发送「文本 + 附件」时，写入同一个 exchange。Timeline 顺序：

```text
user_message
attachment
attachment
```

`attachment` item 示例：

```json
{
  "kind": "attachment",
  "role": "user",
  "content": "",
  "payload": {
    "attachment_id": "att_...",
    "kind": "image",
    "filename": "photo.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 123456,
    "sha256": "...",
    "download_url": "/api/v1/attachments/att_..."
  }
}
```

文本文件 item 增加：

```json
{
  "payload": {
    "kind": "text_file",
    "filename": "notes.md",
    "mime_type": "text/markdown",
    "text_excerpt": "# Meeting notes..."
  }
}
```

历史恢复时 Android `TimelineMapper` 将同一 exchange 内的 `user_message + attachment` 合并为一条 user bubble，避免附件散成多条消息。

## 7. API 设计

### 7.1 上传附件

```http
POST /api/v1/attachments
Content-Type: multipart/form-data
Authorization: Bearer <jwt>

file=<binary>
kind=image|text_file
```

返回：

```json
{
  "attachment_id": "att_...",
  "kind": "image",
  "filename": "photo.jpg",
  "mime_type": "image/jpeg",
  "size_bytes": 123456,
  "sha256": "...",
  "download_url": "/api/v1/attachments/att_...",
  "thumbnail_url": "/api/v1/attachments/att_.../thumbnail"
}
```

校验：

- 图片：`image/jpeg` / `image/png` / `image/webp` / `image/gif`，单文件最大 10 MB。
- 文本文件：后缀只允许 `.txt/.md/.csv/.json/.log`，单文件最大 2 MB。
- 文本文件必须 UTF-8 可解码；不支持时返回 400。
- 单 turn 最多 5 个附件。
- 服务端同时校验 MIME 与后缀，不能只信客户端。

### 7.2 下载附件

```http
GET /api/v1/attachments/{attachment_id}
GET /api/v1/attachments/{attachment_id}/thumbnail
```

全部需要 JWT。P0 只允许 owner 访问；多用户权限在 identity Phase 中扩展。

### 7.3 发送 turn

扩展现有请求体：

```json
{
  "content": "帮我看看这张图",
  "session_id": "...",
  "attachment_ids": ["att_..."]
}
```

`content` 可为空，但 `content` 和 `attachment_ids` 不能同时为空。

turn 开始前后端执行：

1. 解析 session 和 agent_type。
2. 校验 attachment 存在、状态是 `uploaded`、未被其他 timeline 引用。
3. 校验附件数量和 provider 能力。
4. 分配 exchange。
5. 写 `user_message` 和 `attachment` timeline items。
6. 将 attachment 状态改为 `attached`。
7. 启动现有 `run_streaming()`。

如果第 3 步失败，不写 timeline，不启动 LLM。

## 8. Provider 能力与投影

新增 provider/model 能力字段：

```text
supports_image_input: bool
supports_text_file_input: bool
```

P0 规则：

- `supports_text_file_input` 对所有 provider 视为 true，因为文本文件由服务端解码后投影为普通文本。
- `supports_image_input` 必须由 catalog/custom model 显式声明。
- 图片附件在当前 provider/model 不支持时，后端返回 400。

### 8.1 文本文件投影

文本文件内容作为 user content 的普通文本 block 注入，并加明确边界：

````text
用户上传了文本文件：notes.md
```notes.md
<file content>
```
````

此格式避免文件内容与用户自然语言指令混在一起。若文件内容超过 token 预算，P0 直接返回 400，提示用户缩短文件；不做自动摘要。

### 8.2 图片投影

Anthropic 路径将图片附件投影为 `image` content block。OpenAI-compatible 路径 P0 不迁移 Responses API；只有在具体 provider/model 显式支持当前 chat-completions 多模态格式时才启用图片，否则返回 400。

OpenAI Responses API 更适合长期承载 `input_image` / `input_file`，但本期不迁移，以免影响 DeepSeek、GLM、llama.cpp 等 OpenAI-compatible 后端。

参考：

- OpenAI Responses migration guide: https://developers.openai.com/api/docs/guides/migrate-to-responses
- OpenAI file inputs: https://developers.openai.com/api/docs/guides/file-inputs
- Anthropic vision: https://docs.anthropic.com/en/docs/build-with-claude/vision

## 9. Android 交互设计

### 9.1 Composer

Composer 左下角新增附件按钮。点击后弹出选择菜单：

- 图片
- 文件

选择「图片」：

1. 读取当前会话绑定 provider/model 的能力快照。
2. 不支持图片：Toast「当前模型不支持图片输入，请在 Settings 切换视觉模型」，不打开选择器。
3. 支持图片：打开系统 Photo Picker。

选择「文件」：

1. 打开 SAF 文件选择器。
2. 客户端限制 `.txt/.md/.csv/.json/.log`。
3. 选择后加入附件预览条。

发送规则：

- 文本为空但有附件时允许发送。
- streaming 中禁用新增附件和发送，但保留停止按钮。
- 上传失败的附件显示重试/移除状态，不发送 turn。

### 9.2 状态归属

`ChatViewModel` 持有：

- `pendingAttachments: List<PendingAttachment>`
- 当前 provider 能力快照
- 上传状态：`local` / `uploading` / `uploaded` / `failed`

`Composer` 只负责展示。`AttachmentSlot` 打开选择器，`AttachmentPreviewBar` 展示待发送附件、缩略图、文件名、大小、移除按钮和失败状态。

`onSend` 从：

```kotlin
onSend: (String) -> Unit
```

扩展为：

```kotlin
onSend: (text: String, attachments: List<PendingAttachment>) -> Unit
```

### 9.3 Android 数据模型

新增：

```kotlin
sealed class AttachmentBlock : ContentBlock
data class ImageBlock(...)
data class FileBlock(...)
```

或在现有 `ContentBlock` 下新增：

- `ImageBlock`
- `FileBlock`

`TimelineMapper` 是唯一把 `attachment` timeline item 映射为 UI block 的入口。

## 10. 生命周期与清理

状态：

- `uploaded`：上传完成但未被 timeline 引用。
- `attached`：已被 timeline 引用。
- `orphaned`：曾 attached，但引用它的 session/timeline 已删除。

清理规则：

- `uploaded` 超过 24 小时仍未被任何 timeline 引用，可清理。
- `orphaned` 超过保留窗口，可清理。
- `attached` 永不自动清理，只随 session/timeline 删除转为 `orphaned`。

删除 session 时：

1. 删除或标记 session/timeline。
2. 找到关联 attachment，标记为 `orphaned`。
3. 后台清理任务异步删除 blob。

## 11. 错误处理

| 场景 | 行为 |
|------|------|
| 当前模型不支持图片 | Android Toast；后端 400 兜底 |
| 文件类型不支持 | Android 阻止；后端 400 兜底 |
| 文本文件非 UTF-8 | 后端 400，App 显示错误 |
| 上传成功但 turn 失败 | 附件保持 `uploaded`，24 小时后可清理 |
| attachment_id 不存在 | turn API 返回 400 |
| attachment 已被其他 turn 使用 | turn API 返回 409 |
| 单 turn 超过 5 个附件 | Android 阻止；后端 400 兜底 |
| 下载无权限 | 403 |

## 12. 测试计划

### 12.1 后端

- 上传图片成功，blob 路径按 sha256 生成。
- 上传文本文件成功，`text_excerpt` 正确写入。
- 不支持后缀 / MIME / 超大小返回 400。
- 发送 turn 携带 attachment_ids 后，写入同 exchange 的 `user_message + attachment`。
- 图片 provider 不支持时返回 400，且不写 timeline。
- attachment 被引用后状态从 `uploaded` 变为 `attached`。
- 删除 session 后 attachment 变为 `orphaned`。
- 清理任务只删除未引用的 `uploaded` 和 `orphaned`，不删除 `attached`。
- `build_legacy_messages` / timeline API 能返回 attachment payload。
- provider context projection 覆盖文本文件和图片路径。

### 12.2 Android

- Composer 附件按钮打开「图片/文件」菜单。
- 不支持图片时选择「图片」只 Toast，不打开 Photo Picker。
- 支持图片时打开 Photo Picker。
- 文本文件选择器只接受 P0 后缀。
- 附件预览条展示图片缩略图、文件名、移除按钮、上传失败状态。
- 文本为空但有附件时发送按钮可用。
- `TimelineMapper` 将同 exchange 的附件合并进 user bubble。

## 13. 实施顺序

1. 后端 attachment store：目录、表、上传/下载 API、校验。
2. turn API 扩展：`attachment_ids`、exchange 写入、状态流转。
3. provider 能力字段：catalog/custom model DTO、Android binding resolved DTO。
4. context projection：文本文件展开、图片 provider 能力校验和 Anthropic 投影。
5. Android 数据层：upload API、DTO、Repository、ContentBlock、TimelineMapper。
6. Android UI：Composer 附件按钮、选择菜单、预览条、Toast 能力拦截。
7. 清理任务与 session 删除联动。
8. README / spec 索引同步。

## 14. 风险

- OpenAI-compatible 后端多模态格式不统一，因此 P0 不默认支持图片输入。
- 文本文件直接展开会消耗上下文窗口，P0 以大小限制和明确 400 控制风险。
- 附件 blob 与 DB 可能出现不一致，上传必须使用 tmp + 原子 rename，清理任务需以 DB 为准。
- Android provider 能力快照可能过期，后端 400 是最终一致性防线。
