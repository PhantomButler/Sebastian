# Memory Internal Package Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `sebastian/memory` internal implementation files into focused subpackages while preserving all runtime behavior and public `MemoryService` contracts.

**Architecture:** Keep `contracts/` and `services/` as the only external memory-facing boundary. Move internal implementation modules into `stores/`, `writing/`, `retrieval/`, `consolidation/`, and `resident/`; update imports without old-path shims. Add an explicit import smoke test so moved module paths and key external entrypoints are verified after migration.

**Tech Stack:** Python 3.12, PyCharm MCP indexed search, `git mv`, pytest, ruff, `compileall`, graphify.

---

## File Structure

Create:

- `sebastian/memory/stores/__init__.py`
- `sebastian/memory/writing/__init__.py`
- `sebastian/memory/retrieval/__init__.py`
- `sebastian/memory/consolidation/__init__.py`
- `sebastian/memory/resident/__init__.py`
- `tests/unit/memory/test_memory_imports_after_reorg.py`

Move:

- `sebastian/memory/profile_store.py` -> `sebastian/memory/stores/profile_store.py`
- `sebastian/memory/episode_store.py` -> `sebastian/memory/stores/episode_store.py`
- `sebastian/memory/entity_registry.py` -> `sebastian/memory/stores/entity_registry.py`
- `sebastian/memory/slot_definition_store.py` -> `sebastian/memory/stores/slot_definition_store.py`
- `sebastian/memory/pipeline.py` -> `sebastian/memory/writing/pipeline.py`
- `sebastian/memory/resolver.py` -> `sebastian/memory/writing/resolver.py`
- `sebastian/memory/write_router.py` -> `sebastian/memory/writing/write_router.py`
- `sebastian/memory/decision_log.py` -> `sebastian/memory/writing/decision_log.py`
- `sebastian/memory/feedback.py` -> `sebastian/memory/writing/feedback.py`
- `sebastian/memory/slot_proposals.py` -> `sebastian/memory/writing/slot_proposals.py`
- `sebastian/memory/slots.py` -> `sebastian/memory/writing/slots.py`
- `sebastian/memory/retrieval.py` -> `sebastian/memory/retrieval/retrieval.py`
- `sebastian/memory/retrieval_lexicon.py` -> `sebastian/memory/retrieval/retrieval_lexicon.py`
- `sebastian/memory/depth_guard.py` -> `sebastian/memory/retrieval/depth_guard.py`
- `sebastian/memory/segmentation.py` -> `sebastian/memory/retrieval/segmentation.py`
- `sebastian/memory/consolidation.py` -> `sebastian/memory/consolidation/consolidation.py`
- `sebastian/memory/extraction.py` -> `sebastian/memory/consolidation/extraction.py`
- `sebastian/memory/prompts.py` -> `sebastian/memory/consolidation/prompts.py`
- `sebastian/memory/provider_bindings.py` -> `sebastian/memory/consolidation/provider_bindings.py`
- `sebastian/memory/resident_snapshot.py` -> `sebastian/memory/resident/resident_snapshot.py`
- `sebastian/memory/resident_dedupe.py` -> `sebastian/memory/resident/resident_dedupe.py`

Modify imports in:

- `sebastian/memory/**/*.py`
- `sebastian/core/base_agent.py`
- `sebastian/gateway/app.py`
- `sebastian/gateway/state.py`
- `sebastian/capabilities/tools/memory_save/__init__.py`
- `sebastian/capabilities/tools/memory_search/__init__.py`
- `tests/unit/memory/*.py`
- `tests/unit/capabilities/test_memory_tools.py`
- `tests/integration/memory/*.py`

Update docs:

- `sebastian/memory/README.md`
- `sebastian/README.md`
- `docs/architecture/spec/memory/*.md`

Do not create old-path compatibility shim files.

---

### Task 1: Add Import Smoke Test

**Files:**
- Create: `tests/unit/memory/test_memory_imports_after_reorg.py`

- [ ] **Step 1: Create the failing import smoke test**

Add this file:

```python
from __future__ import annotations

import importlib


MOVED_MEMORY_MODULES = [
    "sebastian.memory.stores.profile_store",
    "sebastian.memory.stores.episode_store",
    "sebastian.memory.stores.entity_registry",
    "sebastian.memory.stores.slot_definition_store",
    "sebastian.memory.writing.pipeline",
    "sebastian.memory.writing.resolver",
    "sebastian.memory.writing.write_router",
    "sebastian.memory.writing.decision_log",
    "sebastian.memory.writing.feedback",
    "sebastian.memory.writing.slot_proposals",
    "sebastian.memory.writing.slots",
    "sebastian.memory.retrieval.retrieval",
    "sebastian.memory.retrieval.retrieval_lexicon",
    "sebastian.memory.retrieval.depth_guard",
    "sebastian.memory.retrieval.segmentation",
    "sebastian.memory.consolidation.consolidation",
    "sebastian.memory.consolidation.extraction",
    "sebastian.memory.consolidation.prompts",
    "sebastian.memory.consolidation.provider_bindings",
    "sebastian.memory.resident.resident_snapshot",
    "sebastian.memory.resident.resident_dedupe",
]

KEY_EXTERNAL_ENTRYPOINTS = [
    "sebastian.core.base_agent",
    "sebastian.gateway.app",
    "sebastian.capabilities.tools.memory_save",
    "sebastian.capabilities.tools.memory_search",
]


def test_memory_reorganized_modules_are_importable() -> None:
    for module_name in MOVED_MEMORY_MODULES:
        importlib.import_module(module_name)


def test_memory_external_entrypoints_are_importable() -> None:
    for module_name in KEY_EXTERNAL_ENTRYPOINTS:
        importlib.import_module(module_name)
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run:

```bash
pytest tests/unit/memory/test_memory_imports_after_reorg.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `sebastian.memory.stores...`.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/unit/memory/test_memory_imports_after_reorg.py
git commit -m "test(memory): 新增 memory 重组 import smoke test" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 2: Create Subpackages And Move Store Modules

**Files:**
- Create: `sebastian/memory/stores/__init__.py`
- Move: `profile_store.py`, `episode_store.py`, `entity_registry.py`, `slot_definition_store.py`
- Modify imports in moved store modules, `startup.py`, retrieval/writing modules, tests.
- Test: `tests/unit/memory/test_profile_store.py`, `tests/unit/memory/test_episode_store.py`, `tests/unit/memory/test_entity_registry.py`, `tests/unit/memory/test_slot_definition_store.py`, `tests/integration/memory/test_entity_registry_reload_hook.py`

- [ ] **Step 1: Create `stores/` and move store files**

Run:

```bash
mkdir -p sebastian/memory/stores
touch sebastian/memory/stores/__init__.py
git mv sebastian/memory/profile_store.py sebastian/memory/stores/profile_store.py
git mv sebastian/memory/episode_store.py sebastian/memory/stores/episode_store.py
git mv sebastian/memory/entity_registry.py sebastian/memory/stores/entity_registry.py
git mv sebastian/memory/slot_definition_store.py sebastian/memory/stores/slot_definition_store.py
```

- [ ] **Step 2: Update store import paths with PyCharm MCP search**

Use PyCharm MCP indexed search before editing:

Search and replace exact import forms:

```text
from sebastian.memory.profile_store import
from sebastian.memory.episode_store import
from sebastian.memory.entity_registry import
from sebastian.memory.slot_definition_store import
import sebastian.memory.profile_store
import sebastian.memory.episode_store
import sebastian.memory.entity_registry
import sebastian.memory.slot_definition_store
from sebastian.memory import profile_store
from sebastian.memory import episode_store
from sebastian.memory import entity_registry
from sebastian.memory import slot_definition_store
```

New paths:

```text
from sebastian.memory.stores.profile_store import
from sebastian.memory.stores.episode_store import
from sebastian.memory.stores.entity_registry import
from sebastian.memory.stores.slot_definition_store import
import sebastian.memory.stores.profile_store
import sebastian.memory.stores.episode_store
import sebastian.memory.stores.entity_registry
import sebastian.memory.stores.slot_definition_store
from sebastian.memory.stores import profile_store
from sebastian.memory.stores import episode_store
from sebastian.memory.stores import entity_registry
from sebastian.memory.stores import slot_definition_store
```

- [ ] **Step 3: Update string patch targets for stores**

Search for store paths inside strings used by `patch()` / `monkeypatch.setattr()` and update them to the new paths.

Examples:

```python
"sebastian.memory.entity_registry.EntityRegistry"
```

becomes:

```python
"sebastian.memory.stores.entity_registry.EntityRegistry"
```

