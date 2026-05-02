# Tool Display Name 后端化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将工具 UI 显示名从 Android 前端映射表移到后端 `@tool()` 装饰器，通过 SSE 事件和 REST timeline 传给 App，新增工具无需改前端。

**Architecture:** 后端 `ToolSpec` 新增 `display_name` 字段，`stream_helpers.py` 在发 SSE 事件时计算最终显示名（含动态拼接）并写入 DB record；Android 的 `StreamEvent` / `TimelineMapper` 接收并填入 `ContentBlock.ToolBlock.displayName`，`ToolCallCard` 直接读取，`ToolDisplayName.kt` 整个删除。

**Tech Stack:** Python 3.12 / pytest-asyncio（后端），Kotlin / Jetpack Compose / JUnit4（Android）

---

## 文件变更总览

| 文件 | 操作 |
|---|---|
| `sebastian/core/tool.py` | 改：`ToolSpec` 加 `display_name`；`@tool()` 加参数 |
| `sebastian/core/stream_helpers.py` | 改：加 `get_tool` import、`_resolve_display_name` 函数、更新 `dispatch_tool_call` |
| `sebastian/capabilities/tools/*/\_\_init\_\_.py`（13 个） | 改：补 `display_name=` 参数 |
| `tests/unit/capabilities/test_tool_decorator.py` | 改：补 `display_name` 测试 |
| `tests/unit/core/test_stream_helpers.py` | 改：补 `_resolve_display_name` 测试 |
| `ContentBlock.kt` | 改：`ToolBlock` 加 `displayName: String = ""` |
| `StreamEvent.kt` | 改：`ToolRunning` / `ToolExecuted` / `ToolFailed` 加 `displayName` |
| `SseFrameDto.kt` | 改：`parseByType` 3 处加 `optString("display_name", name)` |
| `TimelineMapper.kt` | 改：`tool_call` 和孤儿 `tool_result` 两处构造补 `displayName` |
| `ChatViewModel.kt` | 改：`ToolBlockStart` 初始化 + `ToolRunning/Executed/Failed` 更新 |
| `ToolCallCard.kt` | 改：用 `block.displayName` 替换 `ToolDisplayName.resolve()` |
| `BlockDto.kt` / `MessageDto.kt` | 改：legacy 兼容补全（低优先级，Task 8 末尾） |
| `ToolDisplayName.kt` | **删除** |
| `ToolDisplayNameTest.kt` | **删除** |
| `TimelineMapperTest.kt` | 改：补 `displayName` 断言 |
| `ChatViewModelTest.kt` | 改：更新 `ToolExecuted` / `ToolFailed` 构造调用 |

---

## Task 1：后端 — ToolSpec + @tool 装饰器加 display_name 字段

**Files:**
- Modify: `sebastian/core/tool.py`
- Modify: `tests/unit/capabilities/test_tool_decorator.py`

- [ ] **Step 1：写失败测试**

在 `tests/unit/capabilities/test_tool_decorator.py` 末尾追加：

```python
def test_tool_display_name_stored_in_spec() -> None:
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="fancy_tool", description="test", display_name="Fancy Tool")
    async def fancy(x: str) -> ToolResult:
        return ToolResult(ok=True, output=x)

    spec, _ = tool_module._tools["fancy_tool"]
    assert spec.display_name == "Fancy Tool"


def test_tool_display_name_defaults_to_none() -> None:
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="plain_tool", description="test")
    async def plain(x: str) -> ToolResult:
        return ToolResult(ok=True, output=x)

    spec, _ = tool_module._tools["plain_tool"]
    assert spec.display_name is None
```

- [ ] **Step 2：运行测试，确认失败**

```bash
pytest tests/unit/capabilities/test_tool_decorator.py::test_tool_display_name_stored_in_spec -v
```

期望：`FAILED` — `TypeError: tool() got an unexpected keyword argument 'display_name'`

