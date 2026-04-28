---
date: 2026-04-28
status: draft
topic: agent-file-send-and-todo-read
---

# Agent File Send and Todo Read Design

## 1. 背景

Sebastian 现在已有 `todo_write`，但没有对称的 `todo_read`。长任务、恢复上下文、子代理协作时，Agent 需要一个显式工具读取当前 session 的 todo 状态，而不是完全依赖 system prompt 注入。

附件链路已经支持用户上传图片和文本文件，并在 Android 对话列表中渲染 `ImageBlock` / `FileBlock`。本次希望 Agent 也能向用户发送图片或文本文件，显示方式类似 IM 软件中的图片/文件消息。

## 2. P0 范围

本次只做：

- 新增 `todo_read` 工具。
- 新增 `send_file` 工具，让 Agent 发送本地图片或文本文件。
- Android 当前会话实时显示 `send_file` 产出的图片/文件 block。
- Android 历史水合时继续显示 Agent 发过的图片/文件。
- 更新工具失败返回规范，避免 Agent 对确定性失败盲目重试。

本次不做：

- 不做截图工具。
- 不把 Agent 发送的图片/文件内容喂回 LLM 多模态上下文。
- 不新增 assistant-side `attachment` session item。
- 不通过 turn done 后全量刷新当前消息列表来显示附件。
- 不支持任意二进制文件，P0 只支持现有附件系统已支持的图片和文本文件。

## 3. 总体设计

### 3.1 `todo_read`

`todo_read` 是 `todo_write` 的只读配对工具。

- 位置：`sebastian/capabilities/tools/todo_read/__init__.py`
- 工具名：`todo_read`
- 参数：无
- 权限：`PermissionTier.LOW`
- 上下文：必须存在 `ToolCallContext.session_id`
- 数据源：`state.todo_store.read(ctx.agent_type, ctx.session_id)`

成功返回：

```json
{
  "todos": [
    {
      "content": "整理方案",
      "activeForm": "正在整理方案",
      "status": "in_progress"
    }
  ],
  "count": 1,
  "session_id": "..."
}
```

`display` 使用简洁 checklist 文本。空列表返回空数组，`display` 为“当前没有待办”。

失败时返回 `ToolResult(ok=False, error=...)`，不伪造 todo 状态。

### 3.2 `send_file`

`send_file` 把本地文件注册进现有 `AttachmentStore`，并通过 tool result artifact 让 App 渲染为 Sebastian 发出的附件 block。

- 位置：`sebastian/capabilities/tools/send_file/__init__.py`
- 工具名：`send_file`
- 参数：
  - `file_path: str`：必填，本地文件路径。
  - `display_name: str | None`：可选，用户看到的文件名。不填时使用源文件名。
- 权限：`PermissionTier.MODEL_DECIDES`
- 路径解析：必须使用 `sebastian.capabilities.tools._path_utils.resolve_path()`
- 支持类型：
  - 图片：沿用 `AttachmentStore` 现有 image 后缀、MIME 和 10 MB 限制。
  - 文本文件：沿用 `AttachmentStore` 现有 text_file 后缀、MIME 和 2 MB 限制。
  - 其他类型 P0 拒绝。

成功返回：

```json
{
  "artifact": {
    "kind": "image",
    "attachment_id": "att-123",
    "filename": "photo.png",
    "mime_type": "image/png",
    "size_bytes": 12345,
    "download_url": "/api/v1/attachments/att-123",
    "thumbnail_url": "/api/v1/attachments/att-123/thumbnail"
  }
}
```

文本文件：

```json
{
  "artifact": {
    "kind": "text_file",
    "attachment_id": "att-456",
    "filename": "notes.md",
    "mime_type": "text/markdown",
    "size_bytes": 500,
    "download_url": "/api/v1/attachments/att-456",
    "text_excerpt": "# Hello"
  }
}
```

`display` / LLM-facing `model_content` 只记录事实，例如：

- `已向用户发送图片 photo.png`
- `已向用户发送文件 notes.md`

不包含图片 base64、文件全文或真实 blob 路径。

## 4. 后端数据流

### 4.1 AttachmentStore

`send_file` 复用 `AttachmentStore.upload_bytes()`，将文件复制进现有附件 blob 目录。App 不读取本地路径，只通过 attachment API 下载。

`upload_bytes()` 默认写入 `status="uploaded"`。用户上传附件会在 turn API 中转为 `attached`；`send_file` 不走用户 turn，因此需要新增内部方法，例如：

