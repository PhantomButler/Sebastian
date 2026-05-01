# LLM Catalog Account Model Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current one-row-per-provider/model LLM configuration with a local catalog, user LLM accounts, per-model metadata, and default/agent bindings that carry `account_id + model_id`.

**Architecture:** Built-in provider/model metadata lives in `sebastian/llm/catalog/builtin_providers.json` and is loaded through a small catalog module. SQLite stores only user accounts, custom model metadata, and bindings; `LLMProviderRegistry` resolves `agent_type -> binding -> account + model spec -> ResolvedProvider`. Android keeps the current two settings entry points but renames/re-scopes them to LLM connections and Default/Agent model bindings.

**Tech Stack:** Python 3.12, SQLAlchemy async, FastAPI, Pydantic, pytest/pytest-asyncio, Kotlin, Jetpack Compose, Retrofit/Moshi, Hilt, Gradle.

---

## Source Spec

- `docs/superpowers/specs/2026-04-25-llm-catalog-account-model-binding-design.md`

## File Map

Backend catalog:

- Create `sebastian/llm/catalog/__init__.py`: package exports.
- Create `sebastian/llm/catalog/builtin_providers.json`: local provider/model catalog.
- Create `sebastian/llm/catalog/loader.py`: parse and validate catalog JSON into typed specs.
- Test `tests/unit/llm/test_llm_catalog.py`.

Backend persistence and registry:

- Modify `sebastian/store/models.py`: replace `LLMProviderRecord` with `LLMAccountRecord`, add `LLMCustomModelRecord`, change `AgentLLMBindingRecord`.
- Modify `sebastian/store/database.py`: remove old `llm_providers` idempotent patches; add only needed new-table safe invariants if required.
- Modify `sebastian/llm/registry.py`: resolve accounts and models, return expanded `ResolvedProvider`, expose account/custom model/binding helpers.
- Test `tests/unit/llm/test_llm_registry.py`, `tests/unit/test_llm_registry_resolved.py`, `tests/unit/store/test_agent_llm_binding_model.py`.

Backend routes:

- Delete or replace `sebastian/gateway/routes/llm_providers.py` with account/catalog routes. Prefer renaming to `sebastian/gateway/routes/llm_accounts.py` if app registration is easy to update.
- Modify `sebastian/gateway/app.py`: include new route module, construct compaction scheduler with registry-aware window lookup.
- Modify `sebastian/gateway/routes/agents.py`: binding DTOs use `account_id + model_id`.
- Modify `sebastian/gateway/routes/memory_components.py`: same binding DTOs for memory components.
- Create or modify route tests: `tests/unit/llm/test_llm_accounts_route.py`, `tests/integration/gateway/test_llm_accounts_api.py`, update existing provider tests or remove old expectations.

Context compaction:

- Modify `sebastian/context/compaction.py`: scheduler resolves per-turn context window instead of using one `ContextTokenMeter`.
- Modify `sebastian/core/compaction_hook.py` only if signature needs registry/window data.
- Test `tests/unit/context/test_compaction.py` and `tests/unit/core/test_base_agent_provider.py`.

Android data layer:

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/Provider.kt`: replace/extend provider domain with account/catalog/model/binding domain types. Consider renaming file to `LlmModels.kt` only if Kotlin package imports remain simple.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/ProviderDto.kt`: replace provider DTOs with catalog/account/model DTOs.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt`: use `account_id`, `model_id`, `resolved`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`: add `/llm-catalog`, `/llm-accounts`, custom model, default binding endpoints; update existing binding requests.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt` and `SettingsRepositoryImpl.kt`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt` and `AgentRepositoryImpl.kt`.
- Test under `ui/mobile-android/app/src/test/` where existing repository/viewmodel tests live.

Android UI/viewmodels:

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt`: rename settings rows.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt`: become LLM account list.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt`: become account form with built-in vs custom flow.
- Create `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/CustomModelsPage.kt`: list/add/edit/delete custom account models.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ProviderFormViewModel.kt`: account form state and validation.
- Create `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/CustomModelsViewModel.kt`: custom model CRUD state and validation.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt` and `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`: route to custom model management.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt`: load catalog/accounts.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt`: include top default model row.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt`: account picker + model picker + context window display.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt` and `AgentBindingEditorViewModel.kt`.

Docs:

- Modify `docs/architecture/spec/core/llm-provider.md`.
- Modify `sebastian/llm/README.md`, `sebastian/store/README.md`, `sebastian/gateway/routes/README.md`.
- Modify `ui/mobile-android/README.md`, `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/README.md`, and related data/viewmodel READMEs if touched.
- Modify `CHANGELOG.md` `[Unreleased]`.

## Task 1: Backend Catalog Loader

**Files:**
- Create: `sebastian/llm/catalog/__init__.py`
- Create: `sebastian/llm/catalog/builtin_providers.json`
- Create: `sebastian/llm/catalog/loader.py`
- Test: `tests/unit/llm/test_llm_catalog.py`

- [ ] **Step 1: Write failing catalog loader tests**

Create `tests/unit/llm/test_llm_catalog.py` with tests for happy path, duplicate provider IDs, duplicate model IDs, invalid provider type, invalid thinking fields, and invalid context window.

Example skeleton:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sebastian.llm.catalog.loader import CatalogValidationError, load_catalog_from_path


def _write_catalog(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_catalog_returns_provider_and_model_specs(tmp_path: Path) -> None:
    path = _write_catalog(
        tmp_path,
        {
            "version": 1,
            "providers": [
                {
                    "id": "openai",
                    "display_name": "OpenAI",
                    "provider_type": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "models": [
                        {
                            "id": "gpt-test",
                            "display_name": "GPT Test",
                            "context_window_tokens": 128000,
                            "thinking_capability": "none",
                            "thinking_format": None,
                        }
                    ],
                }
            ],
        },
    )

    catalog = load_catalog_from_path(path)

    provider = catalog.get_provider("openai")
    assert provider.display_name == "OpenAI"
    model = catalog.get_model("openai", "gpt-test")
    assert model.context_window_tokens == 128000
```

