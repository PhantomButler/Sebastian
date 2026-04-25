# LLM Catalog × Context Compaction 联合审计修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复联合审计发现的 8 处问题（CI 必红的测试不一致、Android 调用已删除路由、过时注释、缺失 README、隐式 guard 等），让两份 spec 落地后的代码进入干净状态。

**Architecture:** 全部为局部修复 / 删除 / 文档补齐，不引入新模块。按"先修红 → 再清遗留 → 最后补文档"顺序，每个 Task 单独成 commit，便于 review。

**Tech Stack:** Python 3.12 (后端 + 测试)、Kotlin (Android)、Markdown (spec / README)。

**Branch:** 从 `main` 开 `fix/llm-context-followup`。

**范围声明（确认与排除）：**
- ✅ 本计划包含：zhipu 测试、spec reason 字段、Android 旧 Provider 链路清理、`re_encrypt_api_keys.py`、`__default__` DELETE 显式 guard、`sebastian/context/README.md`、`sebastian/README.md` 模块树、`sebastian/llm/README.md` 过时注释。
- ❌ 不在本计划：`docs/architecture/spec/core/llm-provider.md` 大改、agent/memory binding 响应补 `resolved` 字段、Android Compact context 调试入口、tool block exchange 字段设计风险、`asyncio.create_task` 引用持有、补缺失测试用例。这些归属"可单独 PR"，已在审计报告 §建议处理顺序 第 3 组列出。

---

## Task 1: 修 zhipu catalog 单元测试断言

**背景：** [`builtin_providers.json:79-104`](sebastian/llm/catalog/builtin_providers.json) 定义了 `display_name="Zhi Pu Coding"` + 3 个模型（glm-5.1 / glm-5v-turbo / glm-4.7，最后一个由 commit `d835182 add glm 4.7 config` 加入）。但 [`tests/unit/llm/test_llm_catalog.py:299,302`](tests/unit/llm/test_llm_catalog.py:299) 仍断言 `display_name == "智谱"` 和 `len(models) == 2`，导致单测必红。

**约束（来自用户）：** 不动 JSON 中 `display_name`（用户已改）；只改测试。

**Files:**
- Modify: `tests/unit/llm/test_llm_catalog.py:297-303` 以及补 glm-4.7 单测

- [ ] **Step 1: 先跑当前 zhipu 相关测试确认红**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/unit/llm/test_llm_catalog.py::TestBuiltinCatalog::test_zhipu_provider tests/unit/llm/test_llm_catalog.py::TestBuiltinCatalog::test_zhipu_glm51 tests/unit/llm/test_llm_catalog.py::TestBuiltinCatalog::test_zhipu_glm5v_turbo -v
```
Expected: `test_zhipu_provider` FAIL（`AssertionError: '智谱' == 'Zhi Pu Coding'` 或 `2 == 3`），其余 PASS。

- [ ] **Step 2: 修 `test_zhipu_provider`**

打开 [`tests/unit/llm/test_llm_catalog.py:297-303`](tests/unit/llm/test_llm_catalog.py:297)，把这两个断言改成对齐 JSON 实际值：

```python
    def test_zhipu_provider(self) -> None:
        p = self.catalog.get_provider("zhipu")
        assert p.display_name == "Zhi Pu Coding"
        assert p.provider_type == "anthropic"
        assert p.base_url == "https://open.bigmodel.cn/api/anthropic"
        assert len(p.models) == 3
```

- [ ] **Step 3: 为 glm-4.7 新增单测**

紧跟 `test_zhipu_glm5v_turbo` 之后追加：

```python
    def test_zhipu_glm47(self) -> None:
        m = self.catalog.get_model("zhipu", "glm-4.7")
        assert m.display_name == "GLM-4.7"
        assert m.context_window_tokens == 200_000
        assert m.thinking_capability == "toggle"
        assert m.thinking_format is None
```

- [ ] **Step 4: 跑完整 catalog 测试**

Run:
```bash
pytest tests/unit/llm/test_llm_catalog.py -v
```
Expected: 所有用例 PASS（含新增的 `test_zhipu_glm47`）。

- [ ] **Step 5: 提交**

```bash
git add tests/unit/llm/test_llm_catalog.py
git commit -m "$(cat <<'EOF'
test(llm): 对齐 zhipu catalog 断言并补 glm-4.7 用例

