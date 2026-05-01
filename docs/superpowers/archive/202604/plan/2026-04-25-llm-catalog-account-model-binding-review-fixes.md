# LLM Catalog Binding Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the review findings in the LLM catalog/account/model binding feature so invalid LLM configuration cannot be saved and Android binding screens do not clear or misroute user settings.

**Architecture:** Keep the existing Catalog -> Account -> Binding architecture. Backend routes become the validation boundary for account/model/binding writes; registry coercion becomes a defensive runtime normalization layer. Android uses new account/model binding DTOs end-to-end, routes memory component bindings to their dedicated endpoints, and loads custom account models from `/llm-accounts/{id}/models`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy async, pytest/pytest-asyncio, Kotlin, Jetpack Compose, Retrofit/Moshi, Hilt, Gradle.

---

## Source Context

- Spec: `docs/superpowers/specs/2026-04-25-llm-catalog-account-model-binding-design.md`
- Existing implementation plan: `docs/superpowers/plans/2026-04-25-llm-catalog-account-model-binding.md`
- Backend module README: `sebastian/llm/README.md`, `sebastian/gateway/README.md`, `sebastian/gateway/routes/README.md`
- Android module README: `ui/mobile-android/README.md`

## Review Findings Covered

- Finding 1: Opening normal Agent binding editor clears existing binding.
- Finding 2: Memory component binding editor reads/writes Agent binding endpoints.
- Finding 3: Custom account models never appear in binding editor.
- Finding 4: Custom account `base_url_override` can be cleared.
- Finding 5: Custom account `provider_type` is not validated.
- Finding 6: Custom model `thinking_capability` / `thinking_format` are not validated; invalid effort can pass through.

## File Map

Backend:

- Modify `sebastian/gateway/routes/llm_accounts.py`: add validation helpers; validate custom account update and custom model thinking fields; optionally expose cached catalog helper.
- Modify `sebastian/llm/registry.py`: make `_coerce_thinking()` reject or normalize invalid effort values defensively.
- Test `tests/unit/llm/test_llm_accounts_route.py`: route-level tests for new validation behavior.
- Test `tests/integration/gateway/test_llm_accounts_api.py`: integration tests for invalid custom account/model writes.
- Test `tests/unit/test_llm_registry_resolved.py`: `_coerce_thinking()` value domain tests.
- Optional docs: `sebastian/gateway/routes/README.md`, `sebastian/llm/README.md`.

Android data/API:

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`: memory binding PUT uses `SetBindingRequest`; add GET/PUT methods that return new account-based DTOs.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt`: keep legacy DTO only for still-legacy call sites, but add memory binding DTO conversion to `AgentBinding`.
- Inspect/modify memory component list DTOs in `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/*.kt`: ensure list display reads `account_id` / `model_id` rather than legacy `provider_id`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt`: add account-based `getAgentBinding()`, `getMemoryBinding()`, `setMemoryBinding()` APIs.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt`: wire the new APIs to correct endpoints.

Android ViewModel/UI:

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt`: load via GET, save normal/default/memory paths correctly, load custom account models, avoid default binding empty PUT.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt` only if the page needs to disable save/clear controls for default binding or show custom model loading state.
- Test under `ui/mobile-android/app/src/test/` if ViewModel test infrastructure exists. If no existing ViewModel tests are present, verify with `./gradlew :app:compileDebugKotlin` and add focused repository DTO tests only if the project already has Android unit test patterns.

Docs and validation:

- Modify `CHANGELOG.md` `[Unreleased]`.
- Modify relevant READMEs if behavior or endpoints are documented.

## Task 1: Backend Validation Boundary

**Files:**
- Modify: `sebastian/gateway/routes/llm_accounts.py`
- Modify: `sebastian/llm/registry.py`
- Test: `tests/unit/llm/test_llm_accounts_route.py`
- Test: `tests/integration/gateway/test_llm_accounts_api.py`
- Test: `tests/unit/test_llm_registry_resolved.py`

- [ ] **Step 1: Write failing route tests for custom account validation**

Add tests to `tests/unit/llm/test_llm_accounts_route.py`:

```python
def test_create_account_custom_rejects_unsupported_provider_type(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Gemini-ish",
            "catalog_provider_id": "custom",
            "api_key": "sk-test",
            "provider_type": "gemini",
            "base_url_override": "https://example.com/v1",
        },
    )

    assert resp.status_code == 400
    assert "provider_type" in resp.json()["detail"]
```