- [ ] **Step 4: Run focused store tests**

Run:

```bash
pytest tests/unit/memory/test_profile_store.py tests/unit/memory/test_episode_store.py tests/unit/memory/test_entity_registry.py tests/unit/memory/test_slot_definition_store.py tests/integration/memory/test_entity_registry_reload_hook.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit store move**

```bash
git add sebastian/memory/stores/__init__.py \
  sebastian/memory/stores/profile_store.py \
  sebastian/memory/stores/episode_store.py \
  sebastian/memory/stores/entity_registry.py \
  sebastian/memory/stores/slot_definition_store.py \
  sebastian/memory/startup.py \
  tests/unit/memory/test_profile_store.py \
  tests/unit/memory/test_episode_store.py \
  tests/unit/memory/test_entity_registry.py \
  tests/unit/memory/test_slot_definition_store.py \
  tests/integration/memory/test_entity_registry_reload_hook.py
git status --short sebastian/memory tests/unit/memory tests/integration/memory
# Add any additional modified files from the status output explicitly.
git add <each additional modified file>
git commit -m "refactor(memory): 迁移 store 模块到 stores 子包" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 3: Move Writing Modules

**Files:**
- Create: `sebastian/memory/writing/__init__.py`
- Move: `pipeline.py`, `resolver.py`, `write_router.py`, `decision_log.py`, `feedback.py`, `slot_proposals.py`, `slots.py`
- Modify imports in services, tools, startup, consolidation, tests, docs later.
- Test: writing-related unit tests and memory tools tests.

- [ ] **Step 1: Create `writing/` and move files**

Run:

```bash
mkdir -p sebastian/memory/writing
touch sebastian/memory/writing/__init__.py
git mv sebastian/memory/pipeline.py sebastian/memory/writing/pipeline.py
git mv sebastian/memory/resolver.py sebastian/memory/writing/resolver.py
git mv sebastian/memory/write_router.py sebastian/memory/writing/write_router.py
git mv sebastian/memory/decision_log.py sebastian/memory/writing/decision_log.py
git mv sebastian/memory/feedback.py sebastian/memory/writing/feedback.py
git mv sebastian/memory/slot_proposals.py sebastian/memory/writing/slot_proposals.py
git mv sebastian/memory/slots.py sebastian/memory/writing/slots.py
```

- [ ] **Step 2: Update writing import paths**

Use PyCharm MCP search for these old import forms:

```text
from sebastian.memory.pipeline import
from sebastian.memory.resolver import
from sebastian.memory.write_router import
from sebastian.memory.decision_log import
from sebastian.memory.feedback import
from sebastian.memory.slot_proposals import
from sebastian.memory.slots import
import sebastian.memory.pipeline
import sebastian.memory.resolver
import sebastian.memory.write_router
import sebastian.memory.decision_log
import sebastian.memory.feedback
import sebastian.memory.slot_proposals
import sebastian.memory.slots
from sebastian.memory import pipeline
from sebastian.memory import resolver
from sebastian.memory import write_router
from sebastian.memory import decision_log
from sebastian.memory import feedback
from sebastian.memory import slot_proposals
from sebastian.memory import slots
```

Replace with `sebastian.memory.writing.<module>`.

- [ ] **Step 3: Update writing string patch targets**

Search for old string targets in tests:

```text
sebastian.memory.pipeline
sebastian.memory.resolver
sebastian.memory.write_router
sebastian.memory.decision_log
sebastian.memory.feedback
sebastian.memory.slot_proposals
sebastian.memory.slots
```

Replace with `sebastian.memory.writing.<module>`.

- [ ] **Step 4: Run focused writing tests**

Run:

```bash
pytest tests/unit/memory/test_pipeline.py tests/unit/memory/test_resolver.py tests/unit/memory/test_write_router.py tests/unit/memory/test_decision_log.py tests/unit/memory/test_feedback.py tests/unit/memory/test_slot_proposals.py tests/unit/memory/test_slots.py tests/unit/memory/test_builtin_slots.py tests/unit/memory/test_slot_registry_bootstrap.py tests/unit/memory/test_pipeline_proposed_slots_flow.py tests/unit/capabilities/test_memory_tools.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit writing move**

```bash
git add sebastian/memory/writing/__init__.py \
  sebastian/memory/writing/pipeline.py \
  sebastian/memory/writing/resolver.py \
  sebastian/memory/writing/write_router.py \
  sebastian/memory/writing/decision_log.py \
  sebastian/memory/writing/feedback.py \
  sebastian/memory/writing/slot_proposals.py \
  sebastian/memory/writing/slots.py
