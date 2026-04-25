# Memory Settings Persistence, Android UI & Confidence Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 持久化记忆功能开关（重启不丢失）、Android 前端记忆设置页面、Extractor 置信度评分规则。

**Architecture:** 新建 `app_settings` KV 表存储全局配置；Gateway lifespan 启动时从 DB 读取 `memory_enabled`，`PUT /api/v1/memory/settings` 同时写 DB；Android 新增 `MemorySettingsPage` + `MemorySettingsViewModel`，通过现有 `SettingsRepository` 调 API；`prompts.py` 新增置信度评分指南常量注入 extractor system prompt。

**Tech Stack:** Python 3.12 / SQLAlchemy async / FastAPI；Kotlin / Jetpack Compose / Hilt / Retrofit / Moshi

---

## 文件变更清单

| 操作 | 路径 |
|------|------|
| 修改 | `sebastian/store/models.py` |
| 新建 | `sebastian/store/app_settings_store.py` |
| 修改 | `sebastian/gateway/app.py` |
| 修改 | `sebastian/gateway/routes/memory_settings.py` |
| 修改 | `sebastian/memory/prompts.py` |
| 新建 | `tests/unit/store/test_app_settings_store.py` |
| 新建 | `tests/integration/test_memory_settings_persistence.py` |
| 修改 | `tests/unit/memory/test_prompts.py` |
| 新建 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MemorySettingsDto.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt` |
| 新建 | `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/MemorySettingsViewModel.kt` |
| 新建 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/MemorySettingsPage.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt` |
| 新建 | `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/MemorySettingsViewModelTest.kt` |

---

## Task 1: AppSettingsRecord + AppSettingsStore

**Files:**
- Modify: `sebastian/store/models.py`
- Create: `sebastian/store/app_settings_store.py`
- Create: `tests/unit/store/test_app_settings_store.py`

- [ ] **Step 1: 在 models.py 添加 AppSettingsRecord**

在 `sebastian/store/models.py` 的 import 行加 `Text`，并在文件末尾追加新 model：

```python
# 修改 import 行（原来没有 Text）
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
```

在文件末尾（`SessionConsolidationRecord` 类之后）追加：

```python
class AppSettingsRecord(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 2: 写失败测试**

新建 `tests/unit/store/test_app_settings_store.py`：

```python
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store.app_settings_store import APP_SETTING_MEMORY_ENABLED, AppSettingsStore
from sebastian.store.database import Base