- [ ] **Step 2: Run catalog tests to verify they fail**

Run: `pytest tests/unit/llm/test_llm_catalog.py -v`

Expected: FAIL because `sebastian.llm.catalog.loader` does not exist.

- [ ] **Step 3: Implement catalog dataclasses and validation**

Create `sebastian/llm/catalog/loader.py` with:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

SUPPORTED_PROVIDER_TYPES = {"anthropic", "openai"}
SUPPORTED_THINKING_CAPABILITIES = {"none", "toggle", "effort", "adaptive", "always_on", None}
SUPPORTED_THINKING_FORMATS = {"reasoning_content", "think_tags", None}
MIN_CONTEXT_WINDOW = 1_000
MAX_CONTEXT_WINDOW = 10_000_000


class CatalogValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LLMModelSpec:
    id: str
    display_name: str
    context_window_tokens: int
    thinking_capability: str | None
    thinking_format: str | None


@dataclass(frozen=True, slots=True)
class LLMProviderSpec:
    id: str
    display_name: str
    provider_type: str
    base_url: str
    models: tuple[LLMModelSpec, ...]


@dataclass(frozen=True, slots=True)
class LLMCatalog:
    version: int
    providers: tuple[LLMProviderSpec, ...]

    def get_provider(self, provider_id: str) -> LLMProviderSpec:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise KeyError(provider_id)

    def get_model(self, provider_id: str, model_id: str) -> LLMModelSpec:
        provider = self.get_provider(provider_id)
        for model in provider.models:
            if model.id == model_id:
                return model
        raise KeyError(f"{provider_id}/{model_id}")
```

Then implement `load_catalog_from_path(path: Path) -> LLMCatalog` and `load_builtin_catalog() -> LLMCatalog`. Keep validation strict and deterministic.

- [ ] **Step 4: Add initial built-in catalog JSON**

Create `sebastian/llm/catalog/builtin_providers.json` with a small but useful first list:

```json
{
  "version": 1,
  "providers": [
    {
      "id": "anthropic",
      "display_name": "Anthropic",
      "provider_type": "anthropic",
      "base_url": "https://api.anthropic.com",
      "models": [
        {
          "id": "claude-sonnet-4-5",
          "display_name": "Claude Sonnet 4.5",
          "context_window_tokens": 200000,
          "thinking_capability": "adaptive",
          "thinking_format": null
        }
      ]
    },
    {
      "id": "openai",
      "display_name": "OpenAI",
      "provider_type": "openai",
      "base_url": "https://api.openai.com/v1",
      "models": [
        {
          "id": "gpt-4.1",
          "display_name": "GPT-4.1",
          "context_window_tokens": 1047576,
          "thinking_capability": "none",
          "thinking_format": null
        }
      ]
    },
    {
      "id": "deepseek",
      "display_name": "DeepSeek",
      "provider_type": "openai",
      "base_url": "https://api.deepseek.com/v1",
      "models": [
        {
          "id": "deepseek-chat",
          "display_name": "DeepSeek Chat",
          "context_window_tokens": 128000,
          "thinking_capability": "none",
          "thinking_format": null
        },
        {
          "id": "deepseek-reasoner",
          "display_name": "DeepSeek Reasoner",
          "context_window_tokens": 128000,
          "thinking_capability": "always_on",
          "thinking_format": "reasoning_content"
        }
      ]
    },
    {
      "id": "zhipu",
      "display_name": "智谱",
      "provider_type": "openai",
      "base_url": "https://open.bigmodel.cn/api/paas/v4",
      "models": [
        {
          "id": "glm-4.5",
          "display_name": "GLM-4.5",
          "context_window_tokens": 128000,
          "thinking_capability": "effort",
          "thinking_format": null
        }
      ]
    }
  ]
}
```

If implementation-time docs show a catalog value is wrong, prefer conservative metadata and document the source in a short JSON-adjacent comment is not possible; instead add a README note later. Do not browse unless the user asks to update exact current provider/model data.

- [ ] **Step 5: Run catalog tests**

Run: `pytest tests/unit/llm/test_llm_catalog.py -v`

Expected: PASS.

- [ ] **Step 6: Commit catalog loader**

```bash
git add sebastian/llm/catalog/__init__.py sebastian/llm/catalog/loader.py sebastian/llm/catalog/builtin_providers.json tests/unit/llm/test_llm_catalog.py
git commit -m "feat(llm): 添加内置模型 catalog"
```

## Task 2: Replace LLM Provider Persistence Schema

**Files:**
- Modify: `sebastian/store/models.py`
- Modify: `sebastian/store/database.py`
- Test: `tests/unit/store/test_agent_llm_binding_model.py`
- Test: `tests/unit/llm/test_llm_provider_store.py` or replace with `tests/unit/llm/test_llm_account_store.py`

- [ ] **Step 1: Write failing model/schema tests**

Update or create tests that assert:

- `LLMAccountRecord.__tablename__ == "llm_accounts"`
- `LLMCustomModelRecord.__tablename__ == "llm_custom_models"`
- `AgentLLMBindingRecord` has `account_id`, `model_id`, `thinking_effort`
- There is no `provider_id` dependency in binding tests
- A test DB `create_all` can create all tables

Example:

```python
from __future__ import annotations