git status --short sebastian/memory sebastian/capabilities tests/unit/memory tests/unit/capabilities
# Add any additional modified files from the status output explicitly.
git add <each additional modified file>
git commit -m "refactor(memory): 迁移写入链路到 writing 子包" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 4: Move Retrieval Modules

**Files:**
- Create: `sebastian/memory/retrieval/__init__.py`
- Move: `retrieval.py`, `retrieval_lexicon.py`, `depth_guard.py`, `segmentation.py`
- Modify imports in `base_agent.py`, `gateway/app.py`, services, stores, startup, tests.
- Test: retrieval and depth-guard tests.

- [ ] **Step 1: Create `retrieval/` and move files**

Run:

```bash
mkdir -p sebastian/memory/retrieval
touch sebastian/memory/retrieval/__init__.py
git mv sebastian/memory/retrieval.py sebastian/memory/retrieval/retrieval.py
git mv sebastian/memory/retrieval_lexicon.py sebastian/memory/retrieval/retrieval_lexicon.py
git mv sebastian/memory/depth_guard.py sebastian/memory/retrieval/depth_guard.py
git mv sebastian/memory/segmentation.py sebastian/memory/retrieval/segmentation.py
```

- [ ] **Step 2: Update retrieval import paths**

Use PyCharm MCP search for:

```text
from sebastian.memory.retrieval import
from sebastian.memory.retrieval_lexicon import
from sebastian.memory.depth_guard import
from sebastian.memory.segmentation import
import sebastian.memory.retrieval
import sebastian.memory.retrieval_lexicon
import sebastian.memory.depth_guard
import sebastian.memory.segmentation
from sebastian.memory import retrieval
from sebastian.memory import retrieval_lexicon
from sebastian.memory import depth_guard
from sebastian.memory import segmentation
```

Replace with:

```text
from sebastian.memory.retrieval.retrieval import
from sebastian.memory.retrieval.retrieval_lexicon import
from sebastian.memory.retrieval.depth_guard import
from sebastian.memory.retrieval.segmentation import
```

- [ ] **Step 3: Update service patch targets**

Check `tests/unit/memory/test_memory_services.py` for patch targets around `retrieve_memory_section`, `_keep_record`, `DEFAULT_RETRIEVAL_PLANNER`, and `MemoryRetrievalService`.

Keep patching at the binding that the service module imports. If `services/retrieval.py` imports:

```python
from sebastian.memory.retrieval.retrieval import retrieve_memory_section
```

then tests should still patch:

```python
"sebastian.memory.services.retrieval.retrieve_memory_section"
```

Do not patch the source module when the service has already bound the symbol locally.

- [ ] **Step 4: Run focused retrieval tests**

Run:

```bash
pytest tests/unit/memory/test_retrieval.py tests/unit/memory/test_retrieval_filter.py tests/unit/memory/test_retrieval_lexicon.py tests/unit/memory/test_retrieval_planner_tokenize.py tests/unit/memory/test_memory_section_depth_guard.py tests/unit/memory/test_planner_entity_bootstrap.py tests/unit/memory/test_segmentation.py tests/integration/memory/test_memory_search_entity_trigger.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit retrieval move**

```bash
git add sebastian/memory/retrieval/__init__.py \
  sebastian/memory/retrieval/retrieval.py \
  sebastian/memory/retrieval/retrieval_lexicon.py \
  sebastian/memory/retrieval/depth_guard.py \
  sebastian/memory/retrieval/segmentation.py
git status --short sebastian/memory sebastian/core sebastian/gateway tests/unit/memory tests/integration/memory
# Add any additional modified files from the status output explicitly.
git add <each additional modified file>
git commit -m "refactor(memory): 迁移检索模块到 retrieval 子包" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 5: Move Consolidation And Resident Modules

**Files:**
- Create: `sebastian/memory/consolidation/__init__.py`
- Create: `sebastian/memory/resident/__init__.py`
- Move: `consolidation.py`, `extraction.py`, `prompts.py`, `provider_bindings.py`, `resident_snapshot.py`, `resident_dedupe.py`
- Modify imports in gateway, services, tools, tests.
- Test: consolidation, extraction, provider bindings, resident tests.