Add an update test using the existing `mock_registry` fixture:

```python
def test_update_custom_account_rejects_null_base_url(
    client: TestClient,
    mock_registry: MagicMock,
) -> None:
    custom = _make_account(
        id="custom-1",
        catalog_provider_id="custom",
        provider_type="openai",
        base_url_override="https://custom.example.com/v1",
    )
    mock_registry.get_account = AsyncMock(return_value=custom)

    resp = client.put(
        "/api/v1/llm-accounts/custom-1",
        json={"base_url_override": None},
    )

    assert resp.status_code == 400
    assert "base_url_override" in resp.json()["detail"]
    mock_registry.update_account.assert_not_awaited()
```

- [ ] **Step 2: Run the new route tests and verify they fail**

Run:

```bash
pytest tests/unit/llm/test_llm_accounts_route.py::test_create_account_custom_rejects_unsupported_provider_type tests/unit/llm/test_llm_accounts_route.py::test_update_custom_account_rejects_null_base_url -v
```

Expected: FAIL because provider type is accepted and update does not fetch the account before allowing null base URL.

- [ ] **Step 3: Add backend validation helpers**

In `sebastian/gateway/routes/llm_accounts.py`, import catalog constants:

```python
from sebastian.llm.catalog.loader import (
    SUPPORTED_PROVIDER_TYPES,
    SUPPORTED_THINKING_CAPABILITIES,
    SUPPORTED_THINKING_FORMATS,
)
```

Add helpers near `_validate_base_url()`:

```python
def _validate_provider_type(value: str) -> str:
    if value not in SUPPORTED_PROVIDER_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_PROVIDER_TYPES))
        raise HTTPException(
            status_code=400,
            detail=f"provider_type must be one of: {allowed}",
        )
    return value


def _validate_thinking_capability(value: str | None) -> str | None:
    if value not in SUPPORTED_THINKING_CAPABILITIES:
        allowed = ", ".join(sorted(v for v in SUPPORTED_THINKING_CAPABILITIES if v is not None))
        raise HTTPException(
            status_code=400,
            detail=f"thinking_capability must be one of: {allowed}",
        )
    return value


def _validate_thinking_format(value: str | None) -> str | None:
    if value not in SUPPORTED_THINKING_FORMATS:
        allowed = ", ".join(sorted(v for v in SUPPORTED_THINKING_FORMATS if v is not None))
        raise HTTPException(
            status_code=400,
            detail=f"thinking_format must be one of: {allowed}",
        )
    return value
```

Use `_validate_provider_type(body.provider_type)` when creating custom accounts.

- [ ] **Step 4: Make custom account update reject empty base URL**

In `update_account()`, fetch the account before building updates:

```python
record = await state.llm_registry.get_account(account_id)
if record is None:
    raise HTTPException(status_code=404, detail="Account not found")
```

Then replace the current null branch:

```python
if "base_url_override" in data:
    val = data["base_url_override"]
    if val is not None:
        updates["base_url_override"] = _validate_base_url(val)
    elif record.catalog_provider_id == "custom":
        raise HTTPException(
            status_code=400,
            detail="base_url_override is required for custom providers",
        )
    else:
        updates["base_url_override"] = None
```

Leave built-in accounts able to clear `base_url_override` so they fall back to catalog base URL.

- [ ] **Step 5: Run account validation tests and verify they pass**

Run:

```bash
pytest tests/unit/llm/test_llm_accounts_route.py::test_create_account_custom_rejects_unsupported_provider_type tests/unit/llm/test_llm_accounts_route.py::test_update_custom_account_rejects_null_base_url -v
```

Expected: PASS.

- [ ] **Step 6: Write failing tests for custom model thinking field validation**

Add route tests:

