# Soul Display Name Android Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Android App 主聊天页面顶部 AgentPill 中，实时显示当前激活的 soul 名称，切换后立即更新，跨会话和重启均保持一致。

**Architecture:** 后端新增 `soul.changed` SSE 事件（`switch_soul` 成功时推送）和 `GET /api/v1/soul/current` REST 端点。Android 端通过 `SettingsDataStore` 本地持久化 soul 名；`GlobalSseDispatcher` 监听 `SoulChanged` 事件并写入 DataStore；`ChatViewModel` 订阅 DataStore 流，通过 `activeSoulName` 字段驱动 `AgentPill`。初次连接时从 REST 端点拉取当初值写入 DataStore，此后依赖 SSE 实时更新。

**Tech Stack:** Python 3.12+ (FastAPI, Pydantic)；Kotlin (ViewModel, DataStore Preferences, Hilt, Retrofit)

---

## 文件变更清单

| 操作 | 文件 |
|------|------|
| 修改 | `sebastian/protocol/events/types.py` |
| 新增 | `sebastian/gateway/routes/soul.py` |
| 修改 | `sebastian/gateway/app.py` |
| 修改 | `sebastian/capabilities/tools/switch_soul/__init__.py` |
| 新增 | `tests/unit/gateway/test_soul_route.py` |
| 修改 | `tests/unit/capabilities/test_switch_soul.py` |
| 修改 | `ui/mobile-android/app/.../data/local/SettingsDataStore.kt` |
| 修改 | `ui/mobile-android/app/.../data/model/StreamEvent.kt` |
| 修改 | `ui/mobile-android/app/.../data/remote/dto/SseFrameDto.kt` |
| 新增 | `ui/mobile-android/app/.../data/remote/dto/SoulDto.kt` |
| 修改 | `ui/mobile-android/app/.../data/remote/ApiService.kt` |
| 修改 | `ui/mobile-android/app/.../data/repository/SettingsRepository.kt` |
| 修改 | `ui/mobile-android/app/.../data/repository/SettingsRepositoryImpl.kt` |
| 修改 | `ui/mobile-android/app/.../data/remote/GlobalSseDispatcher.kt` |
| 修改 | `ui/mobile-android/app/.../viewmodel/ChatUiState.kt` |
| 修改 | `ui/mobile-android/app/.../viewmodel/ChatViewModel.kt` |
| 修改 | `ui/mobile-android/app/.../ui/chat/ChatScreen.kt` |

> 路径前缀统一省略，完整前缀为：
> `ui/mobile-android/app/src/main/java/com/sebastian/android/`

---

### Task 1: 后端 — soul.changed 事件类型 + REST 端点

**Files:**
- Modify: `sebastian/protocol/events/types.py`
- Create: `sebastian/gateway/routes/soul.py`
- Modify: `sebastian/gateway/app.py:408-441`
- Test: `tests/unit/gateway/test_soul_route.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/gateway/test_soul_route.py`：

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sebastian.gateway.routes.soul import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_get_current_soul_returns_active_soul(client: TestClient) -> None:
    mock_loader = MagicMock()
    mock_loader.current_soul = "cortana"

    mock_state = MagicMock()
    mock_state.soul_loader = mock_loader

    with (
        patch("sebastian.gateway.routes.soul._get_state", return_value=mock_state),
        patch("sebastian.gateway.routes.soul.require_auth", return_value={}),
    ):
        resp = client.get("/api/v1/soul/current")

    assert resp.status_code == 200
    assert resp.json() == {"active_soul": "cortana"}
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/gateway/test_soul_route.py -v
```

期望：`ModuleNotFoundError` 或 `ImportError`

- [ ] **Step 3: 添加 EventType.SOUL_CHANGED**

`sebastian/protocol/events/types.py`，在 `TODO_UPDATED` 之后追加：

```python
    # Soul
    SOUL_CHANGED = "soul.changed"
```

- [ ] **Step 4: 创建 soul 路由**

新建 `sebastian/gateway/routes/soul.py`：

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["soul"])

AuthPayload = dict[str, Any]


def _get_state() -> Any:
    import sebastian.gateway.state as state
    return state


@router.get("/soul/current")
async def get_current_soul(
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, str]:
    state = _get_state()
    return {"active_soul": state.soul_loader.current_soul}
```

- [ ] **Step 5: 在 app.py 注册路由**

`sebastian/gateway/app.py`，在路由导入块（约第 408 行）追加 `soul`：

```python
    from sebastian.gateway.routes import (
        ...
        soul,
        ...
    )
```

在 `include_router` 调用区（约第 441 行）追加：