- [ ] **Step 1: Create `consolidation/` and `resident/`, then move files**

Run:

```bash
mkdir -p sebastian/memory/consolidation sebastian/memory/resident
touch sebastian/memory/consolidation/__init__.py sebastian/memory/resident/__init__.py
git mv sebastian/memory/consolidation.py sebastian/memory/consolidation/consolidation.py
git mv sebastian/memory/extraction.py sebastian/memory/consolidation/extraction.py
git mv sebastian/memory/prompts.py sebastian/memory/consolidation/prompts.py
git mv sebastian/memory/provider_bindings.py sebastian/memory/consolidation/provider_bindings.py
git mv sebastian/memory/resident_snapshot.py sebastian/memory/resident/resident_snapshot.py
git mv sebastian/memory/resident_dedupe.py sebastian/memory/resident/resident_dedupe.py
```

- [ ] **Step 2: Update consolidation import paths**

Use PyCharm MCP search for:

```text
from sebastian.memory.consolidation import
from sebastian.memory.extraction import
from sebastian.memory.prompts import
from sebastian.memory.provider_bindings import
import sebastian.memory.consolidation
import sebastian.memory.extraction
import sebastian.memory.prompts
import sebastian.memory.provider_bindings
from sebastian.memory import consolidation
from sebastian.memory import extraction
from sebastian.memory import prompts
from sebastian.memory import provider_bindings
```

Replace with:

```text
from sebastian.memory.consolidation.consolidation import
from sebastian.memory.consolidation.extraction import
from sebastian.memory.consolidation.prompts import
from sebastian.memory.consolidation.provider_bindings import
```

- [ ] **Step 3: Update resident import paths**

Use PyCharm MCP search for:

```text
from sebastian.memory.resident_snapshot import
from sebastian.memory.resident_dedupe import
import sebastian.memory.resident_snapshot
import sebastian.memory.resident_dedupe
from sebastian.memory import resident_snapshot
from sebastian.memory import resident_dedupe
```

Replace with:

```text
from sebastian.memory.resident.resident_snapshot import
from sebastian.memory.resident.resident_dedupe import
```

- [ ] **Step 4: Keep consolidation's `MemoryService` dependency injected**

Verify `SessionConsolidationWorker` still receives `MemoryService` via constructor and still calls:

```python
await self._memory_service.write_candidates_in_session(...)
```

Do not change it to read gateway state. Do not make `consolidation/` construct `MemoryService`.

- [ ] **Step 5: Run focused consolidation/resident tests**

Run:

```bash
pytest tests/unit/memory/test_consolidation.py tests/unit/memory/test_consolidator.py tests/unit/memory/test_extraction.py tests/unit/memory/test_extraction_with_proposed_slots.py tests/unit/memory/test_prompts.py tests/unit/memory/test_provider_bindings.py tests/unit/memory/test_resident_snapshot.py tests/unit/memory/test_resident_dedupe.py tests/integration/memory/test_session_consolidation_proposes_slots.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit consolidation/resident move**

```bash
git add sebastian/memory/consolidation/__init__.py \
  sebastian/memory/consolidation/consolidation.py \
  sebastian/memory/consolidation/extraction.py \
  sebastian/memory/consolidation/prompts.py \
  sebastian/memory/consolidation/provider_bindings.py \
  sebastian/memory/resident/__init__.py \
  sebastian/memory/resident/resident_snapshot.py \
  sebastian/memory/resident/resident_dedupe.py
git status --short sebastian/memory sebastian/gateway sebastian/capabilities tests/unit/memory tests/integration/memory
# Add any additional modified files from the status output explicitly.
git add <each additional modified file>
git commit -m "refactor(memory): 迁移沉淀与常驻快照模块" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 6: Update Services, Startup, Gateway, And External Entrypoints

**Files:**
- Modify: `sebastian/memory/services/*.py`
- Modify: `sebastian/memory/startup.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/capabilities/tools/memory_save/__init__.py`
- Modify: `sebastian/capabilities/tools/memory_search/__init__.py`
- Test: import smoke, memory services, memory tools.

- [ ] **Step 1: Audit service imports**

Use PyCharm MCP to read:

```text
sebastian/memory/services/memory_service.py
sebastian/memory/services/retrieval.py
sebastian/memory/services/writing.py
```