from sebastian.store.models import AgentLLMBindingRecord, LLMAccountRecord, LLMCustomModelRecord


def test_llm_account_model_tables_are_named() -> None:
    assert LLMAccountRecord.__tablename__ == "llm_accounts"
    assert LLMCustomModelRecord.__tablename__ == "llm_custom_models"
    assert AgentLLMBindingRecord.__tablename__ == "agent_llm_bindings"


def test_agent_binding_uses_account_and_model_columns() -> None:
    columns = AgentLLMBindingRecord.__table__.columns
    assert "account_id" in columns
    assert "model_id" in columns
    assert "provider_id" not in columns
```

- [ ] **Step 2: Run schema tests to verify they fail**

Run: `pytest tests/unit/store/test_agent_llm_binding_model.py tests/unit/llm/test_llm_provider_store.py -v`

Expected: FAIL because old models still exist.

- [ ] **Step 3: Replace ORM models**

In `sebastian/store/models.py`:

- Remove `LLMProviderRecord`.
- Add `LLMAccountRecord`.
- Add `LLMCustomModelRecord`.
- Update `AgentLLMBindingRecord`.

Use `ondelete="RESTRICT"` or no cascade for `AgentLLMBindingRecord.account_id`; API will block referenced deletes with `409`. Use cascade from `LLMCustomModelRecord.account_id` to `llm_accounts.id` for unreferenced custom account cleanup.

Recommended constraints:

```python
class LLMCustomModelRecord(Base):
    __table_args__ = (
        UniqueConstraint("account_id", "model_id", name="uq_llm_custom_models_account_model"),
    )
```

- [ ] **Step 4: Clean idempotent migrations**

In `sebastian/store/database.py`, remove old `("llm_providers", "thinking_capability", ...)` patch. Keep unrelated memory/session patches. Do not add product migration from `llm_providers`.

- [ ] **Step 5: Run schema tests**

Run: `pytest tests/unit/store/test_agent_llm_binding_model.py tests/unit/llm/test_llm_provider_store.py -v`

Expected: PASS after updating/removing old provider-store assertions.

- [ ] **Step 6: Commit schema replacement**

```bash
git add sebastian/store/models.py sebastian/store/database.py tests/unit/store/test_agent_llm_binding_model.py tests/unit/llm/test_llm_provider_store.py
git commit -m "refactor(store): 重写 LLM account 与模型绑定 schema"
```

## Task 3: Registry Resolves Account And Model Specs

**Files:**
- Modify: `sebastian/llm/registry.py`
- Test: `tests/unit/llm/test_llm_registry.py`
- Test: `tests/unit/test_llm_registry_resolved.py`

- [ ] **Step 1: Write failing registry tests**

Cover:

- `get_provider("forge")` uses explicit `agent_type` binding.
- `get_provider("forge")` falls back to `__default__`.
- Missing `__default__` raises `RuntimeError`.
- Built-in account model metadata comes from catalog.
- Custom account model metadata comes from `llm_custom_models`.
- `ResolvedProvider.context_window_tokens` is returned.
- `thinking_effort` is coerced by model capability, not account capability.

Example:

```python
async def test_get_provider_returns_context_window_from_catalog(db_session_factory):
    from sebastian.llm.crypto import encrypt
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.models import AgentLLMBindingRecord, LLMAccountRecord

    async with db_session_factory() as session:
        account = LLMAccountRecord(
            name="OpenAI",
            catalog_provider_id="openai",
            provider_type="openai",
            api_key_enc=encrypt("sk-test"),
            base_url_override=None,
        )
        session.add(account)
        await session.flush()
        session.add(
            AgentLLMBindingRecord(
                agent_type="__default__",
                account_id=account.id,
                model_id="gpt-4.1",
                thinking_effort="high",
            )
        )
        await session.commit()

    resolved = await LLMProviderRegistry(db_session_factory).get_provider("forge")

    assert resolved.model == "gpt-4.1"
    assert resolved.context_window_tokens == 1047576
    assert resolved.thinking_effort is None