```python
    app.include_router(soul.router, prefix="/api/v1")
```

- [ ] **Step 6: 运行测试确认通过**

```bash
pytest tests/unit/gateway/test_soul_route.py -v
```

期望：PASS

- [ ] **Step 7: Commit**

```bash
git add sebastian/protocol/events/types.py sebastian/gateway/routes/soul.py sebastian/gateway/app.py tests/unit/gateway/test_soul_route.py
git commit -m "feat(soul): 新增 SOUL_CHANGED 事件类型和 GET /api/v1/soul/current 端点"
```

---

### Task 2: 后端 — switch_soul 工具推送 soul.changed 事件

**Files:**
- Modify: `sebastian/capabilities/tools/switch_soul/__init__.py`
- Modify: `tests/unit/capabilities/test_switch_soul.py`

- [ ] **Step 1: 更新 switch_soul 测试，断言事件被发布**

`tests/unit/capabilities/test_switch_soul.py`，在 `_make_state` 函数里添加 `event_bus` mock：

```python
def _make_state(souls_dir: Path, current_soul: str = "sebastian") -> MagicMock:
    from sebastian.core.soul_loader import SoulLoader

    loader = SoulLoader(
        souls_dir=souls_dir,
        builtin_souls={"sebastian": "You are Sebastian.", "cortana": "You are Cortana."},
    )
    loader.ensure_defaults()
    loader.current_soul = current_soul

    sebastian = MagicMock()
    sebastian.persona = "You are Sebastian."
    sebastian.system_prompt = "old_prompt"
    sebastian._gate = MagicMock()
    sebastian._agent_registry = {}
    sebastian.build_system_prompt = MagicMock(return_value="new_prompt")

    db_session = AsyncMock()
    db_cm = AsyncMock()
    db_cm.__aenter__ = AsyncMock(return_value=db_session)
    db_cm.__aexit__ = AsyncMock(return_value=None)
    db_factory = MagicMock(return_value=db_cm)

    event_bus = AsyncMock()

    state = MagicMock()
    state.soul_loader = loader
    state.sebastian = sebastian
    state.db_factory = db_factory
    state.event_bus = event_bus
    return state
```

更新 `test_switch_soul_success`，在末尾追加断言：

```python
@pytest.mark.asyncio
async def test_switch_soul_success(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="sebastian")
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("cortana")

    assert result.ok is True
    assert "cortana" in result.output
    assert state.sebastian.persona == "You are Cortana."
    assert state.sebastian.system_prompt == "new_prompt"
    assert state.soul_loader.current_soul == "cortana"
    db_session = state.db_factory.return_value.__aenter__.return_value
    db_session.commit.assert_awaited_once()
    # soul.changed 事件必须被发布
    state.event_bus.publish.assert_awaited_once()
    published_event = state.event_bus.publish.call_args[0][0]
    assert published_event.data["soul_name"] == "cortana"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/capabilities/test_switch_soul.py::test_switch_soul_success -v
```

期望：FAIL（`event_bus.publish not called`）

- [ ] **Step 3: 在 switch_soul 成功分支中发布事件**

`sebastian/capabilities/tools/switch_soul/__init__.py`，在 `soul_loader.current_soul = soul_name` 之后插入：

```python
        soul_loader.current_soul = soul_name
        state.sebastian.persona = content
        state.sebastian.system_prompt = state.sebastian.build_system_prompt(
            state.sebastian._gate, state.sebastian._agent_registry
        )
        from sebastian.protocol.events.types import Event, EventType

        await state.event_bus.publish(
            Event(
                type=EventType.SOUL_CHANGED,
                data={"soul_name": soul_name},
            )
        )
        msg = f"已切换到 {soul_name}"
        return ToolResult(ok=True, output=msg, display=msg)
```

- [ ] **Step 4: 运行全量 soul 测试确认通过**

```bash
pytest tests/unit/capabilities/test_switch_soul.py tests/unit/gateway/test_soul_route.py tests/unit/core/test_soul_loader.py tests/integration/test_gateway_soul.py -v
```

