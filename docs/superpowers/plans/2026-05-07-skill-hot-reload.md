# Skill Hot Reload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skills added or edited under the user extensions directory are reloaded before the first turn of a new session, without adding model-visible refresh tools or scanning every turn.

**Architecture:** Add an internal `SkillHotReloader` that fingerprints `SKILL.md` files, replaces skill specs when they change, and exposes a monotonic skill version. `BaseAgent` checks this service only once per agent/session pair, then rebuilds only the current agent type singleton's prompt when its cached skill prompt version is stale.

**Tech Stack:** Python 3.12, asyncio, pytest, existing `CapabilityRegistry`, `BaseAgent`, `gateway.state`, and `load_skills()`.

---

## File Structure

- Modify `sebastian/capabilities/registry.py`
  - Separate skill storage from MCP storage.
  - Add `replace_skill_specs()`.
  - Preserve existing `register_skill_specs()` behavior.

- Create `sebastian/capabilities/skills/hot_reload.py`
  - Define `SkillFileFingerprint`, `SkillFingerprint`, `SkillReloadResult`.
  - Define `SkillHotReloader`.
  - Implement `seeded()` for startup fingerprint capture.
  - Implement `maybe_reload()`.

- Modify `sebastian/gateway/state.py`
  - Add `skill_hot_reloader` runtime singleton annotation.

- Modify `sebastian/gateway/app.py`
  - Instantiate and seed `SkillHotReloader` immediately after startup skill load.
  - Register startup skill specs through `replace_skill_specs()` or keep existing registration then seed from the same dirs.

- Modify `sebastian/core/base_agent.py`
  - Add `_skill_prompt_version`.
  - Add `rebuild_system_prompt()` and `mark_skill_prompt_version()`.
  - Add first-session skill reload check using an in-memory `(agent_context, session_id)` set.
  - Call the check after resolving `worker_session` and before assembling the effective prompt.

- Modify `sebastian/orchestrator/sebas.py`
  - Keep/adjust the Sebastian override of `rebuild_system_prompt()`.
  - Ensure it remains compatible with the new base method.

- Test `tests/unit/capabilities/test_registry_filtering.py`
  - Add replacement and collision tests.

- Test `tests/unit/capabilities/test_skill_hot_reload.py`
  - New tests for fingerprinting, changed/unchanged reloads, deletion, scripts ignored, startup seed, concurrency.

- Test `tests/unit/core/test_base_agent.py` or `tests/unit/core/test_prompt_builder.py`
  - Add agent lifecycle tests for new-session check, stale version catch-up, subsequent-turn skip, and current-agent-only rebuild.

- Optional docs update
  - Update `sebastian/capabilities/skills/README.md` only if implementation changes the documented extension behavior materially.

---

## Task 0: Prepare Feature Branch

**Files:**
- No code files

- [ ] **Step 1: Confirm clean worktree**

Run:

```bash
git status --short
```

Expected: no output.

- [ ] **Step 2: Start from latest main**

Run:

```bash
git checkout main
git pull
git checkout -b feat/skill-hot-reload
```

Expected: branch switches to `feat/skill-hot-reload`.

- [ ] **Step 3: Confirm branch**

Run:

```bash
git branch --show-current
```

Expected: `feat/skill-hot-reload`.

---

## Task 1: Split Skill Storage From MCP Storage

**Files:**
- Modify: `sebastian/capabilities/registry.py`
- Test: `tests/unit/capabilities/test_registry_filtering.py`

- [ ] **Step 1: Write failing tests for skill replacement**

Add tests:

```python
def test_replace_skill_specs_removes_deleted_skills() -> None:
    reg = CapabilityRegistry()
    reg.register_skill_specs(
        [
            {"name": "skill_a", "description": "A", "input_schema": {}},
            {"name": "skill_b", "description": "B", "input_schema": {}},
        ]
    )

    reg.replace_skill_specs(
        [{"name": "skill_b", "description": "B2", "input_schema": {}}]
    )

    names = {s["name"] for s in reg.get_skill_specs()}
    assert names == {"skill_b"}
    assert next(s for s in reg.get_skill_specs() if s["name"] == "skill_b")[
        "description"
    ] == "B2"
```

