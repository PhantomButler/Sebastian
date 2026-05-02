---
version: "1.1"
last_updated: 2026-05-02
status: planned
---

# Tool Display Name 后端化设计

## 背景与目标

当前 App 端维护 `ToolDisplayName.kt`，手动映射工具内部名 → UI 显示名。每新增一个工具，若未加进映射表，卡片 header 直接显示 snake_case 原始名（如 `memory_save`）。

目标：将显示名的定义权移到后端，App 只消费后端传来的值，新增工具无需改前端。

---

## 设计方案

### 1. 后端：`ToolSpec` 加 `display_name` 字段

文件：`sebastian/core/tool.py`

```python
class ToolSpec:
    __slots__ = ("name", "description", "parameters", "permission_tier", "display_name")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        permission_tier: PermissionTier = PermissionTier.LOW,
        display_name: str | None = None,
    ) -> None:
        ...
        self.display_name = display_name  # None → fallback 到 name
```

`@tool()` 装饰器同步加 `display_name: str | None = None` 参数，传给 `ToolSpec`。

### 2. 后端：现有工具补标注

所有工具 `@tool()` 调用补 `display_name`（全英文）。内部名本身已是好名字的（`Read` / `Write` / `Bash` / `Edit` / `Glob` / `Grep`）无需填，其余补全：

| 工具 `name` | `display_name` |
|---|---|
| `spawn_sub_agent` | `"Worker"` |
| `delegate_to_agent` | `"Agent"` |
| `stop_agent` | `"Stop Agent"` |
| `resume_agent` | `"Resume Agent"` |
| `ask_parent` | `"Ask Parent"` |
| `check_sub_agents` | `"Check Workers"` |
| `inspect_session` | `"Inspect Session"` |
| `memory_save` | `"Save Memory"` |
| `memory_search` | `"Search Memory"` |
| `todo_read` | `"Read Todos"` |
| `todo_write` | `"Update Todos"` |
| `send_file` | `"Send File"` |
| `screenshot_send` | `"Take Screenshot"` |

### 3. 后端：`stream_helpers.py` 加 `_resolve_display_name`

在发 SSE 事件前计算最终显示名，处理动态拼接的 4 个特殊工具：

```python
from sebastian.core.tool import get_tool   # 新增 import

def _resolve_display_name(
    name: str,
    inputs: dict[str, Any],
    spec_display_name: str | None,
) -> str:
    agent_type = inputs.get("agent_type", "") if isinstance(inputs, dict) else ""
    match name:
        case "delegate_to_agent":
            return f"Agent: {agent_type.capitalize()}" if agent_type else "Agent"
        case "stop_agent":
            return f"Stop Agent: {agent_type.capitalize()}" if agent_type else "Stop Agent"
        case "resume_agent":
            return f"Resume Agent: {agent_type.capitalize()}" if agent_type else "Resume Agent"
        case "spawn_sub_agent":
            return "Worker"
    return spec_display_name or name
```

调用方 `dispatch_tool_call` 在调用前先取 spec：

```python
tool_entry = get_tool(event.name)
spec_display_name = tool_entry[0].display_name if tool_entry else None
display_name = _resolve_display_name(event.name, event.inputs, spec_display_name)
```

> **注意**：`get_tool` 目前未在 `stream_helpers.py` 中 import，需要在文件顶部添加。

### 4. 后端：DB 记录写入 `display_name`

`stream_helpers.py` 在构造 `record` 时同步写入 `display_name`：

```python
record: dict[str, Any] = {
    "type": "tool",
    "tool_call_id": event.tool_id,
    "tool_name": event.name,
    "display_name": display_name,
    "input": event.inputs,
    ...
}
```

存进 DB 后，REST `/api/v1/sessions/{id}` 返回的 `timelineItems` 中对应 tool_call item 会携带 `display_name` 字段。旧记录该字段为 null，前端 fallback 到 `name`（历史数据显示原始名可接受）。

### 5. 后端：SSE 事件加 `display_name` 字段

三个 tool 相关事件统一加字段：

