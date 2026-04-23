---
integrated_to: memory/implementation.md
integrated_at: 2026-04-23
---

# Memory Settings Persistence & Confidence Scoring Design

**Goal:** 持久化记忆功能开关（重启不丢失）+ Android 前端开关 UI + Extractor 置信度评分规则。

**Architecture:** 新建 `app_settings` KV 表作为通用全局配置存储，`AppSettingsStore` 封装读写，Gateway 启动时从 DB 加载覆盖环境变量；Android 新增 `MemorySettingsPage`，与后端 `PUT /api/v1/memory/settings` 联动；Extractor prompt 加置信度评分指南，约束模型评分行为。

**Tech Stack:** Python / SQLAlchemy async / FastAPI；Kotlin / Jetpack Compose / Retrofit

---

## 1. 后端：`app_settings` 表 & `AppSettingsStore`

### 数据模型

新增 `AppSettingsRecord`（`store/models.py`）：

```python
class AppSettingsRecord(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
```

已知常量（定义在 `store/app_settings_store.py`）：

```python
APP_SETTING_MEMORY_ENABLED = "memory_enabled"
```

### AppSettingsStore（新文件 `store/app_settings_store.py`）

```python
class AppSettingsStore:
    def __init__(self, session: AsyncSession) -> None: ...

    async def get(self, key: str, default: str | None = None) -> str | None:
        """查询指定 key，不存在返回 default。"""

    async def set(self, key: str, value: str) -> None:
        """Upsert：存在则更新 value + updated_at，不存在则插入。"""
```

### Gateway 启动加载（`gateway/app.py` lifespan）

```python
async with db_factory() as session:
    app_settings_store = AppSettingsStore(session)
    mem_val = await app_settings_store.get(APP_SETTING_MEMORY_ENABLED)
    if mem_val is not None:
        mem_enabled = mem_val.lower() == "true"
    else:
        mem_enabled = settings.sebastian_memory_enabled  # 环境变量 fallback
state.memory_settings = MemoryRuntimeSettings(enabled=mem_enabled)
```

### PUT /api/v1/memory/settings（`gateway/routes/memory_settings.py`）

在更新内存状态的同时写入 DB：

```python
@router.put("/memory/settings", response_model=MemoryRuntimeSettings)
async def put_memory_settings(body: MemoryRuntimeSettings, ...) -> MemoryRuntimeSettings:
    async with state.db_factory() as session:
        store = AppSettingsStore(session)
        await store.set(APP_SETTING_MEMORY_ENABLED, str(body.enabled).lower())
        await session.commit()
    state.memory_settings = body
    return state.memory_settings
```

### 数据库 Migration

项目使用 `Base.metadata.create_all` 自动建表（检查 `store/database.py`），新增 model 后在 `create_all` 前 import `AppSettingsRecord` 即可，无需 Alembic migration。

---

## 2. Android 前端

### API 层（`SebastianApiService`）

```kotlin
@GET("api/v1/memory/settings")
suspend fun getMemorySettings(@Header("Authorization") token: String): MemorySettingsDto

@PUT("api/v1/memory/settings")
suspend fun putMemorySettings(
    @Header("Authorization") token: String,
    @Body body: MemorySettingsDto,
): MemorySettingsDto

data class MemorySettingsDto(@SerializedName("enabled") val enabled: Boolean)
```

### 导航

`Route.kt` 新增：

```kotlin
data object SettingsMemory : Route()
```

`NavGraph` 注册对应 `MemorySettingsPage` composable。

### MemorySettingsViewModel（新文件）

```kotlin
data class MemorySettingsUiState(
    val enabled: Boolean = true,
    val isLoading: Boolean = true,
    val error: String? = null,
)

class MemorySettingsViewModel(private val api: SebastianApiService) : ViewModel() {
    val uiState: StateFlow<MemorySettingsUiState>

    // 启动时 load
    init { loadSettings() }

    fun toggle(enabled: Boolean) {
        // 乐观更新 → PUT → 失败回滚 + 设置 error
    }
}
```