Add collision tests:

```python
def test_skill_name_collision_hides_skill_spec_and_preserves_mcp_tool() -> None:
    reg = CapabilityRegistry()

    async def mcp_fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="mcp")

    reg.register_mcp_tool(
        "skill__travel",
        {"name": "skill__travel", "description": "mcp travel", "input_schema": {}},
        mcp_fn,
    )
    reg.register_skill_specs(
        [{"name": "skill__travel", "description": "skill travel", "input_schema": {}}]
    )

    callable_names = [s["name"] for s in reg.get_callable_specs(ALL_TOOLS, None)]
    tool_names = {s["name"] for s in reg.get_tool_specs(ALL_TOOLS)}
    skill_names = {s["name"] for s in reg.get_skill_specs()}

    assert callable_names.count("skill__travel") == 1
    assert "skill__travel" in tool_names
    assert "skill__travel" not in skill_names
```

```python
def test_replace_skill_specs_does_not_delete_colliding_mcp_tool() -> None:
    reg = CapabilityRegistry()

    async def mcp_fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="mcp")

    reg.register_mcp_tool(
        "skill__travel",
        {"name": "skill__travel", "description": "mcp travel", "input_schema": {}},
        mcp_fn,
    )
    reg.register_skill_specs(
        [{"name": "skill__travel", "description": "skill travel", "input_schema": {}}]
    )

    reg.replace_skill_specs([])

    assert "skill__travel" in {s["name"] for s in reg.get_tool_specs(ALL_TOOLS)}
    assert "skill__travel" not in {s["name"] for s in reg.get_skill_specs()}
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests/unit/capabilities/test_registry_filtering.py -q
```

Expected: fails because `replace_skill_specs()` does not exist.

- [ ] **Step 3: Implement separate `_skill_tools` storage**

In `CapabilityRegistry.__init__`:

```python
self._mcp_tools: dict[str, tuple[dict[str, Any], McpToolFn]] = {}
self._skill_tools: dict[str, tuple[dict[str, Any], ToolFn]] = {}
```

Update:

- `get_tool_specs()` reads `_mcp_tools`.
- `get_skill_specs()` reads `_skill_tools`, but hides any skill whose name collides with
  native or MCP tool names.
- `get_callable_specs()` must never return duplicate names. Native/MCP tools win over
  skills on collision.
- `call()` checks native, then `_mcp_tools`, then `_skill_tools`.
- `register_skill_specs()` writes `_skill_tools`.
- Remove or stop using `_skill_names`.

Add:

```python
def replace_skill_specs(self, specs: list[dict[str, Any]]) -> None:
    self._skill_tools.clear()
    self.register_skill_specs(specs)
```

Add a helper:

```python
def _name_collides_with_tool(self, name: str) -> bool:
    return get_tool(name) is not None or name in self._mcp_tools
```

Use it in `get_skill_specs()`:

```python
if self._name_collides_with_tool(name):
    logger.warning("Skill %r hidden because a native/MCP tool has the same name", name)
    continue
```

Keep the existing `_skill_fn()` behavior:

```python
async def _skill_fn(instructions: str = "", _desc: str = description) -> ToolResult:
    return ToolResult(ok=True, output=_desc)
```

- [ ] **Step 4: Run registry tests**

Run:

```bash
pytest tests/unit/capabilities/test_registry_filtering.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/registry.py tests/unit/capabilities/test_registry_filtering.py
git commit -m "refactor(capabilities): 分离 skill 与 MCP 注册存储" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

## Task 2: Add SkillHotReloader

**Files:**
- Create: `sebastian/capabilities/skills/hot_reload.py`
- Test: `tests/unit/capabilities/test_skill_hot_reload.py`

- [ ] **Step 1: Write failing tests for unchanged and changed fingerprints**

Create `tests/unit/capabilities/test_skill_hot_reload.py`.

Use helpers:

```python
from pathlib import Path

import pytest

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.capabilities.skills._loader import load_skills
from sebastian.capabilities.skills.hot_reload import SkillHotReloader


def write_skill(base: Path, dirname: str, body: str) -> None:
    skill_dir = base / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