```python
async def mark_agent_sent(
    attachment_id: str,
    agent_type: str,
    session_id: str,
) -> None:
    ...
```

行为：

- 仅允许 `uploaded -> attached`
- 写入 `agent_type`、`session_id`、`attached_at`
- 防止 cleanup 把 Agent 发出的文件当作临时 uploaded 附件删除
- 不新增 `attachment` session item

### 4.2 Tool Result Artifact 持久化

现有 `tool_result` 会作为 session timeline item 入库，但 `ToolResult.output` 没有稳定保存在 timeline payload 中。为了支持历史水合，本次增加窄通道：

1. `send_file` 返回 `ToolResult.output["artifact"]`
2. `stream_helpers.append_tool_result_block()` 从 `result.output` 提取 `artifact`
3. `session_timeline._normalize_block_payload()` 保留 `artifact`
4. timeline API 返回 `tool_result.payload.artifact`

`tool_result.content` / `model_content` 仍保持轻量事实文本。LLM 后续只知道“已发送某文件”，不会读取文件内容。

### 4.3 SSE 实时显示

当前实时显示不能依赖 turn done 后全量刷新，否则可能造成对话列表闪动或滚动位置变化。

因此扩展 `tool.executed` 事件：

- 保留现有 `result_summary`
- 如果工具结果带 `artifact`，额外发送 `artifact`
- 失败事件不带 artifact

失败语义保持现有后端工具流：

- `ToolResult(ok=False, error=...)` 发布 `tool.failed`
- `ToolResult(ok=True, output=...)` 发布 `tool.executed`
- 只有成功的 `tool.executed` 可以携带 `artifact`

因此 `send_file` 的确定性失败不会走 `tool.executed`，Android 继续按现有 `ToolFailed` 路径把对应工具卡置为失败。

示例：

```json
{
  "type": "tool.executed",
  "data": {
    "session_id": "...",
    "tool_id": "toolu_...",
    "name": "send_file",
    "result_summary": "已向用户发送图片 photo.png",
    "artifact": {
      "kind": "image",
      "attachment_id": "att-123",
      "filename": "photo.png",
      "mime_type": "image/png",
      "size_bytes": 12345,
      "download_url": "/api/v1/attachments/att-123",
      "thumbnail_url": "/api/v1/attachments/att-123/thumbnail"
    }
  }
}
```

## 5. Android 显示设计

### 5.1 复用现有 UI

现有 App 已有：

- `ContentBlock.ImageBlock`
- `ContentBlock.FileBlock`
- `ImageAttachmentBlock`
- `FileAttachmentBlock`
- `StreamingMessage` 对 USER 和 ASSISTANT 两侧的 block 渲染

因此 UI 组件本身不需要大改。改动集中在数据映射。

### 5.2 实时 SSE 映射

`StreamEvent.ToolExecuted` 增加可选 `artifact` 字段。

`ChatViewModel.handleEvent()` 处理 `ToolExecuted` 时：

- 如果 `event.name == "send_file"` 且 `event.artifact != null`
  - 将对应 `toolId` 的 `ToolBlock` 原地替换成 `ImageBlock` 或 `FileBlock`
  - 不全量刷新消息列表
  - 如果找不到对应 `ToolBlock`，但当前 active session 与事件 session 一致，且当前 assistant message 仍存在，则将附件 block 追加到当前 assistant message 末尾
  - 使用 `attachment_id` 去重，避免 SSE replay 或后续历史水合产生重复 block
  - 如果当前 assistant message 已不存在，则不创建临时消息；历史水合负责最终一致显示
- 否则沿用现有逻辑，将工具卡状态置为 DONE

失败时：

- `ToolFailed` 保持现有工具卡错误显示
- 不生成附件 block

### 5.3 历史 Timeline 映射

`TimelineMapper.buildAssistantBlocks()` 增加窄特例：

- 找到 `tool_result.payload.tool_call_id` 对应的 `tool_call`
- 若工具名为 `send_file`
- 且 `tool_result.ok == true`
- 且 `tool_result.payload.artifact` 存在
- 则转成 `ImageBlock` / `FileBlock`
- 不生成这个 `send_file` 的 `ToolBlock`

其他工具不受影响。

历史水合链路：

```text
GET /api/v1/sessions/{id}?include_archived=true
  -> timeline_items
  -> TimelineMapper 读取 tool_result.payload.artifact
  -> ImageBlock / FileBlock
  -> AttachmentBlocks.kt 渲染
```