期望：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/switch_soul/__init__.py tests/unit/capabilities/test_switch_soul.py
git commit -m "feat(soul): switch_soul 成功后发布 soul.changed SSE 事件"
```

---

### Task 3: Android 数据层 — DataStore 持久化 + SSE 解析 + Repository

**Files:**
- Modify: `data/local/SettingsDataStore.kt`
- Modify: `data/model/StreamEvent.kt`
- Modify: `data/remote/dto/SseFrameDto.kt`
- Create: `data/remote/dto/SoulDto.kt`
- Modify: `data/remote/ApiService.kt`
- Modify: `data/repository/SettingsRepository.kt`
- Modify: `data/repository/SettingsRepositoryImpl.kt`
- Modify: `data/remote/GlobalSseDispatcher.kt`

- [ ] **Step 1: SettingsDataStore 添加 ACTIVE_SOUL**

`data/local/SettingsDataStore.kt`，在 `companion object` 中追加 key，在类体中添加 flow 和 save 方法：

```kotlin
companion object {
    val SERVER_URL = stringPreferencesKey("server_url")
    val THEME = stringPreferencesKey("theme")
    val ACTIVE_SOUL = stringPreferencesKey("active_soul")   // ← 新增
}

val activeSoul: StateFlow<String> = context.dataStore.data
    .map { prefs -> prefs[ACTIVE_SOUL] ?: "" }
    .stateIn(scope, SharingStarted.Eagerly, "")

suspend fun saveActiveSoul(name: String) {
    context.dataStore.edit { it[ACTIVE_SOUL] = name }
}
```

- [ ] **Step 2: StreamEvent 添加 SoulChanged**

`data/model/StreamEvent.kt`，在 `object Unknown` 之前追加：

```kotlin
    // Soul
    data class SoulChanged(val soulName: String) : StreamEvent()
```

- [ ] **Step 3: SSE 解析器处理 soul.changed**

`data/remote/dto/SseFrameDto.kt`，在 `"todo.updated"` 分支之后追加：

```kotlin
        "soul.changed" -> StreamEvent.SoulChanged(
            soulName = data.optString("soul_name", "sebastian"),
        )
```

- [ ] **Step 4: 创建 SoulDto**

新建 `data/remote/dto/SoulDto.kt`：

```kotlin
package com.sebastian.android.data.remote.dto

import com.google.gson.annotations.SerializedName

data class SoulCurrentDto(
    @SerializedName("active_soul") val activeSoul: String,
)
```

- [ ] **Step 5: ApiService 添加 getCurrentSoul**

`data/remote/ApiService.kt`，在 `@GET("api/v1/health")` 之前追加：

```kotlin
    // Soul
    @GET("api/v1/soul/current")
    suspend fun getCurrentSoul(): SoulCurrentDto
```

- [ ] **Step 6: SettingsRepository 接口扩展**

`data/repository/SettingsRepository.kt`，追加三行：

```kotlin
    val activeSoul: Flow<String>
    suspend fun saveActiveSoul(name: String)
    suspend fun fetchActiveSoul(): Result<String>
```

- [ ] **Step 7: SettingsRepositoryImpl 实现**

`data/repository/SettingsRepositoryImpl.kt`，追加：

```kotlin
    override val activeSoul: Flow<String> = dataStore.activeSoul

    override suspend fun saveActiveSoul(name: String) = dataStore.saveActiveSoul(name)

    override suspend fun fetchActiveSoul(): Result<String> = runCatching {
        apiService.getCurrentSoul().activeSoul
    }
```

- [ ] **Step 8: GlobalSseDispatcher 处理 SoulChanged**

`data/remote/GlobalSseDispatcher.kt`，`settingsRepository` 已注入。在已有的 `_events.emit(event)` 之后插入 3 行（不要重写整个 collect 块）：

```kotlin
                        _events.emit(event)
                        // ← 新增：SSE 通知后同步写 DataStore，fire-and-forget 不阻塞 SSE 流
                        if (event is StreamEvent.SoulChanged) {
                            scope.launch(dispatcher) {
                                settingsRepository.saveActiveSoul(event.soulName)
                            }
                        }
```

- [ ] **Step 9: Commit**

```bash
git add \
  ui/mobile-android/app/src/main/java/com/sebastian/android/data/local/SettingsDataStore.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SoulDto.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/GlobalSseDispatcher.kt