- [ ] **Step 3：修改 `sebastian/core/tool.py`**

将 `ToolSpec` 的 `__slots__` 和 `__init__` 改为：

```python
class ToolSpec:
    """Specification and metadata for a registered tool."""

    __slots__ = ("name", "description", "parameters", "permission_tier", "display_name")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        permission_tier: PermissionTier = PermissionTier.LOW,
        display_name: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.permission_tier = permission_tier
        self.display_name = display_name
```

将 `tool()` 装饰器签名和内部 `ToolSpec(...)` 构造改为：

```python
def tool(
    name: str,
    description: str,
    permission_tier: PermissionTier = PermissionTier.MODEL_DECIDES,
    display_name: str | None = None,
) -> Callable[[ToolFn], ToolFn]:
    """Decorator that registers an async function as a callable tool."""

    def decorator(fn: ToolFn) -> ToolFn:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=_infer_json_schema(fn),
            permission_tier=permission_tier,
            display_name=display_name,
        )
        ...
```

- [ ] **Step 4：运行测试，确认通过**

```bash
pytest tests/unit/capabilities/test_tool_decorator.py -v
```

期望：所有测试 `PASSED`

- [ ] **Step 5：提交**

```bash
git add sebastian/core/tool.py tests/unit/capabilities/test_tool_decorator.py
git commit -m "feat(core): ToolSpec 和 @tool 装饰器加 display_name 字段"
```

---

## Task 2：后端 — stream_helpers.py 加 `_resolve_display_name`

**Files:**
- Modify: `sebastian/core/stream_helpers.py`
- Modify: `tests/unit/core/test_stream_helpers.py`

- [ ] **Step 1：写失败测试**

在 `tests/unit/core/test_stream_helpers.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# _resolve_display_name
# ---------------------------------------------------------------------------


def test_resolve_display_name_delegate_with_agent_type() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("delegate_to_agent", {"agent_type": "forge"}, None)
    assert result == "Agent: Forge"


def test_resolve_display_name_delegate_without_agent_type() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("delegate_to_agent", {}, None)
    assert result == "Agent"


def test_resolve_display_name_stop_agent() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("stop_agent", {"agent_type": "forge"}, None)
    assert result == "Stop Agent: Forge"


def test_resolve_display_name_resume_agent() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("resume_agent", {"agent_type": "builder"}, None)
    assert result == "Resume Agent: Builder"


def test_resolve_display_name_spawn_sub_agent() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("spawn_sub_agent", {"goal": "do stuff"}, "Worker")
    assert result == "Worker"


def test_resolve_display_name_uses_spec_display_name() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("memory_save", {}, "Save Memory")
    assert result == "Save Memory"


def test_resolve_display_name_falls_back_to_name() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("some_tool", {}, None)
    assert result == "some_tool"


def test_resolve_display_name_non_dict_inputs() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("delegate_to_agent", "not-a-dict", None)
    assert result == "Agent"
```

- [ ] **Step 2：运行测试，确认失败**

```bash
pytest tests/unit/core/test_stream_helpers.py::test_resolve_display_name_delegate_with_agent_type -v
```

期望：`FAILED` — `ImportError: cannot import name '_resolve_display_name'`

- [ ] **Step 3：在 `sebastian/core/stream_helpers.py` 中加 `_resolve_display_name`**

在 `logger = logging.getLogger(__name__)` 之后、`_DISPLAY_MAX` 之前插入：