这保证从其他 session 切回、重启 App 后，Agent 发出的图片/文件仍能正常显示。

## 6. 失败处理规范

`send_file` 的确定性失败必须返回稳定、可行动的错误，并明确提示 Agent 不要自动重试同一输入，应告知用户或请求新输入。

示例：

- `send_file requires session context. Do not retry automatically; tell the user the file could not be sent in this conversation.`
- `File not found: <path>. Do not retry automatically; ask the user to provide an existing file path.`
- `Path is a directory, not a file: <path>. Do not retry automatically; ask the user for a file path.`
- `Unsupported file type: <suffix>. Do not retry automatically; only image and supported text files can be sent.`
- `File is too large to send: <filename>. Do not retry automatically; ask the user to choose a smaller file.`
- `Attachment service is unavailable. Do not retry automatically; tell the user sending files is currently unavailable.`

`todo_read` 失败也必须返回 `ToolResult(ok=False, error=...)`，不得伪造状态。

该规范同步写入 `sebastian/capabilities/tools/README.md` 的新增工具规范中：

- 工具失败必须返回 `ToolResult(ok=False, error=...)`
- `error` 应包含失败原因和下一步建议
- 确定性失败应明确 `Do not retry automatically; ...`
- 临时性失败可建议稍后重试，但不能在同一 turn 内无限重试

## 7. 测试计划

### 7.1 后端

- `todo_read` 有 session context 时返回当前 todos
- `todo_read` 空 todo 返回空数组和清晰 display
- `todo_read` 无 session context 返回 `ok=False`
- `send_file` 图片成功注册 attachment，返回 `artifact.kind=image`
- `send_file` 文本文件成功注册 attachment，返回 `artifact.kind=text_file` 和 `text_excerpt`
- `send_file` 文件不存在、目录、不支持类型、超大小、attachment store 未初始化均返回明确 `ok=False error`
- `send_file` 成功后 attachment 绑定到当前 `agent_type/session_id`
- `ToolResult.output.artifact` 写入 `tool_result.payload.artifact`
- `tool_result.model_content` 保持轻量事实文本，不包含图片 base64 或文件全文
- `tool.executed` 成功事件可选携带 artifact
- `send_file` 确定性失败发布 `tool.failed`，不发布带 artifact 的 `tool.executed`
- 集成测试覆盖 `GET /api/v1/sessions/{id}?include_archived=true` 返回的 `timeline_items` 中，成功 `send_file` 的 `tool_result.payload.artifact` 完整保留

### 7.2 Android

- `TimelineMapper` 将历史 `send_file` image artifact 映射为 assistant `ImageBlock`
- `TimelineMapper` 将历史 `send_file` text_file artifact 映射为 assistant `FileBlock`
- 成功 `send_file` 不生成 `ToolBlock`
- 失败 `send_file` 仍显示失败工具卡
- 其他工具映射不变
- SSE `tool.executed` 带 artifact 时，当前 ToolBlock 原地替换为 Image/File block
- SSE `tool.executed` 带 artifact 但找不到 ToolBlock 时，追加附件 block 到当前 assistant message，并按 `attachment_id` 去重
- SSE `tool.executed` 不带 artifact 时，保持普通工具卡 DONE 逻辑
- 仓储/映射测试覆盖后端 timeline JSON 中的 `tool_result.payload.artifact` 经过 `TimelineMapper` 变成 assistant Image/File block

## 8. 文档更新

- `sebastian/capabilities/tools/README.md`
  - 新增 `todo_read/`
  - 新增 `send_file/`
  - 新增工具失败返回规范
- `sebastian/capabilities/README.md`
  - 同步工具目录索引
- `ui/mobile-android/README.md`
  - 补充 Agent 发送附件通过 `send_file` tool result artifact 显示为图片/文件 block
- `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`
  - 补充 assistant-side image/file block 可来自 `send_file`

## 9. 验收标准

- Agent 调用 `todo_read` 能读取当前 session todo。
- Agent 调用 `send_file` 发送图片后，当前聊天实时显示图片 block。
- 切走再切回同一 session 后，Agent 发出的图片仍正常显示。
- Agent 调用 `send_file` 发送文本文件后，当前聊天实时显示文件 block。
- 切走再切回同一 session 后，Agent 发出的文件仍正常显示。
- `send_file` 失败时显示失败工具卡，Agent 不反复重试同一输入。
- 当前 turn 不通过全量刷新消息列表来显示附件。