@pytest_asyncio.fixture
async def db_session(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db", future=True)
    async with engine.begin() as conn:
        from sebastian.store import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(db_session) -> None:
    store = AppSettingsStore(db_session)
    assert await store.get("nonexistent") is None


@pytest.mark.asyncio
async def test_get_returns_default_when_absent(db_session) -> None:
    store = AppSettingsStore(db_session)
    assert await store.get("nonexistent", default="fallback") == "fallback"


@pytest.mark.asyncio
async def test_set_then_get_returns_value(db_session) -> None:
    store = AppSettingsStore(db_session)
    await store.set(APP_SETTING_MEMORY_ENABLED, "false")
    await db_session.commit()
    assert await store.get(APP_SETTING_MEMORY_ENABLED) == "false"


@pytest.mark.asyncio
async def test_set_upserts_on_second_call(db_session) -> None:
    store = AppSettingsStore(db_session)
    await store.set(APP_SETTING_MEMORY_ENABLED, "true")
    await db_session.commit()
    await store.set(APP_SETTING_MEMORY_ENABLED, "false")
    await db_session.commit()
    result = await store.get(APP_SETTING_MEMORY_ENABLED)
    assert result == "false"
```

- [ ] **Step 3: 运行测试确认失败**

```bash
pytest tests/unit/store/test_app_settings_store.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sebastian.store.app_settings_store'`

- [ ] **Step 4: 实现 AppSettingsStore**

新建 `sebastian/store/app_settings_store.py`：

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from sebastian.store.models import AppSettingsRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

APP_SETTING_MEMORY_ENABLED = "memory_enabled"


class AppSettingsStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str, default: str | None = None) -> str | None:
        """Return the value for *key*, or *default* if absent."""
        result = await self._session.execute(
            select(AppSettingsRecord).where(AppSettingsRecord.key == key)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return default
        return record.value

    async def set(self, key: str, value: str) -> None:
        """Upsert *key* → *value*. Caller must commit the session."""
        result = await self._session.execute(
            select(AppSettingsRecord).where(AppSettingsRecord.key == key)
        )
        record = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if record is None:
            self._session.add(AppSettingsRecord(key=key, value=value, updated_at=now))
        else:
            record.value = value
            record.updated_at = now
```

- [ ] **Step 5: 运行测试确认全过**

```bash
pytest tests/unit/store/test_app_settings_store.py -v
```

Expected: 4 PASSED

- [ ] **Step 6: 提交**

```bash
git add sebastian/store/models.py sebastian/store/app_settings_store.py tests/unit/store/test_app_settings_store.py
git commit -m "feat(store): 新增 AppSettingsRecord + AppSettingsStore KV 持久化

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Gateway 启动读 DB + PUT 路由持久化

**Files:**
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/routes/memory_settings.py`
- Create: `tests/integration/test_memory_settings_persistence.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/integration/test_memory_settings_persistence.py`：

```python
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store.app_settings_store import APP_SETTING_MEMORY_ENABLED, AppSettingsStore
from sebastian.store.database import Base


@pytest_asyncio.fixture
async def db_session(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db", future=True)
    async with engine.begin() as conn:
        from sebastian.store import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_memory_enabled_persisted_as_false(db_session) -> None:
    """PUT endpoint logic: after setting memory_enabled=false, DB stores 'false'."""
    store = AppSettingsStore(db_session)
    await store.set(APP_SETTING_MEMORY_ENABLED, "false")
    await db_session.commit()

    result = await store.get(APP_SETTING_MEMORY_ENABLED)
    assert result == "false"


@pytest.mark.asyncio
async def test_startup_reads_db_value_over_env_default(db_session) -> None:
    """Simulate gateway startup: DB value 'false' should override env default True."""
    store = AppSettingsStore(db_session)
    await store.set(APP_SETTING_MEMORY_ENABLED, "false")
    await db_session.commit()

    raw = await store.get(APP_SETTING_MEMORY_ENABLED)
    env_default = True
    mem_enabled = (raw.lower() == "true") if raw is not None else env_default
    assert mem_enabled is False


@pytest.mark.asyncio
async def test_startup_falls_back_to_env_when_db_empty(db_session) -> None:
    """When DB has no memory_enabled key, env default is used."""
    store = AppSettingsStore(db_session)
    raw = await store.get(APP_SETTING_MEMORY_ENABLED)
    env_default = True
    mem_enabled = (raw.lower() == "true") if raw is not None else env_default
    assert mem_enabled is True
```

- [ ] **Step 2: 运行测试确认通过**

```bash
pytest tests/integration/test_memory_settings_persistence.py -v
```

Expected: 3 PASSED（这些测试只测 store 逻辑，本身不依赖 gateway）

- [ ] **Step 3: 修改 gateway/app.py — 启动时从 DB 加载**

读取 `sebastian/gateway/app.py`，定位第 81-84 行（当前代码）：

```python
    from sebastian.gateway.state import MemoryRuntimeSettings

    state.memory_settings = MemoryRuntimeSettings(enabled=settings.sebastian_memory_enabled)
    db_factory = get_session_factory()
```

替换为（将 db_factory 初始化提前，再从 DB 读取）：

```python
    db_factory = get_session_factory()

    from sebastian.gateway.state import MemoryRuntimeSettings
    from sebastian.store.app_settings_store import APP_SETTING_MEMORY_ENABLED, AppSettingsStore

    async with db_factory() as _app_settings_session:
        _app_store = AppSettingsStore(_app_settings_session)
        _mem_val = await _app_store.get(APP_SETTING_MEMORY_ENABLED)
    mem_enabled = (_mem_val.lower() == "true") if _mem_val is not None else settings.sebastian_memory_enabled
    state.memory_settings = MemoryRuntimeSettings(enabled=mem_enabled)
```

- [ ] **Step 4: 修改 gateway/routes/memory_settings.py — PUT 写 DB**

把整个文件替换为：

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

import sebastian.gateway.state as state
from sebastian.gateway.auth import require_auth
from sebastian.gateway.state import MemoryRuntimeSettings

router = APIRouter(tags=["memory"])

AuthPayload = dict[str, Any]


@router.get("/memory/settings", response_model=MemoryRuntimeSettings)
async def get_memory_settings(
    _auth: AuthPayload = Depends(require_auth),
) -> MemoryRuntimeSettings:
    return state.memory_settings


@router.put("/memory/settings", response_model=MemoryRuntimeSettings)
async def put_memory_settings(
    body: MemoryRuntimeSettings,
    _auth: AuthPayload = Depends(require_auth),
) -> MemoryRuntimeSettings:
    from sebastian.store.app_settings_store import APP_SETTING_MEMORY_ENABLED, AppSettingsStore

    async with state.db_factory() as session:
        store = AppSettingsStore(session)
        await store.set(APP_SETTING_MEMORY_ENABLED, str(body.enabled).lower())
        await session.commit()
    state.memory_settings = body
    return state.memory_settings
```

- [ ] **Step 5: 运行全量测试确认无回归**

```bash
pytest tests/ -x -q
```

Expected: all tests pass

- [ ] **Step 6: 提交**

```bash
git add sebastian/gateway/app.py sebastian/gateway/routes/memory_settings.py tests/integration/test_memory_settings_persistence.py
git commit -m "feat(gateway): memory_settings 开关持久化到 DB，重启后保留

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Extractor 置信度评分规则

**Files:**
- Modify: `sebastian/memory/prompts.py`
- Modify: `tests/unit/memory/test_prompts.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/memory/test_prompts.py` 文件末尾追加：

```python
def test_extractor_prompt_contains_confidence_guide() -> None:
    """置信度评分指南必须出现在 extractor system prompt 中。"""
    from sebastian.memory.prompts import build_extractor_prompt, group_slots_by_kind
    from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY

    prompt = build_extractor_prompt(group_slots_by_kind(DEFAULT_SLOT_REGISTRY.list_all()))

    assert "置信度评分指南" in prompt
    assert "0.9" in prompt
    assert "source=explicit" in prompt
    assert "source=inferred" in prompt
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/memory/test_prompts.py::test_extractor_prompt_contains_confidence_guide -v
```

Expected: FAIL with `AssertionError`

- [ ] **Step 3: 在 prompts.py 新增置信度常量并注入 prompt**

读取 `sebastian/memory/prompts.py`，在 `_EXTRACTOR_FIELD_TABLE` 常量定义之后、`build_extractor_prompt` 函数之前，插入新常量：

```python
_CONFIDENCE_SCORING_GUIDE = """\
## 置信度评分指南

confidence 字段反映你对该记忆内容准确性的把握程度：

| 分值区间 | 适用场景 |
|---|---|
| 0.9 – 1.0 | 用户明确陈述的事实（"我喜欢X"、"我叫X"、"我在X工作"） |
| 0.7 – 0.9 | 对话中直接体现但非明确声明（"每次都选X"、重复提及同一偏好） |
| 0.5 – 0.7 | 从行为或上下文推断的偏好，有一定根据但非直述 |
| 0.3 – 0.5 | 模糊线索或单次偶然提及，可信度较低 |
| < 0.3 | 高度不确定的推断，几乎只有间接证据（建议不提取） |

附加约束：
- source=explicit 时，confidence 不应低于 0.8
- source=inferred 时，confidence 上限建议不超过 0.75
- 宁可少提取，不提取低质量记忆
"""
```

将 `build_extractor_prompt` 函数中的 return 语句修改为：

```python
def build_extractor_prompt(known_slots_by_kind: dict[str, list[dict[str, str]]]) -> str:
    rules = build_slot_rules_section(known_slots_by_kind)
    return f"""\
你是记忆提取助手。分析给定的对话内容，抽取出有记忆价值的信息。

{_EXTRACTOR_FIELD_TABLE}

{_CONFIDENCE_SCORING_GUIDE}

{rules}
"""
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/memory/test_prompts.py -v
```

Expected: all tests PASSED

- [ ] **Step 5: 提交**

```bash
git add sebastian/memory/prompts.py tests/unit/memory/test_prompts.py
git commit -m "feat(memory): extractor prompt 加入置信度评分指南

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Android DTO + ApiService

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MemorySettingsDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`

- [ ] **Step 1: 新建 MemorySettingsDto.kt**

新建 `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MemorySettingsDto.kt`：

```kotlin
package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class MemorySettingsDto(
    @param:Json(name = "enabled") val enabled: Boolean,
)
```

- [ ] **Step 2: 在 ApiService.kt 添加 memory settings 接口**

在 `ApiService.kt` 的 `// Health` 注释块上方，添加新的 `// Memory Settings` 块：

```kotlin
    // Memory Settings
    @GET("api/v1/memory/settings")
    suspend fun getMemorySettings(): MemorySettingsDto

    @PUT("api/v1/memory/settings")
    suspend fun putMemorySettings(@Body body: MemorySettingsDto): MemorySettingsDto
```

- [ ] **Step 3: 运行 Android 单测确认编译通过**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -5
```

Expected: `BUILD SUCCESSFUL`

- [ ] **Step 4: 提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MemorySettingsDto.kt
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt
git commit -m "feat(android): 新增 MemorySettingsDto + ApiService memory settings 接口

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: SettingsRepository 新增 memory settings 方法

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt`

- [ ] **Step 1: 在 SettingsRepository 接口末尾加两个方法**

在 `SettingsRepository.kt` 的 `patchLogState` 行下方追加：

```kotlin
    suspend fun getMemorySettings(): Result<MemorySettingsDto>
    suspend fun setMemoryEnabled(enabled: Boolean): Result<MemorySettingsDto>
```

同时在文件 import 区加：

```kotlin
import com.sebastian.android.data.remote.dto.MemorySettingsDto
```

- [ ] **Step 2: 在 SettingsRepositoryImpl 实现两个方法**

在 `SettingsRepositoryImpl.kt` 末尾的 `}` 之前追加：

```kotlin
    override suspend fun getMemorySettings(): Result<MemorySettingsDto> = runCatching {
        apiService.getMemorySettings()
    }

    override suspend fun setMemoryEnabled(enabled: Boolean): Result<MemorySettingsDto> = runCatching {
        apiService.putMemorySettings(MemorySettingsDto(enabled = enabled))
    }
```

同时在文件 import 区加：

```kotlin
import com.sebastian.android.data.remote.dto.MemorySettingsDto
```

- [ ] **Step 3: 编译确认**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -5
```

Expected: `BUILD SUCCESSFUL`

- [ ] **Step 4: 提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt
git commit -m "feat(android): SettingsRepository 新增 memory settings 读写方法

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: MemorySettingsViewModel

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/MemorySettingsViewModel.kt`
- Create: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/MemorySettingsViewModelTest.kt`

- [ ] **Step 1: 写失败测试**

新建 `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/MemorySettingsViewModelTest.kt`：

```kotlin
package com.sebastian.android.viewmodel

import com.sebastian.android.data.remote.dto.MemorySettingsDto
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class MemorySettingsViewModelTest {

    private val dispatcher = StandardTestDispatcher()
    private lateinit var repository: SettingsRepository

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        repository = mock()
        // SettingsRepository 中 Flow 型属性需要 stub（否则 SettingsViewModel 依赖链会崩）
        // MemorySettingsViewModel 仅依赖 getMemorySettings/setMemoryEnabled，无需 stub flows
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `init loads memory settings and updates enabled state`() = runTest {
        whenever(repository.getMemorySettings())
            .thenReturn(Result.success(MemorySettingsDto(enabled = false)))

        val viewModel = MemorySettingsViewModel(repository, dispatcher)
        advanceUntilIdle()

        assertEquals(false, viewModel.uiState.value.enabled)
        assertEquals(false, viewModel.uiState.value.isLoading)
        assertNull(viewModel.uiState.value.error)
    }

    @Test
    fun `toggle success updates enabled state`() = runTest {
        whenever(repository.getMemorySettings())
            .thenReturn(Result.success(MemorySettingsDto(enabled = true)))
        whenever(repository.setMemoryEnabled(false))
            .thenReturn(Result.success(MemorySettingsDto(enabled = false)))

        val viewModel = MemorySettingsViewModel(repository, dispatcher)
        advanceUntilIdle()

        viewModel.toggle(false)
        advanceUntilIdle()

        assertEquals(false, viewModel.uiState.value.enabled)
        assertNull(viewModel.uiState.value.error)
    }

    @Test
    fun `toggle failure rolls back state and sets error`() = runTest {
        whenever(repository.getMemorySettings())
            .thenReturn(Result.success(MemorySettingsDto(enabled = true)))
        whenever(repository.setMemoryEnabled(false))
            .thenReturn(Result.failure(Exception("network error")))

        val viewModel = MemorySettingsViewModel(repository, dispatcher)
        advanceUntilIdle()

        viewModel.toggle(false)
        advanceUntilIdle()

        assertEquals(true, viewModel.uiState.value.enabled)  // rolled back
        assertNotNull(viewModel.uiState.value.error)
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.MemorySettingsViewModelTest" 2>&1 | tail -10
```

Expected: FAIL with class not found

- [ ] **Step 3: 实现 MemorySettingsViewModel**

新建 `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/MemorySettingsViewModel.kt`：

```kotlin
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class MemorySettingsUiState(
    val enabled: Boolean = true,
    val isLoading: Boolean = true,
    val error: String? = null,
)

@HiltViewModel
class MemorySettingsViewModel @Inject constructor(
    private val repository: SettingsRepository,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(MemorySettingsUiState())
    val uiState: StateFlow<MemorySettingsUiState> = _uiState.asStateFlow()

    init {
        loadSettings()
    }

    private fun loadSettings() {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true) }
            repository.getMemorySettings()
                .onSuccess { dto ->
                    _uiState.update { it.copy(enabled = dto.enabled, isLoading = false) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
        }
    }

    fun toggle(enabled: Boolean) {
        val prev = _uiState.value.enabled
        _uiState.update { it.copy(enabled = enabled, isLoading = true) }
        viewModelScope.launch(dispatcher) {
            repository.setMemoryEnabled(enabled)
                .onSuccess { dto ->
                    _uiState.update { it.copy(enabled = dto.enabled, isLoading = false) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(enabled = prev, isLoading = false, error = "更新失败，已回滚") }
                }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.MemorySettingsViewModelTest" 2>&1 | tail -10
```

Expected: 3 tests PASSED

- [ ] **Step 5: 提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/MemorySettingsViewModel.kt
git add ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/MemorySettingsViewModelTest.kt
git commit -m "feat(android): MemorySettingsViewModel + 单元测试

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: MemorySettingsPage

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/MemorySettingsPage.kt`

- [ ] **Step 1: 新建 MemorySettingsPage.kt**

参考 `DebugLoggingPage.kt` 的结构（Scaffold + TopAppBar + Surface Card + 说明文字）：

```kotlin
package com.sebastian.android.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.common.SebastianSwitch
import com.sebastian.android.viewmodel.MemorySettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MemorySettingsPage(
    navController: NavController,
    viewModel: MemorySettingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(state.error) {
        state.error?.let { msg ->
            snackbarHostState.showSnackbar(msg)
            viewModel.clearError()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("记忆功能") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp),
        ) {
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = MaterialTheme.colorScheme.surfaceContainer,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "启用记忆功能",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.weight(1f),
                    )
                    SebastianSwitch(
                        checked = state.enabled,
                        onCheckedChange = viewModel::toggle,
                        enabled = !state.isLoading,
                    )
                }
            }
            Text(
                text = "开启后 Sebastian 会记住你的偏好、习惯和重要信息，跨会话持续生效。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 8.dp, start = 4.dp),
            )
        }
    }
}
```

- [ ] **Step 2: 编译确认**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -5
```

Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: 提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/MemorySettingsPage.kt
git commit -m "feat(android): 新增 MemorySettingsPage

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: 导航注册 + SettingsScreen 入口

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt`

- [ ] **Step 1: Route.kt 新增 SettingsMemory**

在 `Route.kt` 中，在 `SettingsDebugLogging` 对象之后追加：

```kotlin
    @Serializable
    data object SettingsMemory : Route()
```

- [ ] **Step 2: MainActivity.kt 注册 composable**

在 `MainActivity.kt` 中，找到 `composable<Route.SettingsDebugLogging>` 块（约第 237 行），在其后追加：

```kotlin
            composable<Route.SettingsMemory> {
                MemorySettingsPage(navController = navController)
            }
```

同时在文件顶部 import 区追加：

```kotlin
import com.sebastian.android.ui.settings.MemorySettingsPage
```

- [ ] **Step 3: SettingsScreen.kt 新增入口行**

在 `SettingsScreen.kt` 中，找到 `SettingsRow` for `"Agent LLM Bindings"`（当前 `isLast = true`），将其 `isLast` 改为 `false`，并在其后追加新行：

```kotlin
                    SettingsRow(
                        icon = Icons.Outlined.Extension,
                        title = "Agent LLM Bindings",
                        subtitle = "为每个 Agent 选择 Provider",
                        onClick = { navController.navigate(Route.SettingsAgentBindings) { launchSingleTop = true } },
                    )
                    SettingsRow(
                        icon = Icons.Outlined.Psychology,
                        title = "记忆功能",
                        subtitle = "长期记忆开关",
                        isLast = true,
                        onClick = { navController.navigate(Route.SettingsMemory) { launchSingleTop = true } },
                    )
```

同时在文件顶部 import 区追加（`Icons.Outlined.Psychology` 所需）：

```kotlin
import androidx.compose.material.icons.outlined.Psychology
```

- [ ] **Step 4: 编译确认**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -5
```

Expected: `BUILD SUCCESSFUL`

- [ ] **Step 5: 运行全量 Android 单测**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest 2>&1 | tail -10
```

Expected: all tests PASSED

- [ ] **Step 6: 提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt
git add ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt
git commit -m "feat(android): SettingsScreen 记忆功能入口 + 导航注册

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