### MemorySettingsPage（新文件）

使用已有 `SebastianSwitch` 组件：

```
┌─────────────────────────────────┐
│ ←  记忆功能                      │  TopAppBar
├─────────────────────────────────┤
│                                 │
│  ┌─────────────────────────┐    │
│  │ 启用记忆功能  [SebastianSwitch] │ Card
│  │                         │    │
│  │ 开启后 Sebastian 会记住  │    │
│  │ 你的偏好、习惯和重要信息，│    │
│  │ 跨会话持续生效。         │    │
│  └─────────────────────────┘    │
│                                 │
└─────────────────────────────────┘
```

- Switch 变化时立即调 `viewModel.toggle()`
- `isLoading=true` 时 Switch `enabled=false`（防止重复操作）
- 错误时用 Snackbar 提示，状态回滚

### SettingsScreen 入口

在现有第一个分组 Card 内，`Agent LLM Bindings` 行下方新增（`isLast = true` 移至此行）：

```kotlin
SettingsRow(
    icon = Icons.Outlined.Psychology,  // Memory chip 已被"模型与 Provider"用，改用 Psychology
    title = "记忆功能",
    subtitle = "长期记忆开关",
    isLast = true,
    onClick = { navController.navigate(Route.SettingsMemory) { launchSingleTop = true } },
)
```

---

## 3. Extractor 置信度评分规则

在 `sebastian/memory/prompts.py` 的 extractor system prompt 中新增「置信度评分指南」段落：

```
## 置信度评分指南

confidence 字段反映你对该记忆内容准确性的把握程度，评分标准如下：

| 分值区间 | 适用场景 |
|----------|---------|
| 0.9 – 1.0 | 用户明确陈述的事实（"我喜欢X"、"我叫X"、"我在X工作"） |
| 0.7 – 0.9 | 对话中直接体现但非明确声明（"每次都选X"、重复提及同一偏好） |
| 0.5 – 0.7 | 从行为或上下文推断的偏好，有一定根据但非直述 |
| 0.3 – 0.5 | 模糊线索或单次偶然提及，可信度较低 |
| < 0.3    | 高度不确定的推断，几乎只有间接证据（建议直接不提取） |

附加约束：
- source 为 explicit 时，confidence 不应低于 0.8
- source 为 inferred 时，confidence 上限建议不超过 0.75
- 若不确定是否值得提取，优先提高 confidence 阈值要求而非强行提取低质量记忆
```

---

## 4. 文件变更清单

### 后端（Python）

| 操作 | 文件 |
|------|------|
| 新建 | `sebastian/store/app_settings_store.py` |
| 修改 | `sebastian/store/models.py`（新增 `AppSettingsRecord`） |
| 修改 | `sebastian/gateway/app.py`（lifespan 读 DB） |
| 修改 | `sebastian/gateway/routes/memory_settings.py`（PUT 写 DB） |
| 修改 | `sebastian/memory/prompts.py`（置信度评分指南） |

### Android（Kotlin）

| 操作 | 文件 |
|------|------|
| 修改 | `SebastianApiService.kt`（新增两个 memory settings 接口） |
| 修改 | `Route.kt`（新增 `SettingsMemory`） |
| 修改 | `NavGraph.kt`（注册 MemorySettingsPage） |
| 新建 | `ui/settings/MemorySettingsViewModel.kt` |
| 新建 | `ui/settings/MemorySettingsPage.kt` |
| 修改 | `ui/settings/SettingsScreen.kt`（新增入口行） |

---

## 5. 测试要点

- `AppSettingsStore.set` → `get` 幂等；upsert 多次只有一条记录
- Gateway 启动：DB 有值时用 DB 值；DB 无值时 fallback 到环境变量
- `PUT /api/v1/memory/settings` → DB 持久化 → 重启后 GET 返回相同值
- Android：toggle 失败时 UI 回滚到原值，Snackbar 显示错误
- Extractor：对 explicit source 的 artifact，confidence 不低于 0.8（prompt 规则测试，可用 unit test mock LLM）