```python
def test_create_custom_model_rejects_invalid_thinking_capability(
    client: TestClient,
    mock_registry: MagicMock,
) -> None:
    custom = _make_account(catalog_provider_id="custom", provider_type="openai")
    mock_registry.get_account = AsyncMock(return_value=custom)

    resp = client.post(
        "/api/v1/llm-accounts/acc1/models",
        json={
            "model_id": "bad-model",
            "display_name": "Bad Model",
            "context_window_tokens": 128000,
            "thinking_capability": "telepathy",
        },
    )

    assert resp.status_code == 400
    assert "thinking_capability" in resp.json()["detail"]


def test_create_custom_model_rejects_invalid_thinking_format(
    client: TestClient,
    mock_registry: MagicMock,
) -> None:
    custom = _make_account(catalog_provider_id="custom", provider_type="openai")
    mock_registry.get_account = AsyncMock(return_value=custom)

    resp = client.post(
        "/api/v1/llm-accounts/acc1/models",
        json={
            "model_id": "bad-model",
            "display_name": "Bad Model",
            "context_window_tokens": 128000,
            "thinking_format": "xml_cloud",
        },
    )

    assert resp.status_code == 400
    assert "thinking_format" in resp.json()["detail"]
```

Add an update test for invalid thinking field using the fake DB fixture pattern already in this file if it can return a model record. If the unit fixture cannot easily model this path, put the update validation test in the integration file in Step 9.

- [ ] **Step 7: Run the custom model validation tests and verify they fail**

Run:

```bash
pytest tests/unit/llm/test_llm_accounts_route.py::test_create_custom_model_rejects_invalid_thinking_capability tests/unit/llm/test_llm_accounts_route.py::test_create_custom_model_rejects_invalid_thinking_format -v
```

Expected: FAIL because the invalid fields are currently accepted.

- [ ] **Step 8: Validate custom model thinking fields in create/update**

In `create_custom_model()`, compute validated values before constructing `LLMCustomModelRecord`:

```python
thinking_capability = _validate_thinking_capability(body.thinking_capability)
thinking_format = _validate_thinking_format(body.thinking_format)
```

Use those variables in the record.

In `update_custom_model()`, validate only provided fields:

```python
if "thinking_capability" in data:
    data["thinking_capability"] = _validate_thinking_capability(data["thinking_capability"])
if "thinking_format" in data:
    data["thinking_format"] = _validate_thinking_format(data["thinking_format"])
```

- [ ] **Step 9: Add integration tests for invalid writes**

Add to `tests/integration/gateway/test_llm_accounts_api.py`:

```python
def test_create_custom_account_rejects_invalid_provider_type(client) -> None:
    http_client, token = client
    resp = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Bad Custom",
            "catalog_provider_id": "custom",
            "api_key": "sk-test",
            "provider_type": "gemini",
            "base_url_override": "https://custom.example.com/v1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_update_custom_account_rejects_null_base_url(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Custom",
            "catalog_provider_id": "custom",
            "api_key": "sk-test",
            "provider_type": "openai",
            "base_url_override": "https://custom.example.com/v1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = create.json()["id"]

    resp = http_client.put(
        f"/api/v1/llm-accounts/{aid}",
        json={"base_url_override": None},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400
```

Also add create/update custom model invalid thinking tests. Use a custom account created in the test, then POST/PUT invalid values and assert `400`.

- [ ] **Step 10: Harden `_coerce_thinking()` with value-domain normalization**

Add tests to `tests/unit/test_llm_registry_resolved.py`:

```python
def test_coerce_thinking_rejects_invalid_effort_for_effort_capability() -> None:
    assert _coerce_thinking("ultra", "effort") is None


def test_coerce_thinking_rejects_invalid_effort_for_adaptive_capability() -> None:
    assert _coerce_thinking("ultra", "adaptive") is None
```

Then update `sebastian/llm/registry.py`:

```python
def _coerce_thinking(effort: str | None, capability: str | None) -> str | None:
    if capability in ("none", "always_on", None):
        return None
    if capability == "toggle":
        if effort in (None, "off"):
            return "off"
        if effort in {"on", "low", "medium", "high", "max"}:
            return "on"
        return None
    if capability == "effort":
        if effort in (None, "off"):
            return None
        if effort in ("max", "on"):
            return "high"
        if effort in {"low", "medium", "high"}:
            return effort
        return None
    if capability == "adaptive":
        if effort in (None, "off"):
            return None
        if effort in {"low", "medium", "high", "max"}:
            return effort
        return None
    return None
```

This keeps runtime defensive. API write paths reject invalid custom model thinking metadata; `_coerce_thinking()` covers any stale or manually inserted invalid effort values without passing them into provider adapters.

- [ ] **Step 11: Run backend focused tests**

Run:

```bash
pytest tests/unit/llm/test_llm_accounts_route.py tests/integration/gateway/test_llm_accounts_api.py tests/unit/test_llm_registry_resolved.py -v
```

