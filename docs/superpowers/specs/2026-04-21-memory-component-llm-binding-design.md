# Memory Component LLM Provider Binding

**Date**: 2026-04-21  
**Status**: approved  
**Related spec**: `docs/architecture/spec/memory/implementation.md §3`

---

## 背景

记忆系统的 `MemoryExtractor`（`extraction.py`）和 `MemoryConsolidator`（`consolidation.py`）都通过 `LLMProviderRegistry.get_provider(binding_key)` 调用 LLM。调用已实现，binding key 常量也已定义（`provider_bindings.py`）：

```python
MEMORY_EXTRACTOR_BINDING    = "memory_extractor"
MEMORY_CONSOLIDATOR_BINDING = "memory_consolidator"
```

`get_provider(agent_type)` 的解析逻辑：查 `AgentLLMBindingRecord`，有绑定则用，无则 fallback 到全局默认 provider。这套逻辑已完整。

**缺口**：`GET/PUT/DELETE /agents/{agent_type}/llm-binding` 的校验白名单只认 `agent_registry` 里的注册 agent，`"memory_extractor"` / `"memory_consolidator"` 会返回 404。Android 也没有任何 UI 入口配置这两个绑定。

---

## 目标

让用户能在 Android App 中为记忆提取器和记忆沉淀器独立指定 LLM Provider，与 Agent 绑定管理在 UI 上同页呈现，但在后端路由上完全独立，避免代码耦合。

---

## 设计决策

**后端**：新增独立路由 `/memory/components`，不复用 `/agents` 路由，不修改 `agents.py` 验证逻辑。存储层仍复用 `AgentLLMBindingRecord`（不加新表），`agent_type` 字段的值即 `component_type`。

**Android**：在现有 `AgentBindingsPage` 中插入第二个 section "Memory Components"（位于 Orchestrator 之后、Sub-Agents 之前）。点击行复用现有 `AgentBindingEditorPage`，通过 `isMemoryComponent` 标志切换调用端点。

---

## 后端

### 1. `sebastian/memory/provider_bindings.py` 补充

```python
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

元数据集中在 `provider_bindings.py`，路由层不写死 display name。

### 2. 新文件：`sebastian/gateway/routes/memory_components.py`

路由前缀：`/memory/components`（注册在 `/api/v1` 下）。

#### `GET /memory/components`

返回两个 memory 组件及其当前绑定：

```json
{
  "components": [
    {
      "component_type": "memory_extractor",
      "display_name": "记忆提取器",
      "description": "从会话片段中提取候选 memory artifact",
      "binding": {
        "provider_id": "abc123",
        "thinking_effort": null
      }
    },
    {
      "component_type": "memory_consolidator",
      "display_name": "记忆沉淀器",
      "description": "会话结束后归纳 session summary 和推断偏好",
      "binding": null
    }
  ]
}
```

`binding` 为 `null` 表示该组件没有 binding 行，运行时 fallback 到全局默认 provider。

#### `GET /memory/components/{component_type}/llm-binding`

返回单个组件的绑定。`component_type` 不在白名单时 404。无 binding 行时不返回 404，而是返回 `provider_id: null`（与 `/agents/{agent_type}/llm-binding` 行为一致）：

```json
{
  "component_type": "memory_extractor",
  "provider_id": null,
  "thinking_effort": null
}
```

#### `PUT /memory/components/{component_type}/llm-binding`

请求体：

```json
{
  "provider_id": "abc123",
  "thinking_effort": "low"
}
```

- `provider_id` 为 `null` → 清除绑定（等同 DELETE）
- `provider_id` 指向不存在的 provider → 400
- provider 的 `thinking_capability` 为 `"none"` 或 `"always_on"` → 强制清空 `thinking_effort`（与 agents.py 行为一致）
- provider 切换时 `thinking_effort` 重置为 `null`

返回更新后的绑定对象（格式同 GET）。

#### `DELETE /memory/components/{component_type}/llm-binding`

204 No Content。删除后组件 fallback 到全局默认 provider。

### 3. `sebastian/gateway/app.py`

将 `memory_components.router` 注册到现有 router 列表，prefix 为 `/api/v1`，与其他路由一致。

### 4. `agents.py` 不改动

`/agents` 路由的校验逻辑不感知 memory component 类型。两套路由完全独立。

---

## Android

### 1. 数据层

**新 DTO**：`data/remote/dto/MemoryComponentDto.kt`

```kotlin
@JsonClass(generateAdapter = true)
data class MemoryComponentDto(
    @Json(name = "component_type") val componentType: String,
    @Json(name = "display_name")   val displayName: String,
    val description: String,
    val binding: AgentBindingDto?,
)

@JsonClass(generateAdapter = true)
data class MemoryComponentsResponseDto(
    val components: List<MemoryComponentDto>,
)
```

**Domain model**：`data/model/MemoryComponentInfo.kt`

```kotlin
data class MemoryComponentInfo(
    val componentType: String,
    val displayName: String,
    val description: String,
    val boundProviderId: String? = null,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
)
```

与 `AgentInfo` 平行，不复用同一 data class，语义独立。

**`ApiService`** 新增：

```kotlin
// GET /api/v1/memory/components
suspend fun listMemoryComponents(): MemoryComponentsResponseDto