- display_name 从 "智谱" 改为实际 JSON 值 "Zhi Pu Coding"
- 模型数量 2 → 3
- 新增 test_zhipu_glm47 覆盖新模型规格

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: spec 文档对齐实现的 reason 字段值

**背景：** [`compaction.py:394`](sebastian/context/compaction.py:394) 实际产出 `reason="auto_usage_threshold" | "auto_usage_hard" | "auto_estimate_threshold"`，但 [`docs/superpowers/specs/2026-04-24-context-compaction-design.md:264`](docs/superpowers/specs/2026-04-24-context-compaction-design.md:264) Summary Payload 示例写的是 `"auto_threshold"`。用户决定改 spec，不动代码。

**Files:**
- Modify: `docs/superpowers/specs/2026-04-24-context-compaction-design.md` payload 示例 + §触发策略 reason 描述

- [ ] **Step 1: 修 Summary Payload 示例**

打开 spec 第 252-265 行那段 JSON：

```json
{
  "summary_version": "context_compaction_v1",
  "source_seq_start": 12,
  ...
  "reason": "auto_threshold"
}
```

把 `"reason": "auto_threshold"` 改为：

```json
  "reason": "auto_usage_threshold"
```

- [ ] **Step 2: 在 §触发策略 章节加一段 reason 命名规则说明**

在 [spec §触发策略 (line ~143)](docs/superpowers/specs/2026-04-24-context-compaction-design.md:143) 列出三条规则后追加一段：

```markdown
对应 `summary.payload.reason` 字段取值（自动触发统一加 `auto_` 前缀）：

| 触发档 | reason 值 |
|--------|-----------|
| usage soft | `auto_usage_threshold` |
| usage hard | `auto_usage_hard` |
| estimate | `auto_estimate_threshold` |
| 手动触发 | `manual` |
```

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/specs/2026-04-24-context-compaction-design.md
git commit -m "$(cat <<'EOF'
docs(spec): 上下文压缩 reason 字段对齐实现命名

- Summary Payload 示例从 auto_threshold 改为 auto_usage_threshold
- §触发策略 增加 reason 取值表，含 auto_/manual 命名规范

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: agents/memory binding 路由显式拒绝 DELETE `__default__`

**背景：** [`sebastian/gateway/routes/agents.py:154-165`](sebastian/gateway/routes/agents.py:154) 的 `clear_agent_binding` 通过 `agent_type != ORCHESTRATOR_AGENT_TYPE and agent_type not in agent_registry` 隐式 404 屏蔽了 `__default__`。memory binding 路由同理。spec §API 设计明确要求 `__default__` 不能 DELETE，需要显式 guard 防止未来 agent_type 注册改动导致漏洞。

**Files:**
- Modify: `sebastian/gateway/routes/agents.py:154-165`
- Test: `tests/unit/gateway/routes/test_agents_binding.py`（如不存在则放在 `tests/integration/gateway/test_llm_bindings.py`，先确认）

- [ ] **Step 1: 定位现有 binding 路由测试文件**

Run:
```bash
ls tests/unit/gateway/routes/ tests/integration/gateway/ 2>&1 | grep -iE "binding|llm|agent"
```
Expected: 找到现有 binding 路由测试文件位置。如果没有，新建 `tests/integration/gateway/test_default_binding_delete_guard.py`。

- [ ] **Step 2: 写失败测试**

在选定文件追加：

```python
async def test_delete_default_agent_binding_returns_400(client, auth_headers):
    """DELETE /api/v1/agents/__default__/llm-binding 必须显式拒绝。"""
    resp = await client.delete(
        "/api/v1/agents/__default__/llm-binding", headers=auth_headers
    )
    assert resp.status_code == 400
    assert "__default__" in resp.json()["detail"]
```

- [ ] **Step 3: 跑测试验证 fail**

Run:
```bash
pytest tests/integration/gateway/test_default_binding_delete_guard.py::test_delete_default_agent_binding_returns_400 -v
```
Expected: FAIL（当前是 404，不是 400）。

- [ ] **Step 4: 在 `clear_agent_binding` 顶部加 guard**

修改 [`sebastian/gateway/routes/agents.py:154-165`](sebastian/gateway/routes/agents.py:154)：

```python
@router.delete("/agents/{agent_type}/llm-binding", status_code=204)
async def clear_agent_binding(
    agent_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    if agent_type == "__default__":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete __default__ binding; PUT a new value instead.",
        )

    if agent_type != ORCHESTRATOR_AGENT_TYPE and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    await state.llm_registry.clear_binding(agent_type)
    return Response(status_code=204)
```