Update imports to the moved modules. Examples:

```python
from sebastian.memory.stores.profile_store import ProfileMemoryStore
from sebastian.memory.writing.pipeline import process_candidates
from sebastian.memory.retrieval.retrieval import retrieve_memory_section
from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY
```

- [ ] **Step 2: Audit startup and gateway imports**

Update only the allowed startup import list from the spec:

```python
from sebastian.memory.stores.entity_registry import EntityRegistry
from sebastian.memory.retrieval.retrieval import DEFAULT_RETRIEVAL_PLANNER
from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY
from sebastian.memory.consolidation.consolidation import (
    MemoryConsolidationScheduler,
    MemoryConsolidator,
    SessionConsolidationWorker,
    sweep_unconsolidated,
)
from sebastian.memory.consolidation.extraction import MemoryExtractor
from sebastian.memory.resident.resident_snapshot import ResidentMemorySnapshotRefresher
```

- [ ] **Step 3: Audit tools and BaseAgent imports**

Ensure:

- `BaseAgent` continues to use `MemoryService` / contracts for business memory access.
- `memory_save` continues to use `MemoryService.write_candidates()`.
- `memory_search` continues to use `MemoryService.search()`.
- Tools may import result models from their new locations, but must not directly call stores / pipeline for business logic.

- [ ] **Step 4: Verify dependency-direction checklist**

Use PyCharm MCP search to confirm:

- `sebastian/memory/resident/**/*.py` does not import `sebastian.memory.services`.
- `sebastian/memory/stores/**/*.py` does not import `sebastian.memory.services`, `sebastian.memory.consolidation`, or `sebastian.memory.resident`.
- Root foundation modules `types.py`, `subject.py`, `trace.py`, `constants.py`, and `errors.py` do not import `stores/`, `writing/`, `retrieval/`, `consolidation/`, or `resident/`.
- `SessionConsolidationWorker` receives `MemoryService` by constructor injection; it does not import gateway state and does not construct `MemoryService`.

- [ ] **Step 5: Run service and entrypoint smoke tests**

Run:

```bash
pytest tests/unit/memory/test_memory_imports_after_reorg.py tests/unit/memory/test_memory_services.py tests/unit/capabilities/test_memory_tools.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit entrypoint import updates**

```bash
git add sebastian/memory/services sebastian/memory/startup.py sebastian/gateway/app.py sebastian/gateway/state.py sebastian/core/base_agent.py sebastian/capabilities/tools/memory_save/__init__.py sebastian/capabilities/tools/memory_search/__init__.py tests/unit/memory/test_memory_imports_after_reorg.py tests/unit/memory/test_memory_services.py tests/unit/capabilities/test_memory_tools.py
git commit -m "refactor(memory): 更新 memory facade 与入口 import" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 7: Remove Old Import Forms And Verify No Shims Exist

**Files:**
- Modify: any remaining Python files with old imports.
- Verify: no old module files remain at root.

- [ ] **Step 1: Search exact old import forms with PyCharm MCP**

Search for each pattern from the spec §11:

```text
from sebastian.memory.<moved_module> import
import sebastian.memory.<moved_module>
import sebastian.memory.<moved_module> as
from sebastian.memory import <moved_module>
```

Moved module names:

```text
profile_store
episode_store
entity_registry
slot_definition_store
pipeline
resolver
write_router
decision_log
feedback
slot_proposals
slots
retrieval
retrieval_lexicon
depth_guard
segmentation
consolidation
extraction
prompts
provider_bindings
resident_snapshot
resident_dedupe
```

Explicitly search aliased old imports too:

```text
import sebastian.memory.profile_store as
import sebastian.memory.episode_store as
import sebastian.memory.entity_registry as
import sebastian.memory.slot_definition_store as
import sebastian.memory.pipeline as
import sebastian.memory.resolver as
import sebastian.memory.write_router as
import sebastian.memory.decision_log as
import sebastian.memory.feedback as
import sebastian.memory.slot_proposals as
import sebastian.memory.slots as
import sebastian.memory.retrieval as
import sebastian.memory.retrieval_lexicon as
import sebastian.memory.depth_guard as
import sebastian.memory.segmentation as
import sebastian.memory.consolidation as
import sebastian.memory.extraction as
import sebastian.memory.prompts as
import sebastian.memory.provider_bindings as
import sebastian.memory.resident_snapshot as
import sebastian.memory.resident_dedupe as
```

