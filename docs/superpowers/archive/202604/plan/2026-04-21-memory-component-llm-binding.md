# Memory Component LLM Provider Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `memory_extractor` 和 `memory_consolidator` 添加独立的 `/memory/components` REST API，并在 Android `AgentBindingsPage` 新增 "Memory Components" section。

**Architecture:** 新建 `sebastian/gateway/routes/memory_components.py` 处理 4 个 CRUD 端点，与 `agents.py` 完全独立；Android 新增 DTO/model，扩展 `AgentRepository`，`AgentBindingEditorViewModel` 加 `isMemoryComponent` 标志切换调用端点，`AgentBindingsPage` 插入第二个 section（Orchestrator → Memory Components → Sub-Agents）。

**Tech Stack:** Python 3.12 / FastAPI（后端）；Kotlin / Jetpack Compose / Hilt / Moshi / Retrofit（Android）

---

## 文件清单

| 文件 | 操作 |
|------|------|
| `sebastian/memory/provider_bindings.py` | 修改 |
| `sebastian/gateway/routes/memory_components.py` | 新建 |
| `sebastian/gateway/app.py` | 修改 |
| `tests/unit/test_memory_components_route.py` | 新建 |
| `ui/mobile-android/.../dto/MemoryComponentDto.kt` | 新建 |
| `ui/mobile-android/.../model/MemoryComponentInfo.kt` | 新建 |
| `ui/mobile-android/.../remote/ApiService.kt` | 修改 |
| `ui/mobile-android/.../repository/AgentRepository.kt` | 修改 |
| `ui/mobile-android/.../repository/AgentRepositoryImpl.kt` | 修改 |
| `ui/mobile-android/.../viewmodel/AgentBindingsViewModel.kt` | 修改 |
| `ui/mobile-android/.../viewmodel/AgentBindingEditorViewModel.kt` | 修改 |
| `ui/mobile-android/.../navigation/Route.kt` | 修改 |
| `ui/mobile-android/.../settings/AgentBindingsPage.kt` | 修改 |
| `ui/mobile-android/.../settings/AgentBindingEditorPage.kt` | 修改 |
| `ui/mobile-android/.../MainActivity.kt` | 修改 |

路径前缀：`ui/mobile-android/app/src/main/java/com/sebastian/android`

---

### Task 1: 扩展 `provider_bindings.py`

**Files:**
- Modify: `sebastian/memory/provider_bindings.py`

- [ ] **Step 1: 替换文件内容**

```python
# sebastian/memory/provider_bindings.py
from __future__ import annotations

MEMORY_EXTRACTOR_BINDING = "memory_extractor"
MEMORY_CONSOLIDATOR_BINDING = "memory_consolidator"

MEMORY_COMPONENT_TYPES: frozenset[str] = frozenset({
    MEMORY_EXTRACTOR_BINDING,
    MEMORY_CONSOLIDATOR_BINDING,
})

MEMORY_COMPONENT_META: dict[str, dict[str, str]] = {
    MEMORY_EXTRACTOR_BINDING: {
        "display_name": "记忆提取器",
        "description": "从会话片段中提取候选 memory artifact",
    },
    MEMORY_CONSOLIDATOR_BINDING: {
        "display_name": "记忆沉淀器",
        "description": "会话结束后归纳 session summary 和推断偏好",
    },
}
```

- [ ] **Step 2: 验证导入**

```bash
python -c "from sebastian.memory.provider_bindings import MEMORY_COMPONENT_TYPES, MEMORY_COMPONENT_META; print(MEMORY_COMPONENT_TYPES)"
```
Expected: `frozenset({'memory_extractor', 'memory_consolidator'})`

- [ ] **Step 3: Commit**

```bash
git add sebastian/memory/provider_bindings.py
git commit -m "feat(memory): 新增 MEMORY_COMPONENT_TYPES 和 MEMORY_COMPONENT_META 常量"
```

---

### Task 2: 新建 `memory_components.py` 路由（TDD）

**Files:**
- Create: `tests/unit/test_memory_components_route.py`
- Create: `sebastian/gateway/routes/memory_components.py`

- [ ] **Step 1: 先写测试**