- [ ] **Step 5: 跑测试验证 pass**

Run:
```bash
pytest tests/integration/gateway/test_default_binding_delete_guard.py -v
```
Expected: PASS。

- [ ] **Step 6: 跑相关回归**

Run:
```bash
pytest tests/integration/gateway/ tests/unit/gateway/ -v
```
Expected: 全 PASS（确认未破坏其它 binding 路由）。

- [ ] **Step 7: 提交**

```bash
git add sebastian/gateway/routes/agents.py tests/integration/gateway/test_default_binding_delete_guard.py
git commit -m "$(cat <<'EOF'
fix(gateway): 显式拒绝 DELETE __default__ binding

之前依赖 agent_registry 不含 __default__ 的隐式 404；将来若有
代码把 __default__ 注册为 agent_type，就会绕过保护清空默认绑定。
显式 400 + 文案防御。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 删除 Android 旧 Provider 链路

**背景：** Android 端 `Provider` / `ProviderDto` / `/llm-providers` 路由调用是 LLM 重构遗留，注释 "kept until UI migration in Task 7"，Task 7 已完成。当前症状：用户每次进 Settings 页都会触发 `GET /api/v1/llm-providers` 404 报错（[`SettingsViewModel.kt:71`](ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt:71) `init` 调 `loadProviders()`）。`ProviderPickerDialog` 已无 screen 引用，可安全删除。

**Files:**
- Delete: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/ProviderPickerDialog.kt`
- Delete: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/Provider.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt:67-78`（删 4 个 `/llm-providers` 端点）
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/ProviderDto.kt`（删旧 `ProviderDto` / `ProviderListResponse`）
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt:11,17-22`（删旧接口方法）
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt:35-102`（删 `_providers` / `currentProvider` / `getProviders` / `createProvider` / `updateProvider` / `deleteProvider` / `setDefaultProvider` / `providersFlow`）
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt:7,23,26,55-57,64-65,71,88-118`（删 import / state / combine / loadProviders / deleteProvider / setDefaultProvider）
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/SettingsViewModelTest.kt`（删旧 test、删 mock setup）

- [ ] **Step 1: 删 ProviderPickerDialog（无引用）**

Run:
```bash
rm ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/ProviderPickerDialog.kt
```

- [ ] **Step 2: 删 Provider.kt model**

先确认 import 来源都将被清理（后续 step 处理）。Run:
```bash
rm ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/Provider.kt
```

- [ ] **Step 3: 修剪 ApiService.kt**

打开 [`ApiService.kt:67-78`](ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt:67)，删除以下整段：

```kotlin
    // Providers
    @GET("api/v1/llm-providers")
    suspend fun getProviders(): ProviderListResponse

    @POST("api/v1/llm-providers")
    suspend fun createProvider(@Body body: ProviderDto): ProviderDto

    @PUT("api/v1/llm-providers/{id}")
    suspend fun updateProvider(@Path("id") id: String, @Body body: Map<String, @JvmSuppressWildcards Any>): ProviderDto

    @DELETE("api/v1/llm-providers/{id}")
    suspend fun deleteProvider(@Path("id") id: String)
```

同时检查文件顶部 import，删除所有未再被引用的 `ProviderDto` / `ProviderListResponse` import（IDE 报红即可定位；CLI 阶段可暂留，后续 build 失败再回头处理）。

- [ ] **Step 4: 修剪 ProviderDto.kt**

打开 [`ProviderDto.kt`](ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/ProviderDto.kt)，删除带 "Legacy" 注释的旧 `data class ProviderDto` 和 `data class ProviderListResponse` 及其辅助方法（`toDomain()` 等只有它们用的）。保留新的 LLM Account / Catalog / Binding / CustomModel DTO。

- [ ] **Step 5: 修剪 SettingsRepository 接口**

打开 [`SettingsRepository.kt`](ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt)，删除以下行：

```kotlin
    val currentProvider: Flow<Provider?>
    fun providersFlow(): Flow<List<Provider>>
    suspend fun getProviders(): Result<List<Provider>>
    suspend fun createProvider(name: String, type: String, baseUrl: String?, apiKey: String?, model: String?, thinkingCapability: String?, isDefault: Boolean): Result<Provider>
    suspend fun updateProvider(id: String, name: String, type: String, baseUrl: String?, apiKey: String?, model: String?, thinkingCapability: String?, isDefault: Boolean): Result<Provider>
    suspend fun deleteProvider(id: String): Result<Unit>
    suspend fun setDefaultProvider(id: String): Result<Unit>
```