Expected: PASS.

- [ ] **Step 12: Commit backend validation fix**

Stage exact files:

```bash
git add sebastian/gateway/routes/llm_accounts.py sebastian/llm/registry.py tests/unit/llm/test_llm_accounts_route.py tests/integration/gateway/test_llm_accounts_api.py tests/unit/test_llm_registry_resolved.py
git commit -m "fix(llm): 校验 account 与 custom model 配置" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 2: Android Repository and Endpoint Contract

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MemoryComponentDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt`

- [ ] **Step 1: Inspect whether Android unit tests already cover repositories**

Run:

```bash
rg -n "AgentRepositoryImpl|AgentBindingEditorViewModel|SettingsRepositoryImpl" ui/mobile-android/app/src/test ui/mobile-android/app/src/androidTest
```

Expected: Either existing tests are found, or no tests exist. If tests exist, add focused failing tests before implementation. If no tests exist, continue with compile verification in this task and ViewModel behavior tests only where infrastructure is present.

- [ ] **Step 2: Replace account-based Agent binding repository APIs**

In `AgentRepository.kt`, add account-based getters and memory setters:

```kotlin
suspend fun getAgentBinding(agentType: String): Result<AgentBinding>
suspend fun getMemoryBinding(componentType: String): Result<AgentBinding>
suspend fun setMemoryBinding(
    componentType: String,
    accountId: String?,
    modelId: String?,
    thinkingEffort: String?,
): Result<AgentBinding>
```

Keep legacy methods only if other screens still use them. Do not remove legacy methods in this task unless `rg` proves they are unused.

- [ ] **Step 3: Update Retrofit methods for memory component binding**

In `ApiService.kt`, change memory binding methods to use the new DTOs:

```kotlin
@GET("api/v1/memory/components/{componentType}/llm-binding")
suspend fun getMemoryComponentBindingV2(
    @Path("componentType") componentType: String,
): MemoryComponentBindingDto

@PUT("api/v1/memory/components/{componentType}/llm-binding")
suspend fun setMemoryComponentBindingV2(
    @Path("componentType") componentType: String,
    @Body body: SetBindingRequest,
): MemoryComponentBindingDto
```

If the existing method names are reused, update all call sites in the same commit. Avoid having two Retrofit methods with identical method/path/signature ambiguity if it makes call sites confusing.

- [ ] **Step 4: Add conversion from memory DTO to `AgentBinding`**

In `MemoryComponentDto.kt`, update `MemoryComponentBindingDto` so it contains the account-based fields returned by the backend:

```kotlin
@JsonClass(generateAdapter = true)
data class MemoryComponentBindingDto(
    @param:Json(name = "component_type") val componentType: String? = null,
    @param:Json(name = "account_id") val accountId: String? = null,
    @param:Json(name = "model_id") val modelId: String? = null,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
)
```

Add conversion either in `MemoryComponentDto.kt` next to the DTO or in `AgentBindingDto.kt` if that is where binding converters are grouped locally:

```kotlin
fun MemoryComponentBindingDto.toAgentBinding(componentTypeFallback: String) = AgentBinding(
    agentType = componentType ?: componentTypeFallback,
    accountId = accountId,
    modelId = modelId,
    thinkingEffort = thinkingEffort,
    resolved = null,
)
```

Remove or quarantine old `providerId` usage for this endpoint.

- [ ] **Step 5: Check memory component list DTO display path**

Search:

```bash
rg -n "MemoryComponent|providerId|provider_id|account_id|model_id" ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto ui/mobile-android/app/src/main/java/com/sebastian/android/data/model ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt
```

If `MemoryComponentDto` or its `toDomain()` still reads `provider_id`, update it to read nested `binding.account_id`, `binding.model_id`, and `binding.thinking_effort` from the backend response. Expected behavior: the Settings binding list shows existing memory component bindings instead of rendering them as unbound.

- [ ] **Step 6: Wire repository implementation**

In `AgentRepositoryImpl.kt`:

```kotlin
override suspend fun getAgentBinding(agentType: String): Result<AgentBinding> = runCatching {
    withContext(dispatcher) {
        apiService.getAgentBindingV2(agentType).toDomain()
    }
}

override suspend fun getMemoryBinding(componentType: String): Result<AgentBinding> = runCatching {
    withContext(dispatcher) {
        apiService.getMemoryComponentBindingV2(componentType).toAgentBinding(componentType)
    }
}

override suspend fun setMemoryBinding(
    componentType: String,
    accountId: String?,
    modelId: String?,
    thinkingEffort: String?,
): Result<AgentBinding> = runCatching {
    withContext(dispatcher) {
        apiService.setMemoryComponentBindingV2(
            componentType,
            SetBindingRequest(
                accountId = accountId,
                modelId = modelId,
                thinkingEffort = thinkingEffort,
            ),
        ).toAgentBinding(componentType)
    }
}
```

Also add a Retrofit GET method for normal agent V2 if missing:

```kotlin
@GET("api/v1/agents/{agentType}/llm-binding")
suspend fun getAgentBindingV2(@Path("agentType") agentType: String): AgentBindingDto
```

- [ ] **Step 7: Run Android compile**

Run:

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin
```

Expected: PASS. If it fails, fix only the type/call-site errors caused by this task.

- [ ] **Step 8: Commit Android repository contract fix**

Stage exact files:

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MemoryComponentDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt
git commit -m "fix(android): 对齐 LLM 绑定接口契约" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 3: Android Binding Editor Behavior

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt` if clear/save controls need state guards.
- Test: existing Android ViewModel tests if present; otherwise compile plus manual inspection.

- [ ] **Step 1: Add or identify tests for destructive load behavior**

If ViewModel unit test infrastructure exists, add a fake `AgentRepository` test:

```kotlin
@Test
fun loadNormalAgentGetsBindingWithoutClearing() = runTest {
    val repo = FakeAgentRepository(
        binding = AgentBinding(
            agentType = "forge",
            accountId = "acc-1",
            modelId = "model-1",
            thinkingEffort = null,
            resolved = null,
        ),
    )

    val vm = newVm(agentType = "forge", isMemoryComponent = false, agentRepository = repo)
    vm.load()
    advanceUntilIdle()

    assertEquals(1, repo.getAgentBindingCalls)
    assertEquals(0, repo.setAgentBindingCalls)
}
```

If no infrastructure exists, record this as a manual verification item and continue.

- [ ] **Step 2: Fix normal Agent load path**

In `AgentBindingEditorViewModel.load()`, replace the non-default/non-memory `bindingD` branch:

```kotlin
val bindingD = when {
    isDefault -> async { settingsRepository.getDefaultBinding() }
    isMemoryComponent -> async { agentRepository.getMemoryBinding(agentType) }
    else -> async { agentRepository.getAgentBinding(agentType) }
}
```

Delete the `runCatching { agentRepository.setAgentBinding(agentType, null, null, null) }` load path entirely.

- [ ] **Step 3: Route memory component saves to memory endpoints**

Add a private save helper so `schedulePut()` and `onCleared()` share the same routing:

```kotlin
private suspend fun persistBinding(s: EditorUiState): Result<AgentBinding> {
    val effort = s.thinkingEffort.toApiString()
    return when {
        s.isDefault -> settingsRepository.setDefaultBinding(
            s.selectedAccount?.id ?: return Result.failure(IllegalStateException("Default model requires an account")),
            s.selectedModel?.id ?: return Result.failure(IllegalStateException("Default model requires a model")),
            effort,
        )
        isMemoryComponent -> agentRepository.setMemoryBinding(
            s.agentType,
            s.selectedAccount?.id,
            s.selectedModel?.id,
            effort,
        )
        else -> agentRepository.setAgentBinding(
            s.agentType,
            s.selectedAccount?.id,
            s.selectedModel?.id,
            effort,
        )
    }
}
```

Use `persistBinding(s)` in both `schedulePut()` and `onCleared()`.

For explicit clear actions, prefer the existing DELETE endpoints instead of saving a null PUT:

```kotlin
private suspend fun clearPersistedBinding(s: EditorUiState): Result<Unit> {
    return when {
        s.isDefault -> Result.failure(IllegalStateException("Default model cannot be cleared"))
        isMemoryComponent -> agentRepository.clearMemoryComponentBinding(s.agentType)
        else -> agentRepository.clearBinding(s.agentType)
    }
}
```

Update `clearBinding()` so it clears local state and calls `clearPersistedBinding()` for normal Agent and memory component bindings. Do not expose clear for the default binding.

- [ ] **Step 4: Prevent default binding empty PUT**