**`TOOL_RUNNING`**
```json
{
  "tool_id": "...",
  "name": "memory_save",
  "display_name": "Save Memory",
  "input": { ... }
}
```

**`TOOL_EXECUTED`**
```json
{
  "tool_id": "...",
  "name": "memory_save",
  "display_name": "Save Memory",
  "result_summary": "..."
}
```

**`TOOL_FAILED`**
```json
{
  "tool_id": "...",
  "name": "memory_save",
  "display_name": "Save Memory",
  "error": "..."
}
```

### 6. Android：`ContentBlock.ToolBlock` 加 `displayName`

文件：`ContentBlock.kt`

```kotlin
data class ToolBlock(
    val toolId: String,
    val name: String,         // 保留，供 ToolCallInputExtractor 使用
    val displayName: String,  // 新增，来自后端，直接用于 UI
    val inputs: String,
    val status: ToolStatus,
    ...
) : ContentBlock()
```

### 7. Android：`StreamEvent.kt` 加 `displayName` 字段

实际 SSE 架构：`SseFrameParser.parseByType()` → `StreamEvent.*` → `ChatViewModel.handleEvent()`，不存在命名 DTO 类，`SseFrameDto.kt` 里是手动 JSON 解析（无 Moshi 注解）。

需修改 `StreamEvent.kt` 的三个数据类：

```kotlin
data class ToolRunning(
    val sessionId: String,
    val toolId: String,
    val name: String,
    val displayName: String,   // 新增
) : StreamEvent()

data class ToolExecuted(
    val sessionId: String,
    val toolId: String,
    val name: String,
    val displayName: String,   // 新增
    val resultSummary: String,
    val artifact: AttachmentArtifact? = null,
) : StreamEvent()

data class ToolFailed(
    val sessionId: String,
    val toolId: String,
    val name: String,
    val displayName: String,   // 新增
    val error: String,
) : StreamEvent()
```

同步修改 `SseFrameDto.kt` 中 `parseByType()` 的手动解析：

```kotlin
"tool.running" -> StreamEvent.ToolRunning(
    data.getString("session_id"),
    data.getString("tool_id"),
    data.getString("name"),
    data.optString("display_name", data.getString("name")),  // fallback 到 name
)
"tool.executed" -> StreamEvent.ToolExecuted(
    data.getString("session_id"),
    data.getString("tool_id"),
    data.getString("name"),
    data.optString("display_name", data.getString("name")),  // fallback 到 name
    data.optString("result_summary", ""),
    data.optJSONObject("artifact")?.toArtifactOrNull(),
)
"tool.failed" -> StreamEvent.ToolFailed(
    data.getString("session_id"),
    data.getString("tool_id"),
    data.getString("name"),
    data.optString("display_name", data.getString("name")),  // fallback 到 name
    data.optString("error", ""),
)
```

### 8. Android：`ChatViewModel` 处理 `displayName` 时序

`ToolBlock` 在 `ToolBlockStart` 时创建，此时后端尚未发送 `TOOL_RUNNING`，`display_name` 未知。处理方式：

- `ToolBlockStart`：`displayName = event.name`（用原始名作初始 fallback）
- `ToolRunning`：`existing.copy(status = RUNNING, displayName = event.displayName)`（更新为正式显示名）

```kotlin
is StreamEvent.ToolBlockStart -> {
    val block = ContentBlock.ToolBlock(
        blockId = event.blockId,
        toolId = event.toolId,
        name = event.name,
        displayName = event.name,   // 初始 fallback
        inputs = "",
        status = ToolStatus.PENDING,
    )
    appendBlockToCurrentMessage(block, ...)
}

is StreamEvent.ToolRunning -> {
    updateToolBlockByToolId(event.toolId) { existing ->
        existing.copy(status = ToolStatus.RUNNING, displayName = event.displayName)
    }
}
```

`ToolExecuted` / `ToolFailed` 同样可顺带 copy `displayName`，确保最终状态一致。

### 9. Android：`TimelineMapper.kt` 加 `displayName`（历史加载主路径）