并删除残留的 `import com.sebastian.android.data.model.Provider`（顶部 wildcard `data.model.*` 可保留，但要确认其它仍被引用的类型；若仅 Provider 用 wildcard 则改成显式 import）。

- [ ] **Step 6: 修剪 SettingsRepositoryImpl**

打开 [`SettingsRepositoryImpl.kt`](ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt)，删除：

- 第 35 行 `private val _providers = MutableStateFlow<List<Provider>>(emptyList())`
- 第 37-39 行 `override val currentProvider: Flow<Provider?>`
- 第 41 行 `override fun providersFlow()`
- 第 46-50 行 `override suspend fun getProviders()`
- 第 52-61 行 `override suspend fun createProvider(...)`
- 第 63-83 行 `override suspend fun updateProvider(...)`
- 第 85-88 行 `override suspend fun deleteProvider(...)`
- 第 90-102 行 `override suspend fun setDefaultProvider(...)`

`dataStore.saveActiveProviderId(id)` 调用如不再被使用，连带 `SettingsDataStore` 中的对应方法可一并清理（可选；如有他处使用则保留）。

- [ ] **Step 7: 修剪 SettingsViewModel**

打开 [`SettingsViewModel.kt`](ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt)：

1. 删 import：第 7 行 `import com.sebastian.android.data.model.Provider`
2. `SettingsUiState` 中删第 23 行 `val providers: List<Provider>` 和第 26 行 `val currentProvider: Provider?`
3. `init { ... combine(...) }` 把 `repository.providersFlow()` / `repository.currentProvider` 两条 flow 移除，并把 `args[2]` / `args[3]` 的赋值删除，`combine` 收 3 个参数：

```kotlin
    init {
        viewModelScope.launch {
            combine(
                repository.serverUrl,
                repository.theme,
                repository.isLoggedIn,
            ) { args ->
                @Suppress("UNCHECKED_CAST")
                _uiState.update {
                    it.copy(
                        serverUrl = args[0] as String,
                        theme = args[1] as String,
                        isLoggedIn = args[2] as Boolean,
                    )
                }
            }.collect {}
        }
        loadLlmCatalog()
        loadLlmAccounts()
    }
```

4. 删第 88-118 行 `loadProviders()` / `deleteProvider()` / `setDefaultProvider()` 三个方法。

- [ ] **Step 8: 修剪 SettingsViewModelTest**

打开 [`SettingsViewModelTest.kt`](ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/SettingsViewModelTest.kt)：

1. 删 import 第 4-5 行 `Provider` 和 `ThinkingCapability`（如果 ThinkingCapability 别处不用）
2. `setup()` 中删除 `providersFlow` / `currentProviderFlow` 字段、对应 `whenever(...).thenReturn(...)` mock，以及 `repository.getProviders()` 的 mock
3. 删除 test：`providers list reflects repository flow`、`deleteProvider removes from list on success`、`deleteProvider propagates error to uiState on failure`

精简后保留的测试：`initial state has empty serverUrl`、`serverUrl updates when flow emits`、`saveServerUrl calls repository`。

- [ ] **Step 9: 编译 Android 模块**

Run:
```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin 2>&1 | tail -40
```
Expected: BUILD SUCCESSFUL（如有 unresolved reference，回到 step 3-8 检查漏删）。

- [ ] **Step 10: 跑 Android 单测**

Run:
```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.SettingsViewModelTest" 2>&1 | tail -30
```
Expected: 3 个保留 test PASS。

> 注：用户已配置"Android 不自动安装"原则，跑完单测即收手，不需要 `expo run:android` 或装 APK。

- [ ] **Step 11: 提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/ProviderDto.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/SettingsViewModelTest.kt
# 已删除文件 Git 自动识别
git add -u ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/Provider.kt \
           ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/ProviderPickerDialog.kt
git commit -m "$(cat <<'EOF'
refactor(android): 删除旧 LLM Provider 链路

