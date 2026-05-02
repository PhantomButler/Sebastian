---
version: "1.0"
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

### 4. 后端：DB 记录写入 `display_name`

`stream_helpers.py` 在构造 `record` 时同步写入 `display_name`：

```python
record: dict[str, Any] = {
    "type": "tool",
    "tool_call_id": event.tool_id,
    "tool_name": event.name,
    "display_name": _resolve_display_name(event.name, event.inputs, spec_display_name),
    "input": event.inputs,
    ...
}
```

存进 DB 后，REST `/api/v1/sessions/{id}` 返回的 `blocks` 数组中对应 tool block 会携带 `display_name` 字段，供 timeline 水合时使用。旧记录该字段为 null，前端 fallback 到 `name`（历史数据显示原始名可接受）。

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

`spec_display_name` 通过 `get_tool(event.name)` 取到 `ToolSpec` 后读取；工具不存在时 fallback 到 `name`。

### 6. Android：`ContentBlock.ToolBlock` 加 `displayName`

文件：`ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`

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

### 7. Android：`SseFrameDto` 解析 `display_name`

三个 DTO（`ToolRunningDto` / `ToolExecutedDto` / `ToolFailedDto`）加 `val displayName: String?`，JSON key `"display_name"`。

### 8. Android：`BlockDto` 加 `display_name`（历史水合路径）

```kotlin
data class BlockDto(
    ...
    @param:Json(name = "display_name") val displayName: String? = null,
)
```

`MessageDto.toDomain()` 构造历史 `ToolBlock` 时：

```kotlin
name = b.name ?: "",
displayName = b.displayName ?: b.name ?: "",
```

### 9. Android：`ChatViewModel` 填充 `displayName`

处理 SSE 事件时，用 `dto.displayName ?: dto.name` 填入 `ToolBlock.displayName`。

### 10. Android：`ToolCallCard` 直接用 `block.displayName`

```kotlin
val displayName = block.displayName   // 不再调用 ToolDisplayName.resolve()
```

### 11. Android：删除 `ToolDisplayName.kt`

整个文件移除，不再需要。`ToolCallInputExtractor.kt` 保留不动（负责从 inputs 抽摘要，与显示名无关）。

---

## 数据流

```
Tool 定义
  @tool(display_name="Save Memory")
        ↓
  ToolSpec.display_name = "Save Memory"
        ↓
stream_helpers._resolve_display_name(name, inputs, spec_display_name)
        ↓ 计算结果："Save Memory"
        ├─ DB record["display_name"] = "Save Memory"
        │       ↓
        │  REST GET /sessions/{id} → BlockDto.displayName
        │       ↓
        │  MessageDto.toDomain() → ToolBlock.displayName（历史路径）
        │
        └─ SSE: { "display_name": "Save Memory", "name": "memory_save", ... }
                ↓
           Android SseFrameDto.displayName
                ↓
           ChatViewModel → ToolBlock.displayName（实时路径）

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
| `sebastian/core/tool.py` | 加字段 |
| `sebastian/capabilities/tools/*/\_\_init\_\_.py`（约 13 个） | 补 `display_name` 参数 |
| `sebastian/core/stream_helpers.py` | 加 `_resolve_display_name` 函数 + 3 处事件数据 + DB record |
| `ContentBlock.kt` | 加字段 |
| `SseFrameDto.kt` | 加字段（3 个 DTO） |
| `MessageDto.kt` / `BlockDto.kt` | 加 `display_name` 字段 |
| `ChatViewModel.kt` | 填充逻辑更新 |
| `ToolCallCard.kt` | 读字段改动 |
| `ToolDisplayName.kt` | **删除** |