git commit -m "feat(soul): Android 数据层 — DataStore 持久化 soul 名、SSE 解析、Repository、GlobalSseDispatcher 同步"
```

---

### Task 4: Android UI 层 — ChatUiState + ChatViewModel + ChatScreen

**Files:**
- Modify: `viewmodel/ChatUiState.kt`
- Modify: `viewmodel/ChatViewModel.kt`
- Modify: `ui/chat/ChatScreen.kt`

- [ ] **Step 1: ChatUiState 添加 activeSoulName**

`viewmodel/ChatUiState.kt`，在 `data class ChatUiState` 内追加字段（末尾）：

```kotlin
data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val composerState: ComposerState = ComposerState.IDLE_EMPTY,
    val agentAnimState: AgentAnimState = AgentAnimState.IDLE,
    val activeSessionId: String? = null,
    val isOffline: Boolean = false,
    val error: String? = null,
    val isServerNotConfigured: Boolean = false,
    val connectionFailed: Boolean = false,
    val flushTick: Long = 0L,
    val todos: List<TodoItem> = emptyList(),
    val pendingAttachments: List<PendingAttachment> = emptyList(),
    val inputCapabilities: ModelInputCapabilities = ModelInputCapabilities(),
    val isSessionSwitching: Boolean = false,
    val activeSoulName: String = "Sebastian",   // ← 新增
)
```

- [ ] **Step 2: ChatViewModel 订阅 soul 流并在 init 拉取初始值**

`viewmodel/ChatViewModel.kt`，构造函数参数已包含 `settingsRepository: SettingsRepository`。

在 `init` 块中追加 soul 初始化逻辑：

```kotlin
    init {
        observeNetwork()
        startDeltaFlusher()
        observeActiveSoul()
        fetchInitialSoulIfNeeded()
    }
```

在类体中追加两个私有函数：

```kotlin
    private fun observeActiveSoul() {
        viewModelScope.launch(dispatcher) {
            settingsRepository.activeSoul.collect { name ->
                if (name.isNotBlank()) {
                    _uiState.update { it.copy(activeSoulName = name.replaceFirstChar { c -> c.uppercase() }) }
                }
            }
        }
    }

    private fun fetchInitialSoulIfNeeded() {
        viewModelScope.launch(dispatcher) {
            val cached = settingsRepository.activeSoul.first()  // Flow<String> 用 first()，不是 .value
            if (cached.isNotBlank()) return@launch
            settingsRepository.fetchActiveSoul()
                .onSuccess { name ->
                    settingsRepository.saveActiveSoul(name)
                }
        }
    }
```

- [ ] **Step 3: ChatScreen 将 soul 名传给 AgentPill**

`ui/chat/ChatScreen.kt`，第 335 行 `AgentPill` 调用改为：

```kotlin
                        AgentPill(
                            agentName = agentName ?: chatState.activeSoulName,
                            agentAnimState = chatState.agentAnimState,
                            glassState = glassState,
                        )
```

同时，`AgentPill.kt` 第 76 行的硬编码 fallback 可保留作为最终兜底（`activeSoulName` 默认值已是 `"Sebastian"`，正常不会触发）：

```kotlin
val displayName = agentName ?: "Sebastian"   // 保持不变，正常路径不走此 fallback
```

- [ ] **Step 4: 构建并手动验证**

```bash
cd ui/mobile-android
./gradlew assembleDebug   # 纯原生 Kotlin 项目，无 Expo
# 或直接用 Android Studio 构建并运行
```

验证步骤：
1. 启动 App → 聊天页面顶部显示 "Sebastian"
2. 对话中让 Sebastian 调用 `switch_soul("cortana")`
3. 当前会话顶部立即变为 "Cortana"
4. 退出聊天，重新进入 → 顶部依然显示 "Cortana"
5. 杀进程重启 App → 顶部依然显示 "Cortana"

- [ ] **Step 5: Commit**

```bash
git add \
  ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatUiState.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "feat(soul): Android UI — ChatUiState/ViewModel 订阅 soul 名，AgentPill 实时显示"
```

---

## 自检

**Spec 覆盖：**

| 需求 | 覆盖任务 |
|------|---------|
| 切换后 SSE 实时推送 soul 名 | Task 2 |
| 新开会话读缓存显示正确 soul 名 | Task 3 (DataStore) + Task 4 (observe) |
| 重启后恢复 soul 名 | Task 3 (DataStore 持久化) |
| 切换后同步更新缓存 | Task 3 (GlobalSseDispatcher → saveActiveSoul) |
| 首次启动无缓存时从 REST 拉取 | Task 4 (fetchInitialSoulIfNeeded) |
| 子代理聊天页面不受影响 | Task 4 Step 3（`agentName ?: chatState.activeSoulName`，子代理有 agentName 不走 soul） |

**类型一致性：** `SettingsDataStore.activeSoul` 定义为 `StateFlow<String>`；`SettingsRepository` 接口和 impl 收窄声明为 `Flow<String>`（`StateFlow` 是 `Flow` 子类型，Kotlin 协变合法）；`ChatViewModel` 通过 `collect` / `first()` 消费，类型全程 `String`。`SoulChanged(val soulName: String)` 在 Task 3 定义，Task 3 Step 8 使用 `event.soulName`，一致。

**无 placeholder：** 所有 step 均包含完整代码。