LLM Catalog/Account/Binding 重构后，旧 Provider 模型与 /llm-providers
路由已无后端实现，但 SettingsViewModel.init 仍调 loadProviders() 触发
404。本次删除：
- Provider data model、ProviderPickerDialog（无 screen 引用）
- ApiService 的 4 个 /llm-providers 端点
- SettingsRepository / Impl 的 7 个旧 Provider 方法
- SettingsViewModel 的 providers/currentProvider state 与相关方法
- SettingsViewModelTest 中 3 个 Provider 相关用例
- 旧 ProviderDto / ProviderListResponse

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 删除 `scripts/re_encrypt_api_keys.py`

**背景：** [`scripts/re_encrypt_api_keys.py:115`](scripts/re_encrypt_api_keys.py:115) `from sebastian.store.models import LLMProviderRecord` 引用已删 ORM 类，运行必 ImportError；脚本逻辑（轮换 secret.key 后重加密 `llm_providers.api_key_enc`）与新 schema 完全不匹配（新表叫 `llm_accounts.api_key_enc`，加密机制相同但脚本未适配）。当前没有用户在跑 secret.key 轮换，且文档无任何指引该脚本，决定删除。如未来需要轮换工具可基于新 schema 重写。

**Files:**
- Delete: `scripts/re_encrypt_api_keys.py`

- [ ] **Step 1: 确认无引用**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian
grep -rn "re_encrypt_api_keys" --include="*.py" --include="*.md" --include="*.sh" --include="*.yml" 2>&1 || echo "no refs"
```
Expected: 仅匹配 `scripts/re_encrypt_api_keys.py` 自身或 `no refs`。如出现其它引用（README / CI），先在该处把引用一并清理。

- [ ] **Step 2: 删除脚本**

Run:
```bash
rm scripts/re_encrypt_api_keys.py
```

- [ ] **Step 3: 提交**

```bash
git add -u scripts/re_encrypt_api_keys.py
git commit -m "$(cat <<'EOF'
chore(scripts): 删除已失效的 re_encrypt_api_keys.py

LLM Provider 重构后，该脚本仍 import 已删除的 LLMProviderRecord
并操作不存在的 llm_providers 表，运行必 ImportError。如未来需要
secret.key 轮换工具，可基于新 llm_accounts schema 重写。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 修 `sebastian/llm/README.md` 过时注释

**背景：** [`sebastian/llm/README.md:97`](sebastian/llm/README.md:97) 写「`TokenEstimator`（尚未实现）兜底」，实际 `TokenEstimator` 已在 [`sebastian/context/estimator.py`](sebastian/context/estimator.py) 完整实现。

**Files:**
- Modify: `sebastian/llm/README.md:97`

- [ ] **Step 1: 替换过时句子**

把第 97 行：

```markdown
- 若 Provider 未返回 usage（如本地模型或旧版 API），`TokenUsage` 为 `None`；后续 Token 估算由 `TokenEstimator`（尚未实现）兜底。
```

改为：

```markdown
- 若 Provider 未返回 usage（如本地模型或旧版 API），`TokenUsage` 为 `None`；此时压缩调度器会调用 `sebastian.context.estimator.TokenEstimator` 兜底估算。
```

- [ ] **Step 2: 提交**

```bash
git add sebastian/llm/README.md
git commit -m "$(cat <<'EOF'
docs(llm): 修 README TokenEstimator 已实现的过时注释

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 新建 `sebastian/context/README.md` 并补 `sebastian/README.md` 模块树

**背景：** `sebastian/context/` 包含 5 个文件、数百行核心逻辑，但既无 README 也未在 `sebastian/README.md` 顶层目录树和模块说明中出现，违反 CLAUDE.md "每个模块有 README" 原则。

**Files:**
- Create: `sebastian/context/README.md`
- Modify: `sebastian/README.md`（结构树 + 模块说明 + 修改导航三处）

- [ ] **Step 1: 写 `sebastian/context/README.md`**

新建文件 `sebastian/context/README.md`，内容：

```markdown
# Context Compaction Module

> 上级：[Sebastian Backend](../README.md)

负责 **session 短期上下文的运行时压缩**：当长 session 接近模型上下文窗口时，把较旧的 timeline items 压缩为 `context_summary`，同时通过 `archived=true` 保留完整审计历史。

## 文件职责