```

- [ ] **Step 2: Run registry tests to verify they fail**

Run: `pytest tests/unit/llm/test_llm_registry.py tests/unit/test_llm_registry_resolved.py -v`

Expected: FAIL because registry still imports `LLMProviderRecord` and uses `provider_id`.

- [ ] **Step 3: Update `ResolvedProvider` and registry query flow**

In `sebastian/llm/registry.py`:

- Import `LLMAccountRecord`, `LLMCustomModelRecord`, catalog loader types.
- Add `DEFAULT_BINDING_AGENT_TYPE = "__default__"`.
- Expand `ResolvedProvider` fields.
- Replace default provider lookup with default binding lookup.
- Add helpers:
  - `get_account(account_id: str) -> LLMAccountRecord | None`
  - `list_accounts() -> list[LLMAccountRecord]`
  - `create_account(record: LLMAccountRecord) -> None`
  - `update_account(account_id: str, **kwargs: Any) -> LLMAccountRecord | None`
  - `delete_account(account_id: str) -> bool`
  - `set_binding(agent_type, account_id, model_id, thinking_effort)`
  - `get_model_spec(account, model_id)`
- Keep `_coerce_thinking` behavior consistent with existing tests and docs.

- [ ] **Step 4: Instantiate providers from accounts**

Replace `_instantiate(record: LLMProviderRecord)` with `_instantiate_account(account: LLMAccountRecord, model_spec: LLMModelSpec)`.

Rules:

- `effective_base_url = account.base_url_override or catalog_provider.base_url`
- For custom account, `base_url_override` must exist or registry raises configuration error.
- Anthropic receives `thinking_capability=model_spec.thinking_capability`.
- OpenAI-compatible receives `thinking_format=model_spec.thinking_format` and `thinking_capability=model_spec.thinking_capability`.

- [ ] **Step 5: Run registry tests**

Run: `pytest tests/unit/llm/test_llm_registry.py tests/unit/test_llm_registry_resolved.py -v`

Expected: PASS.

- [ ] **Step 6: Commit registry rewrite**

```bash
git add sebastian/llm/registry.py tests/unit/llm/test_llm_registry.py tests/unit/test_llm_registry_resolved.py
git commit -m "feat(llm): 按 account 与模型解析 provider"
```

## Task 4: LLM Catalog, Account, Custom Model, And Binding APIs

**Files:**
- Create/Modify: `sebastian/gateway/routes/llm_accounts.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/routes/agents.py`
- Modify: `sebastian/gateway/routes/memory_components.py`
- Test: `tests/unit/llm/test_llm_accounts_route.py`
- Test: `tests/integration/gateway/test_llm_accounts_api.py`
- Update: `tests/unit/gateway/test_agents_route.py`
- Update: `tests/unit/test_memory_components_route.py`
- Update: `tests/integration/test_agent_binding_api.py`
- Update: `tests/unit/llm/test_registry_bindings.py`
- Update/remove: `tests/unit/llm/test_llm_providers_route.py`
- Update/remove: `tests/integration/gateway/test_llm_providers_api.py`

- [ ] **Step 1: Write failing API route tests**

Add unit tests for pure route behavior where possible:

- POST built-in account accepts `catalog_provider_id + api_key`.
- POST custom account requires `provider_type + base_url_override`.
- PUT account rejects `api_key=""` and `api_key=None`.
- DELETE account returns `409` when any binding references it.
- DELETE custom model returns `409` when any binding references it.
- PUT custom model returns `409` when changing `model_id` while any binding references it.
- DELETE unreferenced custom account deletes its custom models.
- PUT default binding writes `__default__`.

- [ ] **Step 2: Run API tests to verify they fail**

Run: `pytest tests/unit/llm/test_llm_accounts_route.py tests/integration/gateway/test_llm_accounts_api.py -v`

Expected: FAIL because route module does not exist.

- [ ] **Step 3: Implement account/catalog routes**

Create `sebastian/gateway/routes/llm_accounts.py`.

Pydantic DTO guidance:

```python
class LLMAccountCreate(BaseModel):
    name: str
    catalog_provider_id: str
    api_key: str
    provider_type: str | None = None
    base_url_override: str | None = None


class LLMAccountUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    base_url_override: str | None = None
```

Validation:

- `catalog_provider_id != "custom"` must exist in catalog.
- `catalog_provider_id == "custom"` requires `provider_type` and `base_url_override`.
- `api_key` create must be non-empty.
- `api_key` update, if present, must be non-empty and not null.
- `base_url_override`, when present, must pass existing HTTP URL validation.

- [ ] **Step 4: Implement custom model routes**

In same route module:

- `GET /llm-accounts/{account_id}/models`
- `POST /llm-accounts/{account_id}/models`
- `PUT /llm-accounts/{account_id}/models/{model_record_id}`
- `DELETE /llm-accounts/{account_id}/models/{model_record_id}`

Rules:

- Reject custom model operations for non-custom account with `400`.
- Validate `context_window_tokens`.
- Enforce same-account unique `model_id`.
- DELETE referenced model returns `409`.
- PUT referenced model returns `409` if `model_id` changes; metadata-only updates remain allowed so display name, context window, thinking capability, and thinking format can be corrected without changing bindings.

- [ ] **Step 5: Implement catalog and default binding routes**

In `llm_accounts.py` or a small `llm_bindings.py` only if clearer:

- `GET /api/v1/llm-catalog`
- `GET /api/v1/llm-bindings/default`
- `PUT /api/v1/llm-bindings/default`

Default binding maps to `agent_type="__default__"`. DELETE is not supported.

- [ ] **Step 6: Update app route registration**

In `sebastian/gateway/app.py`, include the new route module and remove old `llm_providers` registration if present.

- [ ] **Step 7: Update agent and memory binding routes**

In `sebastian/gateway/routes/agents.py` and `sebastian/gateway/routes/memory_components.py`:

- Replace `provider_id` request/response fields with `account_id` and `model_id`.
- Validate binding target through registry/model resolution helper before saving.
- Existing DELETE remains clear override.
- Return resolved metadata for UI.

- [ ] **Step 8: Run API tests**

Run:

```bash
pytest \
  tests/unit/llm/test_llm_accounts_route.py \
  tests/integration/gateway/test_llm_accounts_api.py \
  tests/unit/gateway/test_agents_route.py \
  tests/unit/test_memory_components_route.py \
  tests/integration/test_agent_binding_api.py \
  tests/unit/llm/test_registry_bindings.py \
  tests/unit/llm/test_llm_providers_route.py \
  tests/integration/gateway/test_llm_providers_api.py \
  -v
```

Expected: PASS after old provider tests are updated or removed and all `provider_id` binding expectations become `account_id + model_id`.

- [ ] **Step 9: Commit API rewrite**

```bash
git add sebastian/gateway/routes/llm_accounts.py sebastian/gateway/app.py sebastian/gateway/routes/agents.py sebastian/gateway/routes/memory_components.py tests/unit/llm/test_llm_accounts_route.py tests/integration/gateway/test_llm_accounts_api.py tests/unit/gateway/test_agents_route.py tests/unit/test_memory_components_route.py tests/integration/test_agent_binding_api.py tests/unit/llm/test_registry_bindings.py tests/unit/llm/test_llm_providers_route.py tests/integration/gateway/test_llm_providers_api.py
git commit -m "feat(gateway): 提供 LLM account catalog 与绑定接口"
```

## Task 5: Context Compaction Uses Per-Model Context Window

**Files:**
- Modify: `sebastian/context/compaction.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/core/compaction_hook.py` only if needed
- Test: `tests/unit/context/test_compaction.py`
- Test: `tests/unit/core/test_base_agent_provider.py`

- [ ] **Step 1: Write failing compaction scheduler tests**

Add tests that prove:

- Scheduler calls registry for the current `agent_type`.
- A model with `context_window_tokens=10_000` compacts at the 70/65/85 percent thresholds.
- A model with `context_window_tokens=200_000` does not compact for the same token count.
- Registry failure is logged/swallowed by compaction scheduling path.

Use fake registry/resolved provider rather than a DB.

- [ ] **Step 2: Run compaction tests to verify they fail**

Run: `pytest tests/unit/context/test_compaction.py tests/unit/core/test_base_agent_provider.py -v`

Expected: FAIL because scheduler still receives a singleton token meter.

- [ ] **Step 3: Refactor `TurnEndCompactionScheduler`**

In `sebastian/context/compaction.py`, change constructor from `token_meter` injection to either:

- `llm_registry` injection, creating `ContextTokenMeter(context_window=resolved.context_window_tokens)` per call, or
- a small `context_window_resolver(agent_type) -> int` callable.

Prefer the callable if it keeps tests simple. In `gateway/app.py`, wire it to `llm_registry.get_provider(agent_type).context_window_tokens`.

- [ ] **Step 4: Preserve non-blocking behavior**

Keep the existing behavior:

- `maybe_schedule_after_turn()` decides quickly and does not block response streaming.
- Actual compaction still runs in `asyncio.create_task`.
- Any registry/compaction error logs a warning and does not fail the user turn.

- [ ] **Step 5: Run compaction tests**

Run: `pytest tests/unit/context/test_compaction.py tests/unit/core/test_base_agent_provider.py -v`

Expected: PASS.

- [ ] **Step 6: Commit context window integration**

```bash
git add sebastian/context/compaction.py sebastian/gateway/app.py sebastian/core/compaction_hook.py tests/unit/context/test_compaction.py tests/unit/core/test_base_agent_provider.py
git commit -m "feat(context): 按模型上下文窗口触发压缩"
```

## Task 6: Android Data Layer For Catalog, Accounts, Models, Bindings

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/Provider.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/ProviderDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt`
- Test: relevant files in `ui/mobile-android/app/src/test/`