```python
# tests/unit/test_memory_components_route.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sebastian.memory.provider_bindings import (
    MEMORY_CONSOLIDATOR_BINDING,
    MEMORY_EXTRACTOR_BINDING,
)


def _make_binding(agent_type: str, provider_id: str | None = None) -> MagicMock:
    b = MagicMock()
    b.agent_type = agent_type
    b.provider_id = provider_id
    b.thinking_effort = None
    return b


def _make_provider_record(pid: str = "pid-1", capability: str = "none") -> MagicMock:
    r = MagicMock()
    r.id = pid
    r.thinking_capability = capability
    return r


@pytest.fixture
def mock_registry() -> MagicMock:
    r = MagicMock()
    r.list_bindings = AsyncMock(return_value=[])
    r.get_binding = AsyncMock(return_value=None)
    r.get_record = AsyncMock(return_value=None)
    r.set_binding = AsyncMock(return_value=_make_binding(MEMORY_EXTRACTOR_BINDING))
    r.clear_binding = AsyncMock()
    return r


@pytest.fixture
def client(mock_registry: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", mock_registry)

    from sebastian.gateway.auth import require_auth
    from sebastian.gateway.routes.memory_components import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    return TestClient(app)


# ── GET /memory/components ──────────────────────────────────────────────────

def test_list_returns_both_components_with_null_binding(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.list_bindings = AsyncMock(return_value=[])
    resp = client.get("/api/v1/memory/components")
    assert resp.status_code == 200
    data = resp.json()
    types = [c["component_type"] for c in data["components"]]
    assert MEMORY_EXTRACTOR_BINDING in types
    assert MEMORY_CONSOLIDATOR_BINDING in types
    for c in data["components"]:
        assert c["binding"] is None
        assert "display_name" in c
        assert "description" in c


def test_list_shows_existing_binding(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.list_bindings = AsyncMock(
        return_value=[_make_binding(MEMORY_EXTRACTOR_BINDING, provider_id="pid-abc")]
    )
    resp = client.get("/api/v1/memory/components")
    assert resp.status_code == 200
    by_type = {c["component_type"]: c for c in resp.json()["components"]}
    assert by_type[MEMORY_EXTRACTOR_BINDING]["binding"]["provider_id"] == "pid-abc"
    assert by_type[MEMORY_CONSOLIDATOR_BINDING]["binding"] is None


# ── GET /memory/components/{type}/llm-binding ───────────────────────────────

def test_get_binding_no_row_returns_null_provider(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.get_binding = AsyncMock(return_value=None)
    resp = client.get(f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding")
    assert resp.status_code == 200
    body = resp.json()
    assert body["component_type"] == MEMORY_EXTRACTOR_BINDING
    assert body["provider_id"] is None


def test_get_binding_unknown_type_returns_404(client: TestClient) -> None:
    resp = client.get("/api/v1/memory/components/unknown_thing/llm-binding")
    assert resp.status_code == 404


# ── PUT /memory/components/{type}/llm-binding ───────────────────────────────

def test_put_resets_effort_when_provider_changes(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.get_record = AsyncMock(return_value=_make_provider_record("pid-1", "adaptive"))
    mock_registry.get_binding = AsyncMock(return_value=None)  # no existing binding
    mock_registry.set_binding = AsyncMock(
        return_value=_make_binding(MEMORY_EXTRACTOR_BINDING, "pid-1")
    )
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"provider_id": "pid-1", "thinking_effort": "high"},
    )
    assert resp.status_code == 200
    kwargs = mock_registry.set_binding.call_args.kwargs
    assert kwargs["thinking_effort"] is None  # reset because provider changed


def test_put_preserves_effort_when_provider_unchanged(
    client: TestClient, mock_registry: MagicMock
) -> None:
    existing = _make_binding(MEMORY_EXTRACTOR_BINDING, "pid-1")
    mock_registry.get_record = AsyncMock(return_value=_make_provider_record("pid-1", "adaptive"))
    mock_registry.get_binding = AsyncMock(return_value=existing)
    mock_registry.set_binding = AsyncMock(return_value=existing)
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"provider_id": "pid-1", "thinking_effort": "high"},
    )
    assert resp.status_code == 200
    assert mock_registry.set_binding.call_args.kwargs["thinking_effort"] == "high"


def test_put_clears_effort_for_none_capability(
    client: TestClient, mock_registry: MagicMock
) -> None:
    existing = _make_binding(MEMORY_EXTRACTOR_BINDING, "pid-1")
    mock_registry.get_record = AsyncMock(return_value=_make_provider_record("pid-1", "none"))
    mock_registry.get_binding = AsyncMock(return_value=existing)
    mock_registry.set_binding = AsyncMock(return_value=existing)
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"provider_id": "pid-1", "thinking_effort": "high"},
    )
    assert resp.status_code == 200
    assert mock_registry.set_binding.call_args.kwargs["thinking_effort"] is None


def test_put_unknown_provider_returns_400(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.get_record = AsyncMock(return_value=None)
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"provider_id": "nonexistent"},
    )
    assert resp.status_code == 400


def test_put_unknown_component_returns_404(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/memory/components/bad_type/llm-binding",
        json={"provider_id": None},
    )
    assert resp.status_code == 404


# ── DELETE /memory/components/{type}/llm-binding ────────────────────────────

def test_delete_returns_204_and_calls_clear(
    client: TestClient, mock_registry: MagicMock
) -> None:
    resp = client.delete(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding"
    )
    assert resp.status_code == 204
    mock_registry.clear_binding.assert_awaited_once_with(MEMORY_EXTRACTOR_BINDING)


def test_delete_unknown_component_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/v1/memory/components/bad_type/llm-binding")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认全部 FAIL**

```bash
pytest tests/unit/test_memory_components_route.py -v
```
Expected: ImportError（路由文件不存在）。

- [ ] **Step 3: 创建路由文件**

```python
# sebastian/gateway/routes/memory_components.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth
from sebastian.memory.provider_bindings import MEMORY_COMPONENT_META, MEMORY_COMPONENT_TYPES