| 文件 | 职责 |
|------|------|
| `usage.py` | `TokenUsage` dataclass 与 provider usage 归一化辅助 |
| `estimator.py` | `TokenEstimator` 本地兜底估算器（英文/中文/messages 结构） |
| `token_meter.py` | `ContextTokenMeter` 阈值判断（usage 0.70/0.85、estimate 0.65） |
| `compaction.py` | `SessionContextCompactionWorker` + `TurnEndCompactionScheduler` |
| `prompts.py` | context summary prompt（Markdown 7-section handoff） |

## 关键流程

1. **Provider usage 优先**：每次 `ProviderCallEnd` 携带 `TokenUsage`，由 `ContextTokenMeter` 判断是否超阈值。
2. **本地估算兜底**：缺失 usage 时调用 `TokenEstimator.estimate_messages_tokens()`。
3. **per-turn 模型窗口**：`TurnEndCompactionScheduler` 通过 `context_window_resolver(agent_type)` 调用 `LLMProviderRegistry.get_provider(agent_type).context_window_tokens` 动态解析阈值，不再硬编码 200k。
4. **后台异步压缩**：`TurnDone` 持久化后 `asyncio.create_task` 后台执行，不阻塞 stream。
5. **`context_compactor` 可绑定**：summary 生成走 `get_provider("context_compactor")`，无专属绑定时 fallback 到 `__default__`。

## 触发档与 reason

| 档位 | 阈值 | summary.payload.reason |
|------|------|------------------------|
| usage soft | input_tokens >= window * 0.70 | `auto_usage_threshold` |
| usage hard | input_tokens >= window * 0.85 | `auto_usage_hard` |
| estimate | estimated_tokens >= window * 0.65 | `auto_estimate_threshold` |
| 手动 | API `POST /sessions/{id}/compact` | `manual` |

## 范围选择

- `retain_recent_exchanges = 8`（最近 8 个用户交互保留原文）
- `min_compactable_items = 12`、`min_source_tokens = 8000`（dry_run 与 manual 豁免后者）
- exchange 优先用 `exchange_id/exchange_index`；旧数据按 `user_message` 边界回退
- 不完整 tool chain（缺 `tool_result`）跳过
- 已有 `context_summary` 不再二次压缩

## 修改导航

| 修改场景 | 入口 |
|----------|------|
| 调阈值或 retain 窗口 | `compaction.py` 顶部常量 |
| 改 summary prompt | `prompts.py` |
| 新增 provider usage 字段 | `usage.py` `TokenUsage` |
| 调本地估算精度 | `estimator.py` |
| API 改动 | `sebastian/gateway/routes/sessions.py` 的 `compact` / `compaction/status` |
| 原子 archive 流程 | `sebastian/store/session_timeline.py:compact_range` |

## 相关 Spec

- `docs/superpowers/specs/2026-04-24-context-compaction-design.md`
- `docs/superpowers/specs/2026-04-25-llm-catalog-account-model-binding-design.md` §上下文压缩接入
```

- [ ] **Step 2: 在 `sebastian/README.md` 顶层结构树插入 `context/`**

打开 [`sebastian/README.md:24-52`](sebastian/README.md:24)，在 `├── config/` 之后、`├── core/` 之前插入：

```text
├── context/        → context/README.md
```

让目录树按字母序保持。

- [ ] **Step 3: 在「模块说明」章节为 `context/` 增加条目**

在 [`sebastian/README.md`](sebastian/README.md) 模块说明区，紧跟 `### core/` 之前（或 `### llm/` 之后，取决于现有顺序）插入：

```markdown
### `context/`

session 短期上下文的运行时压缩，包含 token usage 归一化、估算器、阈值判断、压缩 worker 与 prompt。详见 [context/README.md](context/README.md)。

- `usage.py`：`TokenUsage` 与 provider usage 归一化
- `estimator.py`：本地兜底 token 估算
- `token_meter.py`：阈值判断
- `compaction.py`：压缩 worker + turn 后调度器
- `prompts.py`：summary prompt

适合在以下场景进入：

- 调整压缩触发阈值或 retain 窗口
- 修改 summary prompt 结构
- 新增 provider usage 字段
```

- [ ] **Step 4: 在「常见修改导航表」中加入 context 行**

在 [`sebastian/README.md` line ~210-225](sebastian/README.md:210) 表格里插入一行：

```markdown
| 修改上下文压缩阈值 / summary prompt | [context/README.md](context/README.md) |
```

- [ ] **Step 5: 提交**

