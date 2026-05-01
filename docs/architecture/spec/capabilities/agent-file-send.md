---
version: "1.0"
last_updated: 2026-05-01
status: implemented
---

# Agent 发送文件：todo_read + send_file

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景

Sebastian 已有 `todo_write`，但缺少只读配对；Agent 长任务、上下文恢复、子代理协作时需要显式读取 todo 状态。

附件链路已支持用户上传图片/文本文件。本功能对称地让 Agent 向用户发送文件，在聊天中渲染为图片/文件 block，支持实时 SSE 显示和历史 timeline 水合。

---

## 2. 范围

**实现内容**：

- `todo_read`：只读读取当前 session 的 todo 列表。
- `send_file`：Agent 将本地文件注册进 AttachmentStore 并通过 artifact 机制在聊天中呈现。
- `send_file_path`：内部共享 helper，供 `send_file` 和 `capture_screenshot_and_send` 复用。
- `tool.executed` SSE 事件携带可选 `artifact` 字段，驱动 Android 实时显示。
- Tool Result Artifact 持久化至 `tool_result.payload.artifact`，支持历史水合。
- 工具失败返回规范（见 §6）。

**不在范围**：截图工具（见 [screenshot-send.md](screenshot-send.md)）、将 Agent 发送文件内容反馈回 LLM 多模态上下文、assistant-side attachment session item、全量刷新消息列表。

---

## 3. 工具规格

### 3.1 `todo_read`

| 属性 | 值 |
|------|-----|
| 位置 | `sebastian/capabilities/tools/todo_read/__init__.py` |
| 权限 | `PermissionTier.LOW` |
| 参数 | 无 |
| 上下文要求 | `ToolCallContext.session_id` 必须存在 |
| 数据源 | `state.todo_store.read(ctx.agent_type, ctx.session_id)` |

成功返回（`ToolResult.output`）：

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

`display`：简洁 checklist 文本。空列表时 `todos=[]`，`display` 为"当前没有待办"。

失败时返回 `ToolResult(ok=False, error=...)`，不伪造 todo 状态。

---

### 3.2 `send_file` 与 `send_file_path`

`send_file_path` 是内部 helper，包含所有上传逻辑；`send_file` 是对外工具的薄包装。

| 属性 | 值 |
|------|-----|
| 工具位置 | `sebastian/capabilities/tools/send_file/__init__.py` |
| 工具名 | `send_file` |
| 权限 | `PermissionTier.MODEL_DECIDES` |
| 参数 | `file_path: str`（必填）、`display_name: str | None`（可选） |

`send_file_path` 依赖 `get_tool_context()` 获取 `session_id` 和 `agent_type`，供 `AttachmentStore.mark_agent_sent()` 使用。**它是专为工具调用栈内部设计的 helper，不是通用上传 API。**

**路径解析**：`sebastian.capabilities.tools._path_utils.resolve_path()`

**支持类型**：沿用 `AttachmentStore` 现有校验规则。

- 图片：`jpg/jpeg/png/webp/gif`，≤ 10 MB
- 文本文件：`txt/md/csv/json/log`，≤ 2 MB
- 其他类型返回 `ok=False`

**`display_name` 处理**：无后缀时追加源文件后缀；有后缀时原样使用。

**成功返回（图片）**：

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

**成功返回（文本文件）**：

```json
{
  "artifact": {
    "kind": "text_file",
    "attachment_id": "att-456",
    "filename": "notes.md",
    "mime_type": "text/markdown",
    "size_bytes": 500,
    "download_url": "/api/v1/attachments/att-456"
  }
}
```

> **实现差异**：原始 spec 设计 text_file artifact 包含 `text_excerpt` 字段；实际实现不含此字段，artifact 只有 `kind/attachment_id/filename/mime_type/size_bytes/download_url`。

`display` / `model_content` 仅记录轻量事实文本（`已向用户发送图片 photo.png`），不含 base64 或文件全文。

---

## 4. 后端数据流

### 4.1 AttachmentStore.mark_agent_sent

`send_file_path` 在 `upload_bytes()` 后调用 `mark_agent_sent()`：

```python
async def mark_agent_sent(
    self,
    attachment_id: str,
    agent_type: str,
    session_id: str,
) -> AttachmentRecord:
    ...
```

行为：
- 校验 record 存在且 `status == "uploaded"`
- 写入 `status="attached"`、`agent_type`、`session_id`、`attached_at`
- 防止 cleanup 将 Agent 发出的文件当临时 uploaded 附件删除
- 不新增 attachment session item

---

### 4.2 Tool Result Artifact 持久化

`send_file` 返回 `ToolResult.output["artifact"]`，持久化链路：

1. `stream_helpers.append_tool_result_block()` 从 `result.output` 提取 `artifact`
2. `session_timeline._normalize_block_payload()` 保留 `artifact` 到 payload
3. timeline API 返回 `tool_result.payload.artifact`

`tool_result.model_content` 保持轻量文本，LLM 不读取文件内容。

---

### 4.3 SSE 实时显示

`tool.executed` 事件扩展可选 `artifact` 字段：

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

语义：
- `ToolResult(ok=True)` → `tool.executed`（可携带 `artifact`）
- `ToolResult(ok=False)` → `tool.failed`（不携带 `artifact`）

Android 端对 SSE 事件和 timeline 历史的处理见 [mobile/attachments.md §12](../mobile/attachments.md)。

---

## 5. 工具失败返回规范

确定性失败必须返回稳定、可行动的错误，明确禁止自动重试。

**`send_file` 错误示例**：

| 失败原因 | error 文本模式 |
|---------|--------------|
| 无 session context | `send_file requires session context. Do not retry automatically; tell the user the file could not be sent in this conversation.` |
| 文件不存在 | `File not found: <path>. Do not retry automatically; ask the user to provide an existing file path.` |
| 路径是目录 | `Path is a directory, not a file: <path>. Do not retry automatically; ask the user for a file path.` |
| 不支持的类型 | `Unsupported file type: <suffix>. Do not retry automatically; only image and supported text files can be sent.` |
| 文件过大 | `... Do not retry automatically; ask the user to choose a smaller file.` |
| Attachment store 不可用 | `Attachment service is unavailable. Do not retry automatically; tell the user sending files is currently unavailable.` |

**`todo_read` 失败**：返回 `ToolResult(ok=False, error=...)`，不伪造状态。

**通用规范**（写入 `sebastian/capabilities/tools/README.md`）：

- 工具失败必须返回 `ToolResult(ok=False, error=...)`
- `error` 应含失败原因和下一步建议
- 确定性失败必须含 `Do not retry automatically; ...`
- 临时性失败可建议稍后重试，不可在同一 turn 内无限重试

---

## 6. 测试覆盖

主要测试文件：

- `tests/unit/capabilities/test_todo_read_tool.py`
- `tests/unit/capabilities/test_send_file_tool.py`
- `tests/unit/core/test_base_agent_provider.py`（`send_file` artifact 不泄漏至 LLM）
- `tests/integration/test_gateway_attachments.py`（timeline artifact 持久化）

关键场景：

- `todo_read` 有/无 session context，空/非空 todo
- `send_file` 图片/文本成功，各类确定性失败
- `mark_agent_sent` 成功绑定、冲突、not found
- `tool_result.payload.artifact` 在 timeline API 完整保留
- `tool.executed` 成功携带 artifact；失败走 `tool.failed` 路径
- `send_file_path` helper 直接调用与 `send_file` 薄包装一致

---

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