历史会话加载主路径为 `toMessagesFromTimeline()` → `buildAssistantBlocks()`，不是 `BlockDto.toDomain()`（后者是 legacy fallback）。

文件：`TimelineMapper.kt`，在 `tool_call` block 的 `ToolBlock` 构造处：

```kotlin
blocks += ContentBlock.ToolBlock(
    blockId = item.stableBlockId(),
    toolId = callId,
    name = toolName,
    displayName = item.payloadString("display_name") ?: toolName,  // 新增
    inputs = item.content ?: "",
    status = status,
    resultSummary = ...,
    error = ...,
)
```

### 10. Android：`ToolCallCard` 直接用 `block.displayName`

```kotlin
val displayName = block.displayName   // 不再调用 ToolDisplayName.resolve()
```

### 11. Android：`BlockDto.kt` 加 `display_name`（兼容性补全，低优先级）

`MessageDto.toDomain()` 是 legacy fallback，SQLite 模式下 `timelineItems` 非空时不走此路径。可选补全：

```kotlin
data class BlockDto(
    ...
    @param:Json(name = "display_name") val displayName: String? = null,
)
// MessageDto.toDomain() 构造 ToolBlock 时：
displayName = b.displayName ?: b.name ?: "",
```

### 12. Android：删除 `ToolDisplayName.kt`

整个文件移除，不再需要。`ToolCallInputExtractor.kt` 保留不动。

---

## 数据流

```
Tool 定义
  @tool(display_name="Save Memory")
        ↓
  ToolSpec.display_name = "Save Memory"
        ↓
stream_helpers.dispatch_tool_call
  get_tool(name) → spec_display_name
  _resolve_display_name(name, inputs, spec_display_name) → "Save Memory"
        ↓
        ├─ DB record["display_name"] = "Save Memory"
        │       ↓
        │  REST → TimelineItems → TimelineMapper
        │  item.payloadString("display_name") ?: toolName
        │       ↓
        │  ToolBlock.displayName（历史路径）
        │
        └─ SSE: { "display_name": "Save Memory", "name": "memory_save", ... }
                ↓
           SseFrameParser → StreamEvent.ToolRunning(displayName="Save Memory")
                ↓
           ChatViewModel.ToolRunning → existing.copy(displayName=event.displayName)
                ↓
           ToolBlock.displayName（实时路径）

ToolBlock.displayName → ToolCallCard header 显示 "Save Memory"
```

---

## 不改动的部分

- `ToolCallInputExtractor.kt`：负责从 inputs JSON 提取参数摘要，与显示名正交，保持不变
- `ToolResult.display`：工具执行结果的人类可读摘要，独立字段，不受影响
- SSE 协议的 `name` 字段：保留，供前端逻辑判断使用（不能删）

---

## 影响范围

| 文件 | 变更类型 |
|---|---|
| `sebastian/core/tool.py` | 加 `display_name` 字段 |
| `sebastian/capabilities/tools/*/\_\_init\_\_.py`（约 13 个） | 补 `display_name` 参数 |
| `sebastian/core/stream_helpers.py` | 加 `get_tool` import、`_resolve_display_name` 函数、DB record 字段、3 处 SSE 事件数据 |
| `StreamEvent.kt` | 三个 tool 事件数据类加 `displayName: String` |
| `SseFrameDto.kt`（`parseByType`） | 三处手动解析加 `optString("display_name", name)` |
| `ContentBlock.kt` | `ToolBlock` 加 `displayName: String` |
| `TimelineMapper.kt` | `tool_call` block 构造处加 `displayName` 读取 |
| `ChatViewModel.kt` | `ToolBlockStart` 初始化 + `ToolRunning` 更新逻辑 |
| `ToolCallCard.kt` | 读 `block.displayName`，移除 `ToolDisplayName.resolve()` 调用 |
| `ToolDisplayName.kt` | **删除** |
| `MessageDto.kt` / `BlockDto.kt` | 可选兼容性补全（低优先级） |