```bash
git add sebastian/context/README.md sebastian/README.md
git commit -m "$(cat <<'EOF'
docs: 补 context 模块 README 与顶层目录树索引

- 新增 sebastian/context/README.md，描述 5 个文件职责、触发档、
  reason 取值表、范围选择规则与修改导航
- sebastian/README.md 顶层结构树补 context/ 行
- 模块说明区新增 context/ 章节
- 修改导航表新增上下文压缩入口

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 收尾验证 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`（`[Unreleased]` 段补条目）

- [ ] **Step 1: 全后端测试**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian
ruff check sebastian/ tests/ scripts/ 2>&1 | tail -20
ruff format --check sebastian/ tests/ 2>&1 | tail -10
mypy sebastian/ 2>&1 | tail -20
pytest tests/unit/llm/ tests/integration/gateway/ tests/unit/context/ -q 2>&1 | tail -20
```
Expected: 全部 PASS / clean。

- [ ] **Step 2: Android 编译 + 单测复跑**

Run:
```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin :app:testDebugUnitTest 2>&1 | tail -20
```
Expected: BUILD SUCCESSFUL，单测 PASS。

- [ ] **Step 3: 更新 CHANGELOG `[Unreleased]`**

打开 [`CHANGELOG.md`](CHANGELOG.md)，在 `[Unreleased]` 段下加 `### Fixed` 与 `### Removed`（如已存在则合并）：

```markdown
### Fixed
- LLM Catalog: zhipu provider 单测断言对齐 JSON 实际值（display_name "Zhi Pu Coding" + 3 个模型）
- Gateway: `DELETE /api/v1/agents/__default__/llm-binding` 显式返回 400，防止默认绑定被清空
- Android: Settings 页不再调用已删除的 `/llm-providers` 路由（之前每次进入触发 404）
- Docs: `sebastian/llm/README.md` TokenEstimator 已实现，移除"尚未实现"过时注释
- Docs: 上下文压缩 spec 中 summary payload `reason` 示例对齐实现命名（`auto_usage_threshold` 等）

### Removed
- Android 旧 `Provider` data model、`ProviderPickerDialog` 与 `/llm-providers` Retrofit 端点
- `scripts/re_encrypt_api_keys.py`（依赖已删除的 `LLMProviderRecord`）

### Added
- `sebastian/context/README.md` 模块文档
- `sebastian/README.md` 顶层目录树与模块说明补 `context/` 条目
```

- [ ] **Step 4: 提交 + 创建 PR**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(changelog): 记录 LLM/Context 联合审计修复

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

git push -u origin HEAD

gh pr create --base main --title "fix: LLM Catalog × Context Compaction 联合审计修复" --body "$(cat <<'EOF'
## Summary

针对 LLM Catalog/Account/Binding 重构与 Context Compaction 落地后的联合审计，修复 8 处问题：
- CI 必红：zhipu catalog 单测与 JSON 不一致
- 运行时报错：Android Settings 页调已删除路由
- 安全：DELETE __default__ binding 隐式 404 改显式 400
- 遗留物：Android 旧 Provider 链路、re_encrypt_api_keys.py
- 文档：context 模块 README、过时注释、spec reason 命名

详见 docs/superpowers/plans/2026-04-25-llm-context-followup-fixes.md。

## Test plan

- [x] `pytest tests/unit/llm/ tests/integration/gateway/ tests/unit/context/`
- [x] `ruff check / format --check / mypy`
- [x] `./gradlew :app:compileDebugKotlin :app:testDebugUnitTest`
- [x] 手动验证 Settings 页不再 404（用户在主线复测）

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage**：本计划 Task 1-7 一一对应审计报告 §二必修问题 + §三遗留物 + §四偏离的"立即修 + 本 PR 内清理"两批；§六（resolved 字段、asyncio task hold、tool exchange field 风险）与 §七（缺失测试用例）已在 Goal 范围声明中显式排除，归属下一个 PR。
- **Placeholder scan**：所有 step 含具体代码块、文件路径、行号、命令、期望结果，无 TBD / 占位符。
- **Type consistency**：`SettingsRepository.providersFlow()` 删除后，`SettingsRepositoryImpl` / `SettingsViewModel` / `SettingsViewModelTest` 三处都同步删除调用，符号名一致。`__default__` 字符串在 Task 3 测试与实现中拼写一致。
- **风险点**：Task 4 step 6 删 `setDefaultProvider` 时连带 `dataStore.saveActiveProviderId()`，需确认是否还有他处使用；step 中已注明"如有他处使用则保留"。