```

Test unchanged seed:

```python
@pytest.mark.asyncio
async def test_seeded_reloader_unchanged_returns_current_version(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Travel\n---\nUse APIs.")
    reg = CapabilityRegistry()
    specs = load_skills(builtin_dir=tmp_path, extra_dirs=[])
    reg.replace_skill_specs(specs)
    reloader = SkillHotReloader.seeded(
        registry=reg,
        builtin_dir=tmp_path,
        extra_dirs=[],
    )

    result = await reloader.maybe_reload()

    assert result.changed is False
    assert result.version == 0
    assert {s["name"] for s in reg.get_skill_specs()} == {"skill__travel"}
```

Test edit:

```python
@pytest.mark.asyncio
async def test_edit_skill_md_reloads_and_increments_version(tmp_path: Path) -> None:
    write_skill(tmp_path, "travel", "---\nname: travel\ndescription: Old\n---\nOld.")
    reg = CapabilityRegistry()
    reg.replace_skill_specs(load_skills(builtin_dir=tmp_path, extra_dirs=[]))
    reloader = SkillHotReloader.seeded(registry=reg, builtin_dir=tmp_path, extra_dirs=[])

    write_skill(
        tmp_path,
        "travel",
        "---\nname: travel\ndescription: New and longer\n---\nNew body with more bytes.",
    )
    result = await reloader.maybe_reload()

    assert result.changed is True
    assert result.version == 1
    assert "New and longer" in reg.get_skill_specs()[0]["description"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests/unit/capabilities/test_skill_hot_reload.py -q
```

Expected: import fails because `hot_reload.py` does not exist.

- [ ] **Step 3: Implement dataclasses and fingerprint scanner**

In `sebastian/capabilities/skills/hot_reload.py`:

```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.capabilities.skills._loader import load_skills

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class SkillFileFingerprint:
    relative_path: str
    mtime_ns: int
    size: int


SkillFingerprint = tuple[SkillFileFingerprint, ...]


@dataclass(frozen=True)
class SkillReloadResult:
    changed: bool
    version: int
    fingerprint: SkillFingerprint
```

Add scanner:

```python
def _skill_dirs(builtin_dir: Path, extra_dirs: list[Path]) -> list[Path]:
    return [builtin_dir, *extra_dirs]


def compute_skill_fingerprint(
    builtin_dir: Path,
    extra_dirs: list[Path] | None = None,
) -> SkillFingerprint:
    entries: list[SkillFileFingerprint] = []
    for base in _skill_dirs(builtin_dir, extra_dirs or []):
        if not base.exists():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            stat = skill_md.stat()
            try:
                rel = str(skill_md.relative_to(base))
            except ValueError:
                rel = str(skill_md)
            entries.append(
                SkillFileFingerprint(
                    relative_path=f"{base.resolve()}::{rel}",
                    mtime_ns=stat.st_mtime_ns,
                    size=stat.st_size,
                )
            )
    return tuple(sorted(entries))
```

- [ ] **Step 4: Implement `SkillHotReloader`**

```python
class SkillHotReloader:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        builtin_dir: Path,
        extra_dirs: list[Path] | None = None,
        fingerprint: SkillFingerprint | None = None,
        version: int = 0,
    ) -> None:
        self._registry = registry
        self._builtin_dir = builtin_dir
        self._extra_dirs = extra_dirs or []
        self._fingerprint = (
            fingerprint
            if fingerprint is not None
            else compute_skill_fingerprint(builtin_dir, self._extra_dirs)
        )
        self._version = version
        self._lock = asyncio.Lock()

    @classmethod
    def seeded(
        cls,
        *,
        registry: CapabilityRegistry,
        builtin_dir: Path,
        extra_dirs: list[Path] | None = None,
    ) -> SkillHotReloader:
        return cls(
            registry=registry,
            builtin_dir=builtin_dir,
            extra_dirs=extra_dirs,
            fingerprint=compute_skill_fingerprint(builtin_dir, extra_dirs or []),
            version=0,
        )

    @property
    def version(self) -> int:
        return self._version

    async def maybe_reload(self) -> SkillReloadResult:
        async with self._lock:
            latest = compute_skill_fingerprint(self._builtin_dir, self._extra_dirs)
            if latest == self._fingerprint:
                return SkillReloadResult(False, self._version, latest)

            try:
                specs = load_skills(
                    builtin_dir=self._builtin_dir,
                    extra_dirs=self._extra_dirs,
                )
                self._registry.replace_skill_specs(specs)
            except Exception:
                logger.warning("Skill hot reload failed", exc_info=True)
                return SkillReloadResult(False, self._version, self._fingerprint)

            self._fingerprint = latest
            self._version += 1
            return SkillReloadResult(True, self._version, latest)
```

- [ ] **Step 5: Add remaining reloader tests**

Add tests for:

- deleting a `SKILL.md`
- adding a `scripts/search_flights.py` without editing `SKILL.md`
- adding or editing `_ignored/SKILL.md` does not trigger reload
- concurrent `maybe_reload()` calls
- startup seed catches edits made after seed but before first `maybe_reload()`

Use:

```python
await asyncio.gather(*(reloader.maybe_reload() for _ in range(5)))
```

Expected: only final registry state matters; version should increment once for one file change.

- [ ] **Step 6: Run reloader tests**

Run:

```bash
pytest tests/unit/capabilities/test_skill_hot_reload.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add sebastian/capabilities/skills/hot_reload.py tests/unit/capabilities/test_skill_hot_reload.py
git commit -m "feat(capabilities): 新增 Skill 热加载器" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

## Task 3: Seed Reloader During Gateway Startup

**Files:**
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/gateway/app.py`
- Test: `tests/unit/capabilities/test_skill_hot_reload.py` or existing gateway lifespan tests if available

- [ ] **Step 1: Add state annotation**

In `sebastian/gateway/state.py`, under `TYPE_CHECKING`:

```python
from sebastian.capabilities.skills.hot_reload import SkillHotReloader
```

At module scope:

```python
skill_hot_reloader: SkillHotReloader | None = None
```

- [ ] **Step 2: Update gateway startup wiring**

In `sebastian/gateway/app.py`, replace startup skill registration with:

```python
from pathlib import Path

from sebastian.capabilities.skills._loader import load_skills
from sebastian.capabilities.skills.hot_reload import SkillHotReloader

skill_extra_dirs = [settings.skills_extensions_dir]
skill_specs = load_skills(extra_dirs=skill_extra_dirs)
registry.replace_skill_specs(skill_specs)
state.skill_hot_reloader = SkillHotReloader.seeded(
    registry=registry,
    builtin_dir=Path(__file__).parents[1] / "capabilities" / "skills",
    extra_dirs=skill_extra_dirs,
)
logger.info("Loaded %d skills", len(skill_specs))
```

Prefer importing the loader module's default built-in path instead of recomputing if the implementation exposes a constant. If no constant exists, use:

```python
from sebastian.capabilities import skills as skills_pkg
builtin_dir = Path(skills_pkg.__file__).parent
```

- [ ] **Step 3: Add a startup seed test if there is a lightweight app lifespan fixture**

If gateway lifespan tests already exist, assert `state.skill_hot_reloader is not None` after startup.

If not, skip a heavy gateway test and rely on `SkillHotReloader.seeded()` unit tests. Do not create a heavyweight FastAPI lifespan test just for this wiring.

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/unit/capabilities/test_skill_hot_reload.py tests/unit/capabilities/test_registry_filtering.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/state.py sebastian/gateway/app.py tests/unit/capabilities/test_skill_hot_reload.py
git commit -m "feat(gateway): 启动时初始化 Skill 热加载器" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

## Task 4: Add Agent Prompt Versioning and New-Session Check

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/orchestrator/sebas.py`
- Test: `tests/unit/core/test_base_agent.py`
- Test: `tests/unit/core/test_prompt_builder.py`

- [ ] **Step 1: Write failing prompt rebuild tests**

In `tests/unit/core/test_prompt_builder.py`, add:

```python
@pytest.mark.asyncio
async def test_base_agent_rebuild_system_prompt_refreshes_skills(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am your butler."
        allowed_tools: list[str] | None = []
        allowed_skills: list[str] | None = None

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()
    with patch("sebastian.core.base_agent.settings") as mock_settings:
        mock_settings.sebastian_model = "claude-opus-4-6"
        mock_settings.llm_max_tokens = 16000
        mock_settings.workspace_dir = tmp_path / "workspace"
        agent = MyAgent(reg, store)

    assert "skill__travel" not in agent.system_prompt
    reg.replace_skill_specs(
        [{"name": "skill__travel", "description": "Travel skill", "input_schema": {}}]
    )

    agent.rebuild_system_prompt()

    assert "skill__travel" in agent.system_prompt
```

If existing tests require settings patches, follow the existing `patch("sebastian.core.base_agent.settings")` pattern in the file.

- [ ] **Step 2: Add base methods**

In `BaseAgent.__init__`, initialize:

```python
self._skill_prompt_version = 0
self._skill_reload_checked_sessions: set[tuple[str, str]] = set()
```

Add methods near `build_system_prompt()`:

```python
def rebuild_system_prompt(self) -> None:
    self.system_prompt = self.build_system_prompt(self._gate)


def mark_skill_prompt_version(self, version: int) -> None:
    self._skill_prompt_version = version
```

- [ ] **Step 3: Ensure Sebastian override still works**

In `sebastian/orchestrator/sebas.py`, keep:

```python
def rebuild_system_prompt(self) -> None:
    self.system_prompt = self.build_system_prompt(self._gate, self._agent_registry)
```

Do not change soul switching behavior. Existing soul switching code already calls Sebastian's rebuild method.

- [ ] **Step 4: Write failing lifecycle tests**

In `tests/unit/core/test_base_agent.py`, add a fake reloader:

```python
class FakeSkillReloader:
    def __init__(self, version: int = 0) -> None:
        self.version = version
        self.calls = 0

    async def maybe_reload(self):
        from sebastian.capabilities.skills.hot_reload import SkillReloadResult

        self.calls += 1
        return SkillReloadResult(
            changed=False,
            version=self.version,
            fingerprint=(),
        )
```

Add test: new session first turn calls reloader once.

Patch `sebastian.gateway.state.skill_hot_reloader` to fake reloader. Use an agent with `_loop.stream` replaced by a fake async generator that immediately yields `TurnDone` or returns empty, following existing patterns in `test_base_agent.py`.

Assert:

```python
assert reloader.calls == 1
```

Add test: same session second turn does not call again.

Assert:

```python
assert reloader.calls == 1
```

Add test: stale prompt version rebuilds even when `changed=False`.

Use a spy:

```python
agent.rebuild_system_prompt = MagicMock(wraps=agent.rebuild_system_prompt)
reloader.version = 2
await agent.run_streaming("hello", "new-session")
agent.rebuild_system_prompt.assert_called_once()
assert agent._skill_prompt_version == 2
```

Add test: only the current agent type singleton rebuilds.

Create two agent instances sharing the same fake reloader. Invoke `run_streaming()` on only
one instance, then assert only that instance's `rebuild_system_prompt()` spy was called.

```python
agent_a.rebuild_system_prompt = MagicMock(wraps=agent_a.rebuild_system_prompt)
agent_b.rebuild_system_prompt = MagicMock(wraps=agent_b.rebuild_system_prompt)

await agent_a.run_streaming("hello", "session-a")

agent_a.rebuild_system_prompt.assert_called_once()
agent_b.rebuild_system_prompt.assert_not_called()
```

Add test: Sebastian's rebuild keeps sub-agent section.

Use `Sebastian.__new__(Sebastian)` as in existing
`test_sebastian_agents_section_renders_agent_type_only`, set `_gate` and `_agent_registry`
manually, call `rebuild_system_prompt()`, and assert:

```python
assert "## Available Sub-Agents" in obj.system_prompt
assert "- forge:" in obj.system_prompt
```

- [ ] **Step 5: Implement `_maybe_refresh_skills_for_new_session()`**

In `BaseAgent`, add:

```python
async def _maybe_refresh_skills_for_new_session(
    self,
    session_id: str,
    agent_context: str,
) -> None:
    key = (agent_context, session_id)
    if key in self._skill_reload_checked_sessions:
        return
    self._skill_reload_checked_sessions.add(key)

    try:
        import sebastian.gateway.state as state

        reloader = getattr(state, "skill_hot_reloader", None)
    except ImportError:
        return

    if reloader is None:
        return

    result = await reloader.maybe_reload()
    if self._skill_prompt_version != result.version:
        self.rebuild_system_prompt()
        self.mark_skill_prompt_version(result.version)
```

In `run_streaming()`, after `worker_session` is resolved and before `TURN_RECEIVED` or before prompt assembly, call:

```python
await self._maybe_refresh_skills_for_new_session(session_id, agent_context)
```

Prefer before `TURN_RECEIVED` so the turn's entire execution sees a settled capability state.

- [ ] **Step 6: Run focused core tests**

Run:

```bash
pytest tests/unit/core/test_prompt_builder.py tests/unit/core/test_base_agent.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add sebastian/core/base_agent.py sebastian/orchestrator/sebas.py tests/unit/core/test_base_agent.py tests/unit/core/test_prompt_builder.py
git commit -m "feat(core): 新会话首轮刷新 Skill prompt" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

## Task 5: Documentation and Regression Run

**Files:**
- Modify if needed: `sebastian/capabilities/skills/README.md`
- Modify if needed: `sebastian/capabilities/README.md`
- Modify if needed: `docs/architecture/spec/capabilities/INDEX.md` or relevant spec index only if project convention requires integrating this planned spec now

- [ ] **Step 1: Check whether README needs update**

Read:

```bash
sed -n '1,180p' sebastian/capabilities/skills/README.md
```

If it still says skills are loaded only at startup, update it. If it already describes dynamic user extension loading without lifecycle specifics, keep it unchanged.

- [ ] **Step 2: Run focused unit suites**

Run:

```bash
pytest tests/unit/capabilities/test_registry_filtering.py tests/unit/capabilities/test_skills_loader.py tests/unit/capabilities/test_skill_hot_reload.py tests/unit/core/test_prompt_builder.py tests/unit/core/test_base_agent.py -q
```

Expected: pass.

- [ ] **Step 3: Run lint on touched Python files**

Run:

```bash
ruff check sebastian/capabilities/registry.py sebastian/capabilities/skills/hot_reload.py sebastian/gateway/state.py sebastian/gateway/app.py sebastian/core/base_agent.py sebastian/orchestrator/sebas.py tests/unit/capabilities/test_registry_filtering.py tests/unit/capabilities/test_skill_hot_reload.py tests/unit/core/test_base_agent.py tests/unit/core/test_prompt_builder.py
```

Expected: pass.

- [ ] **Step 4: Run formatter check**

Run:

```bash
ruff format --check sebastian/capabilities/registry.py sebastian/capabilities/skills/hot_reload.py sebastian/gateway/state.py sebastian/gateway/app.py sebastian/core/base_agent.py sebastian/orchestrator/sebas.py tests/unit/capabilities/test_registry_filtering.py tests/unit/capabilities/test_skill_hot_reload.py tests/unit/core/test_base_agent.py tests/unit/core/test_prompt_builder.py
```

Expected: pass. If it fails, run the same command without `--check`, then re-run tests.

- [ ] **Step 5: Update graphify code graph**

Because Python code changed, run:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: command completes successfully.

- [ ] **Step 6: Commit docs or formatting follow-up if needed**

Only if Task 5 changed files:

```bash
git add <specific changed files>
git commit -m "docs(capabilities): 更新 Skill 热加载说明" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

## Final Verification

- [ ] **Step 1: Run the full backend unit suite if time permits**

```bash
pytest tests/unit/ -q
```

Expected: pass.

- [ ] **Step 2: Inspect final diff**

```bash
git status --short
git log --oneline -5
```

Expected:

- Worktree clean.
- Commits are task-scoped.

- [ ] **Step 3: Report behavior**

Summarize:

- New/edited/deleted `SKILL.md` under user extensions is picked up before a new session's first turn.
- Existing sessions do not scan every turn.
- No model-visible refresh tool was added.
- Script files remain naturally hot because `Bash` executes them fresh.