router = APIRouter(tags=["memory"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


class ComponentBindingUpdate(BaseModel):
    provider_id: str | None = None
    thinking_effort: str | None = None


def _binding_to_dict(component_type: str, binding: Any | None) -> JSONDict:
    return {
        "component_type": component_type,
        "provider_id": binding.provider_id if binding is not None else None,
        "thinking_effort": binding.thinking_effort if binding is not None else None,
    }


@router.get("/memory/components")
async def list_memory_components(
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    bindings = await state.llm_registry.list_bindings()
    binding_map = {b.agent_type: b for b in bindings}

    components: list[JSONDict] = []
    for component_type, meta in MEMORY_COMPONENT_META.items():
        binding = binding_map.get(component_type)
        components.append(
            {
                "component_type": component_type,
                "display_name": meta["display_name"],
                "description": meta["description"],
                "binding": _binding_to_dict(component_type, binding)
                if binding is not None
                else None,
            }
        )
    return {"components": components}


@router.get("/memory/components/{component_type}/llm-binding")
async def get_component_binding(
    component_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if component_type not in MEMORY_COMPONENT_TYPES:
        raise HTTPException(status_code=404, detail="Memory component not found")

    binding = await state.llm_registry.get_binding(component_type)
    return _binding_to_dict(component_type, binding)


@router.put("/memory/components/{component_type}/llm-binding")
async def set_component_binding(
    component_type: str,
    body: ComponentBindingUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if component_type not in MEMORY_COMPONENT_TYPES:
        raise HTTPException(status_code=404, detail="Memory component not found")

    record = None
    if body.provider_id is not None:
        record = await state.llm_registry.get_record(body.provider_id)
        if record is None:
            raise HTTPException(status_code=400, detail="Provider not found")

    existing = await state.llm_registry.get_binding(component_type)
    provider_changed = existing is None or existing.provider_id != body.provider_id

    effort: str | None = None if provider_changed else body.thinking_effort
    if record is not None and record.thinking_capability in ("none", "always_on"):
        effort = None

    binding = await state.llm_registry.set_binding(
        component_type,
        body.provider_id,
        thinking_effort=effort,
    )
    return _binding_to_dict(component_type, binding)


@router.delete("/memory/components/{component_type}/llm-binding", status_code=204)
async def clear_component_binding(
    component_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    if component_type not in MEMORY_COMPONENT_TYPES:
        raise HTTPException(status_code=404, detail="Memory component not found")

    await state.llm_registry.clear_binding(component_type)
    return Response(status_code=204)
```

- [ ] **Step 4: 运行测试确认全部 PASS**

```bash
pytest tests/unit/test_memory_components_route.py -v
```
Expected: 11 tests PASS。

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/routes/memory_components.py tests/unit/test_memory_components_route.py
git commit -m "feat(gateway): /memory/components LLM binding 路由 + 单元测试"
```

---

### Task 3: 注册 router 到 `app.py`

**Files:**
- Modify: `sebastian/gateway/app.py`

- [ ] **Step 1: 在 `create_app()` 中添加 import 和注册**

在 `create_app()` 函数的 import 块，`memory_settings` 之后加 `memory_components`：

```python
from sebastian.gateway.routes import (
    agents,
    approvals,
    debug,
    llm_providers,
    memory_components,   # ← 新增
    memory_settings,
    sessions,
    stream,
    turns,
)
```

在 `app.include_router(memory_settings.router, prefix="/api/v1")` 之后加：

```python
app.include_router(memory_components.router, prefix="/api/v1")
```

- [ ] **Step 2: 确认路由已注册**

```bash
python -c "
from sebastian.gateway.app import create_app
app = create_app()
paths = [r.path for r in app.routes]
mc = [p for p in paths if 'memory/components' in p]
print(mc)
"
```
Expected: 包含 `/api/v1/memory/components` 和 `/api/v1/memory/components/{component_type}/llm-binding` 的列表。

- [ ] **Step 3: Commit**

```bash
git add sebastian/gateway/app.py
git commit -m "feat(gateway): 注册 memory_components router"
```

---

### Task 4: Android — 新建 DTO 和 Domain Model

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MemoryComponentDto.kt`
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/MemoryComponentInfo.kt`

- [ ] **Step 1: 创建 `MemoryComponentDto.kt`**

```kotlin
// data/remote/dto/MemoryComponentDto.kt
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.MemoryComponentInfo
import com.sebastian.android.data.model.toThinkingEffort
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class MemoryComponentBindingDto(
    @param:Json(name = "component_type") val componentType: String,
    @param:Json(name = "provider_id") val providerId: String?,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
)

@JsonClass(generateAdapter = true)
data class MemoryComponentDto(
    @param:Json(name = "component_type") val componentType: String,
    @param:Json(name = "display_name") val displayName: String,
    val description: String,
    val binding: MemoryComponentBindingDto?,
) {
    fun toDomain() = MemoryComponentInfo(
        componentType = componentType,
        displayName = displayName,
        description = description,
        boundProviderId = binding?.providerId,
        thinkingEffort = binding?.thinkingEffort.toThinkingEffort(),
    )
}

@JsonClass(generateAdapter = true)
data class MemoryComponentsResponse(
    val components: List<MemoryComponentDto>,
)
```

- [ ] **Step 2: 创建 `MemoryComponentInfo.kt`**

```kotlin
// data/model/MemoryComponentInfo.kt
package com.sebastian.android.data.model

data class MemoryComponentInfo(
    val componentType: String,
    val displayName: String,
    val description: String,
    val boundProviderId: String? = null,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
)
```

- [ ] **Step 3: 触发 Moshi 适配器生成确认编译通过**

```bash
cd ui/mobile-android && ./gradlew :app:kspDebugKotlin --quiet
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MemoryComponentDto.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/MemoryComponentInfo.kt
git commit -m "feat(android): MemoryComponentDto + MemoryComponentInfo"
```

---

### Task 5: Android — `ApiService` + `AgentRepository` + `AgentRepositoryImpl`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt`

- [ ] **Step 1: 在 `ApiService` 的 Memory Settings 块之后添加 4 个方法**

```kotlin
// Memory Components
@GET("api/v1/memory/components")
suspend fun listMemoryComponents(): MemoryComponentsResponse

@GET("api/v1/memory/components/{componentType}/llm-binding")
suspend fun getMemoryComponentBinding(
    @Path("componentType") componentType: String,
): MemoryComponentBindingDto

@PUT("api/v1/memory/components/{componentType}/llm-binding")
suspend fun setMemoryComponentBinding(
    @Path("componentType") componentType: String,
    @Body body: SetBindingRequest,
): MemoryComponentBindingDto

@DELETE("api/v1/memory/components/{componentType}/llm-binding")
suspend fun clearMemoryComponentBinding(@Path("componentType") componentType: String)
```

- [ ] **Step 2: 在 `AgentRepository` 接口末尾添加 4 个方法**

```kotlin
suspend fun listMemoryComponents(): Result<List<MemoryComponentInfo>>
suspend fun getMemoryComponentBinding(componentType: String): Result<AgentBindingDto>
suspend fun setMemoryComponentBinding(
    componentType: String,
    providerId: String?,
    thinkingEffort: ThinkingEffort,
): Result<Unit>
suspend fun clearMemoryComponentBinding(componentType: String): Result<Unit>
```

- [ ] **Step 3: 在 `AgentRepositoryImpl` 末尾实现 4 个方法**

```kotlin
override suspend fun listMemoryComponents(): Result<List<MemoryComponentInfo>> = runCatching {
    withContext(dispatcher) {
        apiService.listMemoryComponents().components.map { it.toDomain() }
    }
}

override suspend fun getMemoryComponentBinding(
    componentType: String,
): Result<AgentBindingDto> = runCatching {
    withContext(dispatcher) {
        val dto = apiService.getMemoryComponentBinding(componentType)
        // ViewModel 只使用 providerId/thinkingEffort，agentType 字段用 componentType 填充
        AgentBindingDto(
            agentType = dto.componentType,
            providerId = dto.providerId,
            thinkingEffort = dto.thinkingEffort,
        )
    }
}

override suspend fun setMemoryComponentBinding(
    componentType: String,
    providerId: String?,
    thinkingEffort: ThinkingEffort,
): Result<Unit> = runCatching {
    withContext(dispatcher) {
        apiService.setMemoryComponentBinding(
            componentType,
            SetBindingRequest(
                providerId = providerId,
                thinkingEffort = thinkingEffort.toApiString(),
            ),
        )
        Unit
    }
}

override suspend fun clearMemoryComponentBinding(
    componentType: String,
): Result<Unit> = runCatching {
    withContext(dispatcher) {
        apiService.clearMemoryComponentBinding(componentType)
    }
}
```

- [ ] **Step 4: 验证编译**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin --quiet
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt
git commit -m "feat(android): memory component binding API + repository"
```

---

### Task 6: Android — `AgentBindingsViewModel` 扩展

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt`

- [ ] **Step 1: 替换整个文件**

```kotlin
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.MemoryComponentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AgentBindingsUiState(
    val loading: Boolean = false,
    val agents: List<AgentInfo> = emptyList(),
    val memoryComponents: List<MemoryComponentInfo> = emptyList(),
    val providers: List<Provider> = emptyList(),
    val errorMessage: String? = null,
)

@HiltViewModel
class AgentBindingsViewModel @Inject constructor(
    private val agentRepository: AgentRepository,
    private val settingsRepository: SettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(AgentBindingsUiState())
    val uiState: StateFlow<AgentBindingsUiState> = _uiState

    fun load() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, errorMessage = null) }
            val agentsD = async { agentRepository.getAgents() }
            val componentsD = async { agentRepository.listMemoryComponents() }
            val providersD = async { settingsRepository.getProviders() }
            val agentsR = agentsD.await()
            val componentsR = componentsD.await()
            val providersR = providersD.await()
            val err = agentsR.exceptionOrNull()
                ?: componentsR.exceptionOrNull()
                ?: providersR.exceptionOrNull()
            _uiState.update {
                it.copy(
                    loading = false,
                    agents = agentsR.getOrDefault(emptyList()),
                    memoryComponents = componentsR.getOrDefault(emptyList()),
                    providers = providersR.getOrDefault(emptyList()),
                    errorMessage = err?.message,
                )
            }
        }
    }
}
```

- [ ] **Step 2: 验证编译**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin --quiet
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt
git commit -m "feat(android): AgentBindingsViewModel 并发加载 memory components"
```

---

### Task 7: Android — `Route.kt` + `AgentBindingEditorViewModel`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt`

- [ ] **Step 1: 在 `Route.kt` 中为 `SettingsAgentBindingEditor` 加 `isMemoryComponent`**

将：
```kotlin
@Serializable
data class SettingsAgentBindingEditor(val agentType: String) : Route()
```
替换为：
```kotlin
@Serializable
data class SettingsAgentBindingEditor(
    val agentType: String,
    val isMemoryComponent: Boolean = false,
) : Route()
```

- [ ] **Step 2: 替换 `AgentBindingEditorViewModel.kt` 整个文件**

```kotlin
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.toThinkingEffort
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.ApplicationScope
import com.sebastian.android.ui.settings.components.effortStepsFor
import dagger.assisted.Assisted
import dagger.assisted.AssistedFactory
import dagger.assisted.AssistedInject
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class EditorUiState(
    val agentType: String,
    val agentDisplayName: String = "",
    val isOrchestrator: Boolean = false,
    val providers: List<Provider> = emptyList(),
    val selectedProvider: Provider? = null,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
    val isSaving: Boolean = false,
    val errorMessage: String? = null,
    val loading: Boolean = true,
) {
    val effectiveCapability: ThinkingCapability?
        get() = (selectedProvider ?: providers.firstOrNull { it.isDefault })?.thinkingCapability
}

sealed interface EditorEvent {
    data class Snackbar(val text: String) : EditorEvent
}

@HiltViewModel(assistedFactory = AgentBindingEditorViewModel.Factory::class)
class AgentBindingEditorViewModel @AssistedInject constructor(
    @Assisted("agentType") private val agentType: String,
    @Assisted("isMemoryComponent") private val isMemoryComponent: Boolean,
    private val agentRepository: AgentRepository,
    private val settingsRepository: SettingsRepository,
    @ApplicationScope private val applicationScope: CoroutineScope,
) : ViewModel() {

    @AssistedFactory
    interface Factory {
        fun create(
            @Assisted("agentType") agentType: String,
            @Assisted("isMemoryComponent") isMemoryComponent: Boolean,
        ): AgentBindingEditorViewModel
    }

    private val _uiState = MutableStateFlow(EditorUiState(agentType = agentType))
    val uiState: StateFlow<EditorUiState> = _uiState

    private val _events = MutableSharedFlow<EditorEvent>(extraBufferCapacity = 1)
    val events: SharedFlow<EditorEvent> = _events.asSharedFlow()

    private var putJob: Job? = null
    private var loadJob: Job? = null
    private var snapshot: EditorUiState? = null
    private var putPending: Boolean = false

    fun load() {
        if (loadJob?.isActive == true) return
        loadJob = viewModelScope.launch {
            val bindingR = if (isMemoryComponent) {
                agentRepository.getMemoryComponentBinding(agentType)
            } else {
                agentRepository.getBinding(agentType)
            }
            val providersR = settingsRepository.getProviders()
            val err = bindingR.exceptionOrNull() ?: providersR.exceptionOrNull()
            if (err != null) {
                _uiState.update { it.copy(loading = false, errorMessage = err.message) }
                return@launch
            }
            val dto = bindingR.getOrThrow()
            val providers = providersR.getOrThrow()
            val selected = providers.firstOrNull { it.id == dto.providerId }
            val capability = (selected ?: providers.firstOrNull { it.isDefault })?.thinkingCapability
            val (coercedEffort, wasCoerced) =
                coerceEffort(dto.thinkingEffort.toThinkingEffort(), capability)
            _uiState.update {
                it.copy(
                    loading = false,
                    providers = providers,
                    selectedProvider = selected,
                    thinkingEffort = coercedEffort,
                )
            }
            if (wasCoerced) schedulePut()
        }
    }

    fun selectProvider(providerId: String?) {
        val prev = _uiState.value
        val next = prev.providers.firstOrNull { it.id == providerId }
        val providerChanged = prev.selectedProvider?.id != providerId
        val hadConfig = prev.thinkingEffort != ThinkingEffort.OFF
        _uiState.update {
            it.copy(
                selectedProvider = next,
                thinkingEffort = if (providerChanged) ThinkingEffort.OFF else it.thinkingEffort,
            )
        }
        if (providerChanged && hadConfig) {
            _events.tryEmit(EditorEvent.Snackbar("Thinking config reset for new provider"))
        }
        schedulePut()
    }

    fun setEffort(e: ThinkingEffort) {
        _uiState.update { it.copy(thinkingEffort = e) }
        schedulePut()
    }

    private fun schedulePut() {
        putJob?.cancel()
        snapshot = _uiState.value
        putPending = true
        putJob = viewModelScope.launch {
            delay(300)
            val s = _uiState.value
            _uiState.update { it.copy(isSaving = true) }
            val r = if (isMemoryComponent) {
                agentRepository.setMemoryComponentBinding(
                    agentType, s.selectedProvider?.id, s.thinkingEffort,
                )
            } else {
                agentRepository.setBinding(
                    agentType, s.selectedProvider?.id, s.thinkingEffort,
                )
            }
            putPending = false
            _uiState.update { it.copy(isSaving = false) }
            r.onFailure {
                val snap = snapshot
                if (snap != null) _uiState.value = snap.copy(errorMessage = null, isSaving = false)
                _events.tryEmit(EditorEvent.Snackbar("Failed to save. Retry?"))
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        if (putPending) {
            val s = _uiState.value
            applicationScope.launch {
                if (isMemoryComponent) {
                    agentRepository.setMemoryComponentBinding(
                        agentType, s.selectedProvider?.id, s.thinkingEffort,
                    )
                } else {
                    agentRepository.setBinding(agentType, s.selectedProvider?.id, s.thinkingEffort)
                }
            }
        }
    }

    private fun coerceEffort(
        effort: ThinkingEffort,
        capability: ThinkingCapability?,
    ): Pair<ThinkingEffort, Boolean> {
        val steps = capability?.let { effortStepsFor(it) } ?: return Pair(effort, false)
        if (steps.isEmpty()) return Pair(effort, false)
        if (effort !in steps) {
            val fallback = steps.lastOrNull { it != ThinkingEffort.OFF } ?: ThinkingEffort.OFF
            return Pair(fallback, true)
        }
        return Pair(effort, false)
    }
}
```

- [ ] **Step 3: 验证编译**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin --quiet
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt
git commit -m "feat(android): Route + EditorViewModel 支持 isMemoryComponent"
```

---

### Task 8: Android — UI 层（`AgentBindingsPage` + `AgentBindingEditorPage` + `MainActivity`）

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`

- [ ] **Step 1: 替换 `AgentBindingsPage.kt`**

```kotlin
package com.sebastian.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.MemoryComponentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.displayLabel
import com.sebastian.android.ui.common.ToastCenter
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.AgentBindingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentBindingsPage(
    navController: NavController,
    viewModel: AgentBindingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val context = LocalContext.current
    LaunchedEffect(Unit) { viewModel.load() }
    LaunchedEffect(state.errorMessage) {
        val msg = state.errorMessage ?: return@LaunchedEffect
        ToastCenter.show(context, msg.ifBlank { "Failed to load agent bindings." }, key = "agent-bindings-load-error")
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Agent LLM Bindings") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        val (orchestrator, subAgents) = state.agents.partition { it.isOrchestrator }
        val defaultProvider = state.providers.firstOrNull { it.isDefault }

        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding)) {

            // ── Orchestrator ──────────────────────────────────────────────
            if (orchestrator.isNotEmpty()) {
                item { SectionHeader("Orchestrator") }
                items(orchestrator, key = { it.agentType }) { agent ->
                    AgentBindingRow(
                        headline = agent.displayName,
                        subtitle = resolveSubtitle(agent.boundProviderId, agent.thinkingEffort, state.providers, defaultProvider?.name),
                        icon = Icons.Outlined.AutoAwesome,
                        onClick = {
                            navController.navigate(
                                Route.SettingsAgentBindingEditor(agent.agentType, isMemoryComponent = false)
                            )
                        },
                    )
                }
            }

            // ── Memory Components ─────────────────────────────────────────
            if (state.memoryComponents.isNotEmpty()) {
                item { SectionHeader("Memory Components") }
                items(state.memoryComponents, key = { it.componentType }) { component ->
                    AgentBindingRow(
                        headline = component.displayName,
                        subtitle = resolveSubtitle(component.boundProviderId, component.thinkingEffort, state.providers, defaultProvider?.name),
                        icon = Icons.Outlined.Psychology,
                        onClick = {
                            navController.navigate(
                                Route.SettingsAgentBindingEditor(component.componentType, isMemoryComponent = true)
                            )
                        },
                    )
                }
            }

            // ── Sub-Agents ────────────────────────────────────────────────
            if (subAgents.isNotEmpty()) {
                item { SectionHeader("Sub-Agents") }
                items(subAgents, key = { it.agentType }) { agent ->
                    AgentBindingRow(
                        headline = agent.displayName,
                        subtitle = resolveSubtitle(agent.boundProviderId, agent.thinkingEffort, state.providers, defaultProvider?.name),
                        icon = Icons.Outlined.Extension,
                        onClick = {
                            navController.navigate(
                                Route.SettingsAgentBindingEditor(agent.agentType, isMemoryComponent = false)
                            )
                        },
                    )
                }
            }
        }
    }
}

private fun resolveSubtitle(
    boundProviderId: String?,
    thinkingEffort: ThinkingEffort,
    providers: List<Provider>,
    defaultProviderName: String?,
): String {
    val bound = providers.firstOrNull { it.id == boundProviderId }
    return if (bound != null) {
        buildString {
            append(bound.name)
            if (thinkingEffort != ThinkingEffort.OFF) {
                append(" · ")
                append(thinkingEffort.displayLabel())
            }
        }
    } else {
        "Use default · ${defaultProviderName ?: "—"}"
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 4.dp),
    )
}

@Composable
private fun AgentBindingRow(
    headline: String,
    subtitle: String,
    icon: ImageVector,
    onClick: () -> Unit,
) {
    ElevatedCard(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp)
            .clickable { onClick() },
    ) {
        ListItem(
            leadingContent = { Icon(icon, contentDescription = null) },
            headlineContent = { Text(headline) },
            supportingContent = { Text(subtitle) },
        )
    }
}
```

- [ ] **Step 2: 修改 `AgentBindingEditorPage.kt` — 函数签名 + ViewModel 创建**

将函数签名从：
```kotlin
fun AgentBindingEditorPage(
    agentType: String,
    navController: NavController,
)
```
改为：
```kotlin
fun AgentBindingEditorPage(
    agentType: String,
    isMemoryComponent: Boolean = false,
    navController: NavController,
)
```

将 ViewModel 创建代码从：
```kotlin
val vm: AgentBindingEditorViewModel =
    hiltViewModel<AgentBindingEditorViewModel, AgentBindingEditorViewModel.Factory>(
        key = agentType,
        creationCallback = { factory -> factory.create(agentType) },
    )
```
改为：
```kotlin
val vm: AgentBindingEditorViewModel =
    hiltViewModel<AgentBindingEditorViewModel, AgentBindingEditorViewModel.Factory>(
        key = "$agentType-$isMemoryComponent",
        creationCallback = { factory -> factory.create(agentType, isMemoryComponent) },
    )
```
其余代码不变。

- [ ] **Step 3: 修改 `MainActivity.kt` — 更新 composable 调用**

找到 `composable<Route.SettingsAgentBindingEditor>` 块，将其替换为：

```kotlin
composable<Route.SettingsAgentBindingEditor> { backStackEntry ->
    val route = backStackEntry.toRoute<Route.SettingsAgentBindingEditor>()
    AgentBindingEditorPage(
        agentType = route.agentType,
        isMemoryComponent = route.isMemoryComponent,
        navController = navController,
    )
}
```

- [ ] **Step 4: 构建并运行单元测试**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug --quiet
```
Expected: BUILD SUCCESSFUL。

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --quiet
```
Expected: BUILD SUCCESSFUL，所有既有测试通过。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt
git commit -m "feat(android): AgentBindingsPage Memory Components section + editor 路由更新"
```

---

## 自检结果

**Spec 覆盖：** 所有 spec 要求均有对应 Task ✅  
**Placeholder 扫描：** 无 TBD/TODO，所有步骤含完整代码 ✅  
**类型一致性：**
- `MemoryComponentInfo` 在 Task 4 定义，Task 5/6/8 使用 ✅
- `MemoryComponentBindingDto` 在 Task 4 定义，Task 5 使用 ✅
- `MemoryComponentsResponse` 在 Task 4 定义，Task 5 使用 ✅
- `Factory.create(agentType, isMemoryComponent)` 在 Task 7 定义，Task 8 调用 ✅
- `Route.SettingsAgentBindingEditor(agentType, isMemoryComponent)` 在 Task 7 定义，Task 8 使用 ✅
- `resolveSubtitle()` 在 Task 8 内部定义并使用，接受 `ThinkingEffort` 而非字符串 ✅