- [ ] **Step 2: Search monkeypatch / patch string targets**

Search:

```text
sebastian.memory.profile_store
sebastian.memory.episode_store
sebastian.memory.entity_registry
sebastian.memory.slot_definition_store
sebastian.memory.pipeline
sebastian.memory.resolver
sebastian.memory.write_router
sebastian.memory.decision_log
sebastian.memory.feedback
sebastian.memory.slot_proposals
sebastian.memory.slots
sebastian.memory.retrieval
sebastian.memory.retrieval_lexicon
sebastian.memory.depth_guard
sebastian.memory.segmentation
sebastian.memory.consolidation
sebastian.memory.extraction
sebastian.memory.prompts
sebastian.memory.provider_bindings
sebastian.memory.resident_snapshot
sebastian.memory.resident_dedupe
```

For `retrieval` and `consolidation`, use exact import-pattern searches first. Do not rely only on raw substring search, because legal new paths contain the old package prefix.

Recommended regex patterns for old string targets:

```text
sebastian\.memory\.retrieval(?!\.)
sebastian\.memory\.consolidation(?!\.)
```

These match old module-string targets such as `sebastian.memory.retrieval` and exclude legal new paths such as `sebastian.memory.retrieval.retrieval`.

If using plain text search instead of regex, search exact import prefixes:

```text
from sebastian.memory.retrieval import
import sebastian.memory.retrieval as
from sebastian.memory.consolidation import
import sebastian.memory.consolidation as
```

Ignore legal new paths:

```text
sebastian.memory.retrieval.retrieval
sebastian.memory.consolidation.consolidation
```

- [ ] **Step 3: Verify old root files are gone**

Run:

```bash
python - <<'PY'
from pathlib import Path

old_files = [
    "profile_store.py",
    "episode_store.py",
    "entity_registry.py",
    "slot_definition_store.py",
    "pipeline.py",
    "resolver.py",
    "write_router.py",
    "decision_log.py",
    "feedback.py",
    "slot_proposals.py",
    "slots.py",
    "retrieval.py",
    "retrieval_lexicon.py",
    "depth_guard.py",
    "segmentation.py",
    "consolidation.py",
    "extraction.py",
    "prompts.py",
    "provider_bindings.py",
    "resident_snapshot.py",
    "resident_dedupe.py",
]
root = Path("sebastian/memory")
remaining = [str(root / name) for name in old_files if (root / name).exists()]
assert not remaining, "old root memory modules still exist: " + ", ".join(remaining)
PY
```

Expected: no output.

- [ ] **Step 4: Run import smoke test**

Run:

```bash
pytest tests/unit/memory/test_memory_imports_after_reorg.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit cleanup**

```bash
git status --short sebastian tests
# Add any remaining modified Python files from the status output explicitly.
git add <each remaining modified Python file>
git commit -m "refactor(memory): 清理旧 memory import 路径" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 8: Update README And Architecture Docs

**Files:**
- Modify: `sebastian/memory/README.md`
- Modify: `sebastian/README.md`
- Modify: `docs/architecture/spec/memory/INDEX.md`
- Modify: `docs/architecture/spec/memory/overview.md`
- Modify: `docs/architecture/spec/memory/retrieval.md`
- Modify: `docs/architecture/spec/memory/storage.md`
- Modify: `docs/architecture/spec/memory/write-pipeline.md`
- Modify: `docs/architecture/spec/memory/consolidation.md`
- Modify: `docs/architecture/spec/memory/implementation.md`
- Modify: `docs/architecture/spec/memory/resident-snapshot.md`
- Modify: `sebastian/memory/data-flow.md`
- Search all: `docs/architecture/spec/memory/*.md`
- Search all: `sebastian/memory/data-flow.md`

- [ ] **Step 1: Update `sebastian/memory/README.md`**

Update:

- Directory structure to the new subpackages.
- Service boundary section to mention P1 internal organization.
- Modification navigation table to point to new paths.
- `data-flow.md` reference as `sebastian/memory/data-flow.md` or local `[data-flow.md](data-flow.md)`.

- [ ] **Step 2: Update `sebastian/README.md` memory section**

Replace the stale memory summary with current subpackage overview:

```markdown
### `memory/`

长期记忆系统。外部调用通过 `contracts/` + `services/`，内部实现按 `stores/`、`writing/`、`retrieval/`、`consolidation/`、`resident/` 分包组织。详见 [memory/README.md](memory/README.md)。
```

- [ ] **Step 3: Update architecture docs**

For every `docs/architecture/spec/memory/*.md`, search and update old paths. Current architecture docs should describe the new structure and must not keep old implementation paths except in explicitly marked historical migration notes.

Key replacements:

```text
sebastian/memory/retrieval.py -> sebastian/memory/retrieval/retrieval.py
sebastian/memory/pipeline.py -> sebastian/memory/writing/pipeline.py
sebastian/memory/consolidation.py -> sebastian/memory/consolidation/consolidation.py
sebastian/memory/resident_snapshot.py -> sebastian/memory/resident/resident_snapshot.py
```

- [ ] **Step 4: Update `sebastian/memory/data-flow.md`**

Search and update links inside `sebastian/memory/data-flow.md` itself. At minimum, local links such as:

```text
retrieval.py
pipeline.py
consolidation.py
resident_snapshot.py
```

must point to the new subpackage paths when those files move, for example:

```text
retrieval/retrieval.py
writing/pipeline.py
consolidation/consolidation.py
resident/resident_snapshot.py
```

- [ ] **Step 5: Run docs old-path search**

Use PyCharm MCP search over:

```text
docs/architecture/spec/memory
sebastian/memory/README.md
sebastian/README.md
sebastian/memory/data-flow.md
```

Verify old runtime paths are gone unless they appear in this P1 design document or a clearly marked migration table.

- [ ] **Step 6: Commit docs**

Before staging, run:

```bash
git status --short docs/architecture/spec/memory sebastian/memory/README.md sebastian/README.md sebastian/memory/data-flow.md
```

Stage every modified file reported there. Do not assume the list below is exhaustive if the old-path search found additional docs.

```bash
git add sebastian/memory/README.md sebastian/README.md sebastian/memory/data-flow.md docs/architecture/spec/memory/INDEX.md docs/architecture/spec/memory/overview.md docs/architecture/spec/memory/retrieval.md docs/architecture/spec/memory/storage.md docs/architecture/spec/memory/write-pipeline.md docs/architecture/spec/memory/consolidation.md docs/architecture/spec/memory/implementation.md docs/architecture/spec/memory/resident-snapshot.md
git status --short docs/architecture/spec/memory sebastian/memory/README.md sebastian/README.md sebastian/memory/data-flow.md
git commit -m "docs(memory): 同步 memory 内部包结构" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

Expected before commit: no unstaged modified docs remain.

---

### Task 9: Full Verification And Graphify Refresh

**Files:**
- No intended code changes beyond verification-generated graphify output.
- Possible modified generated files under `graphify-out/` depending repository tracking state.

- [ ] **Step 1: Run ruff**

Run:

```bash
ruff check sebastian tests
```

Expected: PASS.

- [ ] **Step 2: Run compile checks**

Run:

```bash
python -m compileall sebastian
python -m compileall tests
```

Expected: PASS.

- [ ] **Step 3: Run memory tests**

Run:

```bash
pytest tests/unit/memory -q
pytest tests/unit/capabilities/test_memory_tools.py -q
pytest tests/integration/memory -q
```

Expected: PASS.

- [ ] **Step 4: Run import smoke test explicitly**

Run:

```bash
pytest tests/unit/memory/test_memory_imports_after_reorg.py -q
```

Expected: PASS.

- [ ] **Step 5: Refresh graphify**

Run:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: completes without exception.

- [ ] **Step 6: Inspect graphify output**

Run:

```bash
git status --short graphify-out
```

If tracked graphify files changed, stage all modified tracked graphify files explicitly. If `graphify-out/` is ignored/untracked and the command shows nothing, no graphify staging is needed.

- [ ] **Step 7: Inspect final git diff**

Run:

```bash
git status --short
git diff --stat
```

Expected:

- Old root memory implementation files show as moved/deleted.
- New subpackages contain moved modules.
- No unexpected schema, prompt, or behavior changes.

- [ ] **Step 8: Final commit if needed**

If verification or graphify changed tracked files, commit them explicitly:

```bash
git add <specific files reported by git status>
git commit -m "chore(memory): 完成 memory 重组验证" \
  -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

If no tracked files changed after verification, do not create an empty commit.