Before saving, guard the default binding case:

```kotlin
if (s.isDefault && (s.selectedAccount == null || s.selectedModel == null)) {
    _uiState.update { it.copy(isSaving = false) }
    _events.tryEmit(EditorEvent.Snackbar("Default model requires an account and model"))
    return@launch
}
```

Do not call `settingsRepository.setDefaultBinding("", "", effort)`.

If the UI has a clear binding action visible for default binding, hide or disable it in `AgentBindingEditorPage.kt`.

- [ ] **Step 5: Prevent partial binding PUTs during account/model selection**

Add a helper that distinguishes complete, clear, and partial states:

```kotlin
private fun isPersistableSelection(s: EditorUiState): Boolean {
    val hasAccount = s.selectedAccount != null
    val hasModel = s.selectedModel != null
    return hasAccount && hasModel
}
```

Use it at the start of `schedulePut()` after reading `val s = _uiState.value`:

```kotlin
if (!isPersistableSelection(s)) {
    putPending = false
    _uiState.update { it.copy(isSaving = false) }
    return@launch
}
```

This is required because changing account intentionally sets `selectedModel = null` while the user chooses the next model. That intermediate state must not be persisted as `account_id != null, model_id = null`. Full clear state is handled by `clearPersistedBinding()` instead of this autosave path.

Use the same guard in `onCleared()` before launching the application-scope save.

- [ ] **Step 6: Load models for custom accounts**

Change model resolution to be suspend-aware. Replace `resolveModels()` with a built-in-only helper:

```kotlin
private fun resolveCatalogModels(
    account: LlmAccount,
    catalog: List<CatalogProvider>,
): List<ModelOption> {
    val catalogProvider = catalog.firstOrNull { it.id == account.catalogProviderId } ?: return emptyList()
    return catalogProvider.models.map { m ->
        ModelOption(
            id = m.id,
            displayName = m.displayName,
            contextWindowTokens = m.contextWindowTokens,
            thinkingCapability = m.thinkingCapability,
        )
    }
}
```

Add suspend helper:

```kotlin
private suspend fun resolveModelsForAccount(
    account: LlmAccount,
    catalog: List<CatalogProvider>,
): List<ModelOption> {
    if (account.catalogProviderId != "custom") {
        return resolveCatalogModels(account, catalog)
    }
    return settingsRepository.getCustomModels(account.id).getOrElse { emptyList() }.map { m ->
        ModelOption(
            id = m.modelId,
            displayName = m.displayName,
            contextWindowTokens = m.contextWindowTokens,
            thinkingCapability = m.thinkingCapability,
        )
    }
}
```

Use this helper in `load()` and `selectAccount()`. Because `selectAccount()` is currently non-suspend, wrap its work in `viewModelScope.launch`:

```kotlin
fun selectAccount(accountId: String?) {
    viewModelScope.launch {
        val prev = _uiState.value
        val account = prev.accounts.firstOrNull { it.id == accountId }
        val models = if (account != null) {
            resolveModelsForAccount(account, prev.catalogProviders)
        } else {
            emptyList()
        }
        _uiState.update {
            it.copy(
                selectedAccount = account,
                availableModels = models,
                selectedModel = null,
                thinkingEffort = ThinkingEffort.OFF,
            )
        }
    }
}
```

Do not call `schedulePut()` from `selectAccount()` after setting `selectedModel = null`. Persist only after `selectModel()` has produced a complete account/model pair, or after an explicit `clearBinding()` has produced a full clear state.

Delete the unused `loadCustomModels()` method after confirming there are no call sites.

- [ ] **Step 7: Handle custom account with zero models**

If a custom account returns no models, keep `selectedModel = null` and avoid saving a partial binding. Add a user-facing snackbar or error:

```kotlin
if (account?.catalogProviderId == "custom" && models.isEmpty()) {
    _events.tryEmit(EditorEvent.Snackbar("Add a custom model before binding this account"))
}
```

Do not send `account_id` with null `model_id`, because backend correctly rejects partial binding state.

- [ ] **Step 8: Add or update ViewModel test for partial selection if infrastructure exists**

If ViewModel test infrastructure exists, add:

```kotlin
@Test
fun selectAccountDoesNotPersistPartialBinding() = runTest {
    val repo = FakeAgentRepository()
    val settings = FakeSettingsRepository(
        accounts = listOf(LlmAccount("acc-1", "Custom", "custom", "openai", "https://x.test/v1", true)),
        customModels = listOf(CustomModel("cm-1", "acc-1", "m1", "M1", 128000, ThinkingCapability.NONE, null)),
    )
    val vm = newVm("forge", false, repo, settings)
    vm.load()
    advanceUntilIdle()

    vm.selectAccount("acc-1")
    advanceUntilIdle()

    assertEquals(0, repo.setAgentBindingCalls)
}
```

If no test infrastructure exists, record this exact manual assertion in the final verification notes after compiling.

- [ ] **Step 9: Run Android compile**

Run:

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin
```

Expected: PASS.

- [ ] **Step 10: Run Android unit tests if available**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest
```

Expected: PASS. If failures are unrelated to this task, document them before proceeding.

- [ ] **Step 11: Commit Android binding editor fix**

Stage exact files:

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt
git commit -m "fix(android): 修复 LLM 绑定编辑器保存路径" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Only include `AgentBindingEditorPage.kt` if it actually changed. If Android ViewModel tests were added or updated, include their exact test file paths in this same commit.

## Task 4: Docs, Regression Checks, and Final Integration

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `sebastian/gateway/routes/README.md` if binding/account validation details changed.
- Modify: `sebastian/llm/README.md` if `_coerce_thinking()` or custom model validation rules are documented.
- Modify: `ui/mobile-android/README.md` if Settings binding behavior or custom model binding flow is documented.

- [ ] **Step 1: Update CHANGELOG**

Add under `## [Unreleased]`:

```markdown
### Fixed
- 修复 LLM 绑定编辑页打开时误清空 Agent 绑定的问题。
- 修复 Memory component 模型绑定读写到错误接口的问题。
- 修复自定义 LLM account/model 可保存非法配置并在运行时失败的问题。
```

If `### Fixed` already exists, append these bullets there.

- [ ] **Step 2: Update READMEs touched by behavior**

Check:

```bash
rg -n "llm-binding|llm-accounts|custom model|provider_type|thinking_capability" sebastian/llm/README.md sebastian/gateway/routes/README.md ui/mobile-android/README.md
```

Update only stale sections. Do not rewrite unrelated docs.

- [ ] **Step 3: Run backend focused regression**

Run:

```bash
pytest tests/unit/llm/test_llm_accounts_route.py tests/integration/gateway/test_llm_accounts_api.py tests/unit/test_llm_registry_resolved.py tests/unit/gateway/test_agents_route.py tests/unit/test_memory_components_route.py -v
```

Expected: PASS.

- [ ] **Step 4: Run backend lint for touched Python files**

Run:

```bash
ruff check sebastian/gateway/routes/llm_accounts.py sebastian/llm/registry.py tests/unit/llm/test_llm_accounts_route.py tests/integration/gateway/test_llm_accounts_api.py tests/unit/test_llm_registry_resolved.py
```

Expected: PASS.

- [ ] **Step 5: Run Android verification**

Run:

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin
./gradlew :app:testDebugUnitTest
```

Expected: PASS.

- [ ] **Step 6: Run full project status check**

Run:

```bash
git status --short
```

Expected: only intended files are modified.

- [ ] **Step 7: Commit docs and final verification updates**

Stage exact files that changed:

```bash
git add CHANGELOG.md sebastian/gateway/routes/README.md sebastian/llm/README.md ui/mobile-android/README.md
git commit -m "docs: 记录 LLM 绑定修复" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Only stage README files that were actually modified.

## Final Acceptance Criteria

- Opening a normal Agent binding editor performs a GET-only load and does not mutate the backend.
- Memory component binding editor uses `/memory/components/{component_type}/llm-binding` for GET/PUT/DELETE.
- Selecting a custom account in the binding editor loads custom models from `/llm-accounts/{account_id}/models`.
- Default binding cannot be saved with empty account/model IDs.
- Custom account creation rejects unsupported `provider_type`.
- Custom account update rejects clearing `base_url_override` for `catalog_provider_id="custom"`.
- Custom model create/update rejects unsupported `thinking_capability` and `thinking_format`.
- Runtime `_coerce_thinking()` does not pass through invalid effort values.
- Backend focused pytest commands pass.
- Android `:app:compileDebugKotlin` passes.
- Android `:app:testDebugUnitTest` passes, or any unrelated pre-existing failures are documented with exact failure output.