```python
def _resolve_display_name(
    name: str,
    inputs: dict[str, Any],
    spec_display_name: str | None,
) -> str:
    """Compute the UI display name for a tool call.

    Handles four tools that need dynamic titles built from inputs;
    all others use spec_display_name or fall back to the internal name.
    """
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

- [ ] **Step 4：运行测试，确认全部通过**

```bash
pytest tests/unit/core/test_stream_helpers.py -v
```

期望：所有测试 `PASSED`

- [ ] **Step 5：提交**

```bash
git add sebastian/core/stream_helpers.py tests/unit/core/test_stream_helpers.py
git commit -m "feat(core): stream_helpers 加 _resolve_display_name"
```

---

## Task 3：后端 — dispatch_tool_call 接入 display_name

**Files:**
- Modify: `sebastian/core/stream_helpers.py`

- [ ] **Step 1：在 `stream_helpers.py` 顶部加 import**

在现有 import 块末尾追加：

```python
from sebastian.core.tool import get_tool
```

- [ ] **Step 2：在 `dispatch_tool_call` 中计算 display_name**

在 `dispatch_tool_call` 函数体内，位于 `from sebastian.protocol.events.types import EventType` 之后立即插入：

```python
    tool_entry = get_tool(event.name)
    spec_display_name = tool_entry[0].display_name if tool_entry else None
    display_name = _resolve_display_name(event.name, event.inputs, spec_display_name)
```

- [ ] **Step 3：更新 TOOL_RUNNING 事件数据**

将：
```python
    await publish(
        session_id,
        EventType.TOOL_RUNNING,
        {"tool_id": event.tool_id, "name": event.name, "input": event.inputs},
    )
```

改为：
```python
    await publish(
        session_id,
        EventType.TOOL_RUNNING,
        {"tool_id": event.tool_id, "name": event.name, "display_name": display_name, "input": event.inputs},
    )