// GET /api/v1/memory/components/{componentType}/llm-binding
suspend fun getMemoryComponentBinding(componentType: String): AgentBindingDto

// PUT /api/v1/memory/components/{componentType}/llm-binding
suspend fun setMemoryComponentBinding(componentType: String, body: AgentBindingUpdateDto): AgentBindingDto

// DELETE /api/v1/memory/components/{componentType}/llm-binding
suspend fun clearMemoryComponentBinding(componentType: String)
```

**`AgentRepository`** 新增 `listMemoryComponents(): List<MemoryComponentInfo>`，负责 DTO → domain model 映射。

### 2. ViewModel 层

**`AgentBindingsViewModel`**

`load()` 并发发出三个请求（`GET /agents`、`GET /memory/components`、`GET /llm-providers`），结果合并到 `UiState`：

```kotlin
data class AgentBindingsUiState(
    val agents: List<AgentInfo> = emptyList(),
    val memoryComponents: List<MemoryComponentInfo> = emptyList(),
    val providers: List<Provider> = emptyList(),
    val errorMessage: String? = null,
)
```

**`AgentBindingEditorViewModel`**

Factory 增加 `isMemoryComponent: Boolean` 参数。VM 内部：

- `isMemoryComponent = false` → 调用 `AgentRepository` 的 agent binding 方法（`/agents/{agentType}/llm-binding`）
- `isMemoryComponent = true` → 调用 `AgentRepository` 的 memory component binding 方法（`/memory/components/{componentType}/llm-binding`）

除端点选择外，加载 provider 列表、thinking effort 管理、保存/清除逻辑完全共享。

### 3. 导航

**`Route.SettingsAgentBindingEditor`** 增加 `isMemoryComponent: Boolean = false`：

```kotlin
@Serializable
data class SettingsAgentBindingEditor(
    val agentType: String,
    val isMemoryComponent: Boolean = false,
)
```

`AgentBindingEditorPage` 将 `isMemoryComponent` 传入 ViewModel factory。

### 4. UI：`AgentBindingsPage`

Section 顺序：

```
[Orchestrator]
  sebastian

[Memory Components]
  记忆提取器   (memory_extractor)
  记忆沉淀器   (memory_consolidator)

[Sub-Agents]
  ...（数量可变）
```

`MemoryComponentRow` 外观与 `AgentRow` 一致，icon 使用 `Icons.Outlined.Psychology`，点击：

```kotlin
navController.navigate(
    Route.SettingsAgentBindingEditor(
        agentType = component.componentType,
        isMemoryComponent = true,
    )
)
```

---

## 存储层说明

两个 memory component 的绑定存储在 `AgentLLMBindingRecord` 表中，`agent_type` 字段值分别为 `"memory_extractor"` 和 `"memory_consolidator"`，与 agent binding 行共存于同一表。

**无需新建表**。区分方式：memory component 路由通过 `MEMORY_COMPONENT_TYPES` 白名单管理自己的键空间；agent 路由通过 `agent_registry` 管理自己的键空间。两者互不干扰。

---

## 不在本次范围

- temperature 独立配置（spec 已明确短期不做）
- memory component 绑定的 CLI/Web UI 入口（当前只做 Android）
- 新增 memory component 类型（如 `memory_retriever`）的自动发现机制

---

## 文件改动清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `sebastian/memory/provider_bindings.py` | 修改 | 新增 `MEMORY_COMPONENT_TYPES` + `MEMORY_COMPONENT_META` |
| `sebastian/gateway/routes/memory_components.py` | 新建 | 4 个路由（list / get / put / delete） |
| `sebastian/gateway/app.py` | 修改 | 注册新 router |
| `tests/unit/test_memory_components_route.py` | 新建 | 路由单元测试 |
| `ui/mobile-android/.../dto/MemoryComponentDto.kt` | 新建 | DTO + response wrapper |
| `ui/mobile-android/.../model/MemoryComponentInfo.kt` | 新建 | Domain model |
| `ui/mobile-android/.../remote/ApiService.kt` | 修改 | 新增 4 个 API 方法 |
| `ui/mobile-android/.../repository/AgentRepository.kt` | 修改 | 新增 `listMemoryComponents()` 接口 |
| `ui/mobile-android/.../repository/AgentRepositoryImpl.kt` | 修改 | 实现 `listMemoryComponents()` |
| `ui/mobile-android/.../viewmodel/AgentBindingsViewModel.kt` | 修改 | 加载 memory components，UiState 新增字段 |
| `ui/mobile-android/.../viewmodel/AgentBindingEditorViewModel.kt` | 修改 | Factory 加 `isMemoryComponent` 参数 |
| `ui/mobile-android/.../navigation/Route.kt` | 修改 | `SettingsAgentBindingEditor` 加 `isMemoryComponent` |
| `ui/mobile-android/.../settings/AgentBindingsPage.kt` | 修改 | 插入 Memory Components section |
| `ui/mobile-android/.../settings/AgentBindingEditorPage.kt` | 修改 | 传 `isMemoryComponent` 给 ViewModel |
| `docs/architecture/spec/memory/implementation.md` | 修改 | §3 provider binding 部分补充路由说明 |