- [ ] **Step 1: Write failing Kotlin DTO/domain tests**

Add or update tests to parse:

- Catalog response with provider/model specs.
- Account response with `has_api_key`.
- Binding response with `account_id`, `model_id`, and `resolved.context_window_tokens`.

If no existing DTO parser tests exist, create small Moshi adapter tests under `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/`.

- [ ] **Step 2: Run Android tests to verify they fail**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*Llm*'`

Expected: FAIL because DTOs do not exist.

- [ ] **Step 3: Add domain models**

In `Provider.kt` or a new `LlmModels.kt`, define:

```kotlin
data class LlmAccount(
    val id: String,
    val name: String,
    val catalogProviderId: String,
    val providerType: String,
    val baseUrlOverride: String?,
    val effectiveBaseUrl: String?,
    val hasApiKey: Boolean,
)

data class CatalogProvider(
    val id: String,
    val displayName: String,
    val providerType: String,
    val baseUrl: String,
    val models: List<CatalogModel>,
)

data class CatalogModel(
    val id: String,
    val displayName: String,
    val contextWindowTokens: Long,
    val thinkingCapability: ThinkingCapability,
    val thinkingFormat: String?,
)

data class CustomModel(
    val id: String,
    val accountId: String,
    val modelId: String,
    val displayName: String,
    val contextWindowTokens: Long,
    val thinkingCapability: ThinkingCapability,
    val thinkingFormat: String?,
)

data class ResolvedBinding(
    val accountName: String?,
    val providerDisplayName: String?,
    val modelDisplayName: String?,
    val contextWindowTokens: Long?,
    val thinkingCapability: ThinkingCapability?,
)

data class AgentBinding(
    val agentType: String,
    val accountId: String?,
    val modelId: String?,
    val thinkingEffort: String?,
    val resolved: ResolvedBinding?,
)
```

Keep existing `ThinkingCapability` and `ThinkingEffort` enums, but ensure `ThinkingCapability.fromString()` handles catalog values.

- [ ] **Step 4: Replace DTOs**

In `ProviderDto.kt` and `AgentBindingDto.kt`, add Moshi DTOs for:

- `LlmCatalogResponseDto`
- `CatalogProviderDto`
- `CatalogModelDto`
- `LlmAccountDto`
- `LlmAccountListResponseDto`
- `CustomModelDto`
- `SetBindingRequest(accountId, modelId, thinkingEffort)`
- `AgentBindingDto(accountId, modelId, thinkingEffort, resolved)`

- [ ] **Step 5: Update Retrofit API**

In `ApiService.kt`, add:

- `getLlmCatalog()`
- `getLlmAccounts()`
- `createLlmAccount(body)`
- `updateLlmAccount(accountId, body)`
- `deleteLlmAccount(accountId)`
- `getCustomModels(accountId)`
- `createCustomModel(accountId, body)`
- `updateCustomModel(accountId, modelRecordId, body)`
- `deleteCustomModel(accountId, modelRecordId)`
- `getDefaultBinding()`
- `setDefaultBinding(body)`

Update existing agent/memory binding methods to use new request DTO.

- [ ] **Step 6: Update repositories**

In `SettingsRepository` and `SettingsRepositoryImpl`, replace provider CRUD with account/catalog/custom model CRUD. Keep method names compatible only if it avoids broad UI churn; otherwise rename to account semantics and update callers in the next task.

In `AgentRepository` and `AgentRepositoryImpl`, change binding methods to accept `accountId: String?`, `modelId: String?`, `thinkingEffort`.

- [ ] **Step 7: Run Android data tests**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*Llm*'`

Expected: PASS.

- [ ] **Step 8: Commit Android data layer**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/Provider.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/ProviderDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt ui/mobile-android/app/src/test
git commit -m "feat(android): 接入 LLM catalog 与 account 数据层"
```

## Task 7: Android LLM Connections UI

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ProviderFormViewModel.kt`
- Test: related ViewModel tests under `ui/mobile-android/app/src/test/`

- [ ] **Step 1: Write failing ViewModel tests**

Cover:

- Built-in account form requires name + api key + catalog provider.
- Built-in account form does not require base URL.
- Custom account form requires provider type + base URL + api key.
- Empty API key update is rejected locally or passed to backend and surfaces error; prefer local validation for better UX.

- [ ] **Step 2: Run focused Android tests to verify they fail**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ProviderForm*' --tests '*Settings*'`

Expected: FAIL due old provider form state.

- [ ] **Step 3: Rename Settings row labels**

In `SettingsScreen.kt`:

- Change `模型与 Provider` to `LLM 连接` or `模型服务连接`.
- Change `Agent LLM Bindings` to `默认模型 / Agent 模型绑定`.
- Update subtitles to account/model language.

- [ ] **Step 4: Rework account list UI**