```

- [ ] **Step 4：更新 DB record**

将：
```python
    record: dict[str, Any] = {
        "type": "tool",
        "tool_call_id": event.tool_id,
        "tool_name": event.name,
        "input": event.inputs,
        "status": "failed",
```

改为：
```python
    record: dict[str, Any] = {
        "type": "tool",
        "tool_call_id": event.tool_id,
        "tool_name": event.name,
        "display_name": display_name,
        "input": event.inputs,
        "status": "failed",
```

- [ ] **Step 5：更新 TOOL_EXECUTED 事件数据**

将：
```python
        event_data: dict[str, Any] = {
            "tool_id": event.tool_id,
            "name": event.name,
            "result_summary": display,
        }
```

改为：
```python
        event_data: dict[str, Any] = {
            "tool_id": event.tool_id,
            "name": event.name,
            "display_name": display_name,
            "result_summary": display,
        }
```

- [ ] **Step 6：更新两处 TOOL_FAILED 事件数据**

第一处（dispatch 异常路径）将：
```python
        await publish(
            session_id,
            EventType.TOOL_FAILED,
            {"tool_id": event.tool_id, "name": event.name, "error": error},
        )
```

改为：
```python
        await publish(
            session_id,
            EventType.TOOL_FAILED,
            {"tool_id": event.tool_id, "name": event.name, "display_name": display_name, "error": error},
        )
```

第二处（result.ok == False 路径）将：
```python
        await publish(
            session_id,
            EventType.TOOL_FAILED,
            {"tool_id": event.tool_id, "name": event.name, "error": result.error},
        )
```

改为：
```python
        await publish(
            session_id,
            EventType.TOOL_FAILED,
            {"tool_id": event.tool_id, "name": event.name, "display_name": display_name, "error": result.error},
        )
```

- [ ] **Step 7：运行后端测试，确认无回归**

```bash
pytest tests/unit/core/ -v
```

期望：所有测试 `PASSED`

- [ ] **Step 8：提交**

```bash
git add sebastian/core/stream_helpers.py
git commit -m "feat(core): dispatch_tool_call 将 display_name 注入 SSE 事件和 DB record"
```

---

## Task 4：后端 — 13 个工具补 display_name 标注

**Files:**
- Modify: 各 `sebastian/capabilities/tools/*/\_\_init\_\_.py`

- [ ] **Step 1：`delegate_to_agent`**

文件：`sebastian/capabilities/tools/delegate_to_agent/__init__.py`

将：
```python
@tool(
    name="delegate_to_agent",
    description="委派任务给指定的下属 Agent。任务将异步执行，你可以继续处理其他事务。",
    permission_tier=PermissionTier.LOW,
)
```
改为：
```python
@tool(
    name="delegate_to_agent",
    description="委派任务给指定的下属 Agent。任务将异步执行，你可以继续处理其他事务。",
    permission_tier=PermissionTier.LOW,
    display_name="Agent",
)
```

- [ ] **Step 2：`spawn_sub_agent`**

文件：`sebastian/capabilities/tools/spawn_sub_agent/__init__.py`（`@tool` 在第 39 行）

在现有 `@tool(...)` 的最后一个参数后追加 `display_name="Worker",`。

- [ ] **Step 3：`stop_agent`**

文件：`sebastian/capabilities/tools/stop_agent/__init__.py`

在 `@tool(...)` 追加 `display_name="Stop Agent",`。

- [ ] **Step 4：`resume_agent`**

文件：`sebastian/capabilities/tools/resume_agent/__init__.py`

在 `@tool(...)` 追加 `display_name="Resume Agent",`。

- [ ] **Step 5：`ask_parent`**

文件：`sebastian/capabilities/tools/ask_parent/__init__.py`

在 `@tool(...)` 追加 `display_name="Ask Parent",`。

- [ ] **Step 6：`check_sub_agents`**

文件：`sebastian/capabilities/tools/check_sub_agents/__init__.py`

在 `@tool(...)` 追加 `display_name="Check Workers",`。

- [ ] **Step 7：`inspect_session`**

文件：`sebastian/capabilities/tools/inspect_session/__init__.py`

在 `@tool(...)` 追加 `display_name="Inspect Session",`。

- [ ] **Step 8：`memory_save`**

文件：`sebastian/capabilities/tools/memory_save/__init__.py`

在 `@tool(...)` 追加 `display_name="Save Memory",`。

- [ ] **Step 9：`memory_search`**

文件：`sebastian/capabilities/tools/memory_search/__init__.py`

在 `@tool(...)` 追加 `display_name="Search Memory",`。

- [ ] **Step 10：`todo_read`**

文件：`sebastian/capabilities/tools/todo_read/__init__.py`

在 `@tool(...)` 追加 `display_name="Read Todos",`。

- [ ] **Step 11：`todo_write`**

文件：`sebastian/capabilities/tools/todo_write/__init__.py`

在 `@tool(...)` 追加 `display_name="Update Todos",`。

- [ ] **Step 12：`send_file`**

文件：`sebastian/capabilities/tools/send_file/__init__.py`（`@tool` 在第 184 行）

在 `@tool(...)` 追加 `display_name="Send File",`。

- [ ] **Step 13：`screenshot_send`**

文件：`sebastian/capabilities/tools/screenshot_send/__init__.py`（`@tool` 在第 158 行）

在 `@tool(...)` 追加 `display_name="Take Screenshot",`。

- [ ] **Step 14：运行工具相关单元测试**

```bash
pytest tests/unit/capabilities/ -v
```

期望：所有测试 `PASSED`

- [ ] **Step 15：提交**

```bash
git add sebastian/capabilities/tools/delegate_to_agent/__init__.py \
        sebastian/capabilities/tools/spawn_sub_agent/__init__.py \
        sebastian/capabilities/tools/stop_agent/__init__.py \
        sebastian/capabilities/tools/resume_agent/__init__.py \
        sebastian/capabilities/tools/ask_parent/__init__.py \
        sebastian/capabilities/tools/check_sub_agents/__init__.py \
        sebastian/capabilities/tools/inspect_session/__init__.py \
        sebastian/capabilities/tools/memory_save/__init__.py \
        sebastian/capabilities/tools/memory_search/__init__.py \
        sebastian/capabilities/tools/todo_read/__init__.py \
        sebastian/capabilities/tools/todo_write/__init__.py \
        sebastian/capabilities/tools/send_file/__init__.py \
        sebastian/capabilities/tools/screenshot_send/__init__.py
git commit -m "feat(tools): 所有工具补 display_name 标注"
```

---

## Task 5：Android — ContentBlock.ToolBlock 加 displayName

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`（ToolBlockStart handler）
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt`（两处）
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MessageDto.kt` + `BlockDto`（legacy）
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt`

- [ ] **Step 1：`ContentBlock.ToolBlock` 加 `displayName`**

在 `ContentBlock.kt` 将 `ToolBlock` 改为：

```kotlin
data class ToolBlock(
    override val blockId: String,
    val toolId: String,
    val name: String,
    val displayName: String = "",  // UI 显示名，来自后端；空串作 fallback
    val inputs: String,
    val status: ToolStatus,
    val resultSummary: String? = null,
    val error: String? = null,
    val expanded: Boolean = false,
) : ContentBlock()
```

- [ ] **Step 2：更新 `ChatViewModel.kt` 的 `ToolBlockStart` handler**

在 `ChatViewModel.kt` 找到 `is StreamEvent.ToolBlockStart ->` 块，将 `ContentBlock.ToolBlock(...)` 构造改为：

```kotlin
is StreamEvent.ToolBlockStart -> {
    val block = ContentBlock.ToolBlock(
        blockId = event.blockId,
        toolId = event.toolId,
        name = event.name,
        displayName = event.name,  // 初始 fallback，ToolRunning 时会更新
        inputs = "",
        status = ToolStatus.PENDING,
    )
    appendBlockToCurrentMessage(block, composerState = ComposerState.STREAMING, agentAnimState = AgentAnimState.WORKING)
}
```

- [ ] **Step 3：更新 `TimelineMapper.kt` 的 `tool_call` 分支**

找到 `"tool_call" ->` 分支里的 `blocks += ContentBlock.ToolBlock(...)` 构造，加入 `displayName`：

```kotlin
blocks += ContentBlock.ToolBlock(
    blockId = item.stableBlockId(),
    toolId = callId,
    name = toolName,
    displayName = item.payloadString("display_name") ?: toolName,
    inputs = item.content ?: "",
    status = status,
    resultSummary = result?.payloadString("display") ?: result?.content,
    error = if (status == ToolStatus.FAILED) result?.payloadString("error") else null,
)
```

- [ ] **Step 4：更新 `TimelineMapper.kt` 的孤儿 `tool_result` 分支**

找到 `"tool_result" ->` 分支里的 `blocks += ContentBlock.ToolBlock(...)` 构造，加入 `displayName`：

```kotlin
blocks += ContentBlock.ToolBlock(
    blockId = "timeline-$sessionId-tool-result-${item.seq}",
    toolId = callId,
    name = "",
    displayName = "",
    inputs = "",
    status = if (failed) ToolStatus.FAILED else ToolStatus.DONE,
    resultSummary = item.payloadString("display") ?: item.content,
    error = if (failed) item.payloadString("error") else null,
)
```

- [ ] **Step 5：legacy — 更新 `MessageDto.kt` 的 `BlockDto` 和 `toDomain()`**

在 `BlockDto` 加字段：

```kotlin
@param:Json(name = "display_name") val displayName: String? = null,
```

在 `MessageDto.toDomain()` 的 `"tool" ->` 分支里改为：

```kotlin
"tool" -> contentBlocks.add(
    ContentBlock.ToolBlock(
        blockId = "$msgId-tool-$i",
        toolId = b.toolId ?: "$msgId-tool-$i",
        name = b.name ?: "",
        displayName = b.displayName ?: b.name ?: "",
        inputs = b.input ?: "",
        status = if (b.status == "failed") ToolStatus.FAILED else ToolStatus.DONE,
        resultSummary = b.result,
    )
)
```

- [ ] **Step 6：更新 `TimelineMapperTest.kt`，补 displayName 断言**

在 `mergesToolCallAndResultByToolCallId` 测试末尾（`assertEquals("done", block.resultSummary)` 之后）追加：

```kotlin
assertEquals("web_search", block.displayName)  // 无 display_name payload，fallback 到 toolName
```

在 `orphanToolResultCreatesMinimalToolBlock` 测试末尾追加：

```kotlin
assertEquals("", block.displayName)
```

- [ ] **Step 7：运行 TimelineMapper 测试**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.dto.TimelineMapperTest" -x lint
```

期望：所有测试 `PASSED`

- [ ] **Step 8：提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MessageDto.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt
git commit -m "feat(android): ToolBlock 加 displayName，补全所有构造点"
```

---

## Task 6：Android — StreamEvent.kt + SseFrameDto.kt 加 displayName

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1：更新 `StreamEvent.kt` 三个数据类**

`ToolRunning`（在 `name` 后插入 `displayName`；无现有测试构造，不影响兼容性）：

```kotlin
data class ToolRunning(
    val sessionId: String,
    val toolId: String,
    val name: String,
    val displayName: String = "",
) : StreamEvent()
```

`ToolExecuted`（放在 `artifact` 之后，因为 `ChatViewModelTest.kt:1189` 用位置参数传 `artifact`，插在中间会类型不匹配）：

```kotlin
data class ToolExecuted(
    val sessionId: String,
    val toolId: String,
    val name: String,
    val resultSummary: String,
    val artifact: AttachmentArtifact? = null,
    val displayName: String = "",
) : StreamEvent()
```

`ToolFailed`（在末尾插入，现有测试用具名参数，不受影响）：

```kotlin
data class ToolFailed(
    val sessionId: String,
    val toolId: String,
    val name: String,
    val error: String,
    val displayName: String = "",
) : StreamEvent()
```

- [ ] **Step 2：更新 `SseFrameDto.kt` 的 `parseByType()` 三处**

将：
```kotlin
"tool.running" -> StreamEvent.ToolRunning(data.getString("session_id"), data.getString("tool_id"), data.getString("name"))
```
改为：
```kotlin
"tool.running" -> StreamEvent.ToolRunning(
    data.getString("session_id"),
    data.getString("tool_id"),
    data.getString("name"),
    data.optString("display_name", data.getString("name")),
)
```

将：
```kotlin
"tool.executed" -> StreamEvent.ToolExecuted(
    data.getString("session_id"),
    data.getString("tool_id"),
    data.getString("name"),
    data.optString("result_summary", ""),
    data.optJSONObject("artifact")?.toArtifactOrNull(),
)
```
改为：
```kotlin
"tool.executed" -> StreamEvent.ToolExecuted(
    sessionId = data.getString("session_id"),
    toolId = data.getString("tool_id"),
    name = data.getString("name"),
    resultSummary = data.optString("result_summary", ""),
    artifact = data.optJSONObject("artifact")?.toArtifactOrNull(),
    displayName = data.optString("display_name", data.getString("name")),
)
```

将：
```kotlin
"tool.failed" -> StreamEvent.ToolFailed(data.getString("session_id"), data.getString("tool_id"), data.getString("name"), data.optString("error", ""))
```
改为：
```kotlin
"tool.failed" -> StreamEvent.ToolFailed(
    data.getString("session_id"),
    data.getString("tool_id"),
    data.getString("name"),
    data.optString("error", ""),
    data.optString("display_name", data.getString("name")),
)
```

- [ ] **Step 3：运行全量 Android 单元测试，确认编译通过且无回归**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest -x lint
```

期望：所有测试 `PASSED`

- [ ] **Step 4：提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt
git commit -m "feat(android): StreamEvent ToolRunning/Executed/Failed 加 displayName，更新 SSE 解析"
```

---

## Task 7：Android — ChatViewModel 更新 ToolRunning/Executed/Failed handler

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`

- [ ] **Step 1：更新 `ToolRunning` handler**

找到 `is StreamEvent.ToolRunning ->` 块，改为：

```kotlin
is StreamEvent.ToolRunning -> {
    updateToolBlockByToolId(event.toolId) { existing ->
        existing.copy(status = ToolStatus.RUNNING, displayName = event.displayName)
    }
}
```

- [ ] **Step 2：更新 `ToolExecuted` handler**

找到 `is StreamEvent.ToolExecuted ->` 块中的 `else` 分支，改为：

```kotlin
} else {
    updateToolBlockByToolId(event.toolId) { existing ->
        existing.copy(
            status = ToolStatus.DONE,
            resultSummary = event.resultSummary,
            displayName = event.displayName,
        )
    }
}
```

（artifact 路径保持原逻辑，不修改）

- [ ] **Step 3：更新 `ToolFailed` handler**

找到 `is StreamEvent.ToolFailed ->` 块，改为：

```kotlin
is StreamEvent.ToolFailed -> {
    updateToolBlockByToolId(event.toolId) { existing ->
        existing.copy(
            status = ToolStatus.FAILED,
            error = event.error,
            displayName = event.displayName,
        )
    }
}
```

- [ ] **Step 4：运行 ChatViewModel 测试**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest" -x lint
```

期望：所有测试 `PASSED`

- [ ] **Step 5：提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt
git commit -m "feat(android): ChatViewModel tool 事件 handler 更新 displayName"
```

---

## Task 8：Android — ToolCallCard 接入 displayName + 删除 ToolDisplayName

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallCard.kt`
- Delete: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt`
- Delete: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolDisplayNameTest.kt`

- [ ] **Step 1：修改 `ToolCallCard.kt`**

找到：
```kotlin
val display = remember(block.name, block.inputs) {
    ToolDisplayName.resolve(block.name, block.inputs)
}
val displayName = display.title
val summary = display.summary
```

改为：
```kotlin
val displayName = block.displayName
val summary = remember(block.name, block.inputs) {
    ToolCallInputExtractor.extractInputSummary(block.name, block.inputs)
}
```

同时删除文件顶部对 `ToolDisplayName` 的任何 import（如有）。

- [ ] **Step 2：删除 `ToolDisplayName.kt`**

```bash
rm ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt
```

- [ ] **Step 3：删除 `ToolDisplayNameTest.kt`**

```bash
rm ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolDisplayNameTest.kt
```

- [ ] **Step 4：运行全量 Android 单元测试**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest -x lint
```

期望：所有测试 `PASSED`，`ToolDisplayNameTest` 不再出现

- [ ] **Step 5：提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallCard.kt
git rm ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt
git rm ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolDisplayNameTest.kt
git commit -m "feat(android): ToolCallCard 使用后端 displayName，删除 ToolDisplayName.kt"
```

---

## Task 9：全量验证 + 运行 lint

- [ ] **Step 1：后端 lint & 类型检查**

```bash
ruff check sebastian/ tests/
ruff format sebastian/ tests/
mypy sebastian/
```

期望：无错误（`mypy` 可能有 `display_name` 属性访问警告，如有请修正）

- [ ] **Step 2：后端全量测试**

```bash
pytest -x
```

期望：所有测试 `PASSED`

- [ ] **Step 3：Android lint**

```bash
cd ui/mobile-android
./gradlew :app:lintDebug
```

期望：无新增 lint 错误

- [ ] **Step 4：Android 全量测试**

```bash
./gradlew :app:testDebugUnitTest
```

期望：所有测试 `PASSED`

- [ ] **Step 5：提交**

```bash
# 如 lint 自动修改了文件
git add -p
git commit -m "chore: ruff format + lint 修复"
```