In `ProviderListPage.kt`, keep the route component name for now if route renaming is noisy, but change content:

- Title: `LLM 连接`
- Card fields: account name, catalog provider display name or Custom, API key configured state.
- Remove default badge.
- Swipe delete still works; backend `409` should show snackbar with clear message.

- [ ] **Step 5: Rework account form UI**

In `ProviderFormPage.kt`:

- First section: service selector from catalog plus `Custom`.
- Built-in service mode: name + API key only.
- Custom mode: name + provider type segmented control + base URL + API key.
- Do not show model field here.
- For edit mode, omit API key unless user enters a replacement.
- After successfully creating a custom account, navigate to that account's custom model management page so the connection can become bindable.

- [ ] **Step 6: Rework form ViewModel**

In `ProviderFormViewModel.kt`:

- Load catalog before rendering service choices.
- Track `catalogProviderId`, `providerType`, `baseUrlOverride`.
- Validate per mode.
- Call account repository methods.

- [ ] **Step 7: Run Android UI/ViewModel tests**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ProviderForm*' --tests '*Settings*'`

Expected: PASS.

- [ ] **Step 8: Commit LLM connections UI**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ProviderFormViewModel.kt ui/mobile-android/app/src/test
git commit -m "feat(android): 重做 LLM 连接设置"
```

## Task 8: Android Custom Model Management UI

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/CustomModelsPage.kt`
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/CustomModelsViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt`
- Test: related ViewModel tests under `ui/mobile-android/app/src/test/`

- [ ] **Step 1: Write failing custom model ViewModel tests**

Cover:

- Loading models for a custom account calls `getCustomModels(accountId)`.
- `modelId`, `displayName`, `contextWindowTokens`, and `thinkingCapability` are required.
- `contextWindowTokens` must be a positive integer within backend range.
- Built-in accounts cannot open custom model editing.
- Delete surfaces backend `409` as a snackbar/error state when a model is referenced by a binding.
- Editing `modelId` surfaces backend `409` when a model is referenced by a binding; metadata-only edits stay available.

- [ ] **Step 2: Run focused custom model tests to verify they fail**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*CustomModel*'`

Expected: FAIL because `CustomModelsViewModel` and page do not exist.

- [ ] **Step 3: Add route and navigation**

In `Route.kt`, add a route similar to:

```kotlin
@Serializable
data class SettingsCustomModels(val accountId: String) : Route()
```

In `MainActivity.kt`, register it and render `CustomModelsPage(accountId = route.accountId)`.

- [ ] **Step 4: Implement `CustomModelsViewModel`**

State should include:

- `accountId`
- `models: List<CustomModel>`
- form fields: `modelId`, `displayName`, `contextWindowTokens`, `thinkingCapability`, `thinkingFormat`
- loading/saving/error flags

Actions:

- `load(accountId)`
- `saveNewModel()`
- `updateModel(modelRecordId)`
- `deleteModel(modelRecordId)`
- `clearError()`

- [ ] **Step 5: Implement `CustomModelsPage`**

UI:

- Top app bar title `自定义模型`.
- List current custom models with model ID and context window.
- Add/edit form using `OutlinedTextField` for model ID/display/window, dropdown for thinking capability, dropdown or optional text field for thinking format.
- Delete action with confirmation.
- Empty state tells the user a custom connection needs at least one model before it can be selected in bindings.

- [ ] **Step 6: Link from LLM connection UI**

In `ProviderListPage.kt`, show a `模型` or `Manage models` action only for custom accounts.

In `ProviderFormPage.kt`, after creating a custom account, navigate to `SettingsCustomModels(accountId)` instead of immediately popping back.

- [ ] **Step 7: Run custom model UI tests**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*CustomModel*'`

Expected: PASS.

- [ ] **Step 8: Commit custom model UI**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/CustomModelsPage.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/CustomModelsViewModel.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt ui/mobile-android/app/src/test
git commit -m "feat(android): 管理自定义 LLM 模型"
```

## Task 9: Android Default And Agent Model Binding UI

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/ProviderPickerDialog.kt`
- Test: related ViewModel tests under `ui/mobile-android/app/src/test/`

- [ ] **Step 1: Write failing binding ViewModel tests**

Cover:

- Default binding row loads from `/llm-bindings/default`.
- Agent rows still load existing agents.
- Selecting an account populates models for that account.
- Switching account clears invalid model.
- Switching model coerces or resets effort.
- Context window text is exposed in UI state.

- [ ] **Step 2: Run focused binding tests to verify they fail**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*AgentBinding*'`

Expected: FAIL due old provider-only binding state.

- [ ] **Step 3: Update bindings list page**

In `AgentBindingsPage.kt`:

- Add a top row/card named `默认模型`.
- Route it to `AgentBindingEditorPage` with a stable default marker. Use existing route if possible: `agentType="__default__"` and a display-name override in UI state.
- Existing Sebastian/Sub-Agent/Memory component rows remain below.

- [ ] **Step 4: Update binding editor UI**

In `AgentBindingEditorPage.kt`:

- Replace provider picker with account picker.
- Add model picker after account selection.
- Show selected model context window: for example `Context window: 128,000 tokens`.
- Keep `EffortSlider`, but drive it from selected model capability.

- [ ] **Step 5: Update binding editor ViewModel**

In `AgentBindingEditorViewModel.kt`:

- Load accounts and catalog/custom model lists.
- Load default binding when `agentType == "__default__"`.
- For normal agent/memory component, load respective binding and fallback display metadata from default binding where needed.
- Save `accountId + modelId + thinkingEffort`.
- Prevent deleting/clearing default binding.

- [ ] **Step 6: Update picker component**

In `ProviderPickerDialog.kt`, either rename to `AccountPickerDialog.kt` or keep filename and change semantics. If renaming, update README and imports in the same task. The component should show account name and provider display name.

- [ ] **Step 7: Run binding UI tests**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*AgentBinding*'`

Expected: PASS.

- [ ] **Step 8: Commit binding UI**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/ProviderPickerDialog.kt ui/mobile-android/app/src/test
git commit -m "feat(android): 支持默认与 Agent 模型绑定"
```

## Task 10: Documentation And Changelog

**Files:**
- Modify: `docs/architecture/spec/core/llm-provider.md`
- Modify: `sebastian/llm/README.md`
- Modify: `sebastian/store/README.md`
- Modify: `sebastian/gateway/routes/README.md`
- Modify: `ui/mobile-android/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md` if data DTO/repository docs mention providers
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md` if provider form/binding docs mention old fields
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update architecture spec**

Update `docs/architecture/spec/core/llm-provider.md`:

- Version/date.
- Replace `LLMProviderRecord` with `LLMAccountRecord`, `LLMCustomModelRecord`, `AgentLLMBindingRecord(account_id, model_id)`.
- Add catalog section.
- Update registry resolution and `ResolvedProvider`.
- Mention context compaction window source.

- [ ] **Step 2: Update backend READMEs**

Update:

- `sebastian/llm/README.md`: catalog/account/registry entry points.
- `sebastian/store/README.md`: new tables and schema change guidance.
- `sebastian/gateway/routes/README.md`: new `/llm-catalog`, `/llm-accounts`, `/llm-bindings/default` routes and updated binding fields.

- [ ] **Step 3: Update Android READMEs**

Update:

- `ui/mobile-android/README.md`: Settings navigation text.
- `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/README.md`: LLM connection and default/agent model binding responsibilities.
- Data/viewmodel READMEs if old provider field list appears.

- [ ] **Step 4: Update CHANGELOG**

In `CHANGELOG.md` under `[Unreleased]`, add a user-facing `Changed` entry:

```markdown
- 重构 LLM 配置为内置模型 catalog、连接账号和默认/Agent 模型绑定，模型上下文窗口用于上下文压缩阈值判断。
```

- [ ] **Step 5: Commit docs**

```bash
git add docs/architecture/spec/core/llm-provider.md sebastian/llm/README.md sebastian/store/README.md sebastian/gateway/routes/README.md ui/mobile-android/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md CHANGELOG.md
git commit -m "docs: 更新 LLM catalog 与模型绑定文档"
```

## Task 11: Full Verification And Cleanup

**Files:**
- No planned source edits unless verification finds issues.

- [ ] **Step 1: Run backend targeted tests**

Run:

```bash
pytest \
  tests/unit/llm \
  tests/unit/gateway/test_agents_route.py \
  tests/unit/test_memory_components_route.py \
  tests/unit/context/test_compaction.py \
  tests/unit/core/test_base_agent_provider.py \
  tests/integration/gateway/test_llm_accounts_api.py \
  tests/integration/test_agent_binding_api.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run full backend test suite**

Run: `pytest`

Expected: PASS. This is required because the refactor touches shared LLM binding semantics used by agents, memory components, gateway tests, and context compaction.

- [ ] **Step 3: Run backend lint and type checks**

Run:

```bash
ruff check sebastian/ tests/
mypy sebastian/
```

Expected: PASS.

- [ ] **Step 4: Run Android unit tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest
```

Expected: PASS.

- [ ] **Step 5: Run Android compile**

Run:

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin
```

Expected: PASS.

- [ ] **Step 6: Manual smoke test with a clean dev DB**

Run backend with a clean dev data directory:

```bash
SEBASTIAN_DATA_DIR=/tmp/sebastian-llm-catalog-smoke uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8824
```

Smoke sequence:

1. `GET /api/v1/llm-catalog` returns catalog.
2. Create an account.
3. Set `/api/v1/llm-bindings/default`.
4. `GET /api/v1/agents/sebastian/llm-binding` can show fallback/resolved metadata.
5. Start Android against `http://10.0.2.2:8824` and verify Settings pages render.

- [ ] **Step 7: Final status**

Run:

```bash
git status --short
git log --oneline --max-count=10
```

Expected: worktree clean except intentional uncommitted manual artifacts, and commits are atomic.
