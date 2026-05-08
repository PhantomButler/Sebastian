# Skill Progressive Disclosure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Skill-as-provider-tool behavior and make Skills discoverable through a safe, progressive `sebastian skills` CLI workflow.

**Architecture:** Keep `allowed_tools -> PolicyGate -> native/MCP tool execution` as the only executable permission chain. Treat Skills as local catalog packages read from disk through `sebastian skills list/search/show/read`, with default prompt context reduced to a short bootstrap. Remove `allowed_skills`, Skill tool specs, and Skill snapshots from runtime.

**Tech Stack:** Python 3.12, Typer CLI, pytest, Pydantic/dataclasses, existing Sebastian `CapabilityRegistry`, `PolicyGate`, `BaseAgent`, `AgentLoop`, and Skill package manager modules.

---

## File Structure

Primary code changes:

- `sebastian/skills_registry/models.py`
  - Add local Skill file-list metadata and possibly `name`.
- `sebastian/skills_registry/installer.py`
  - Implement disk-current local Skill lookup, file listing, safe body/read helpers, and deterministic identifier matching.
- `sebastian/cli/skills.py`
  - Add `--source` to `search`, make local search default, add `show --body`, add `read`.
- `sebastian/capabilities/skills/_loader.py`
  - Stop producing provider tool specs. Either rename to catalog-oriented functions or leave only metadata helpers used by CLI/tests.
- `sebastian/capabilities/skills/hot_reload.py`
  - Remove provider registry mutation. Either delete runtime use or reduce to catalog fingerprint helper if still needed by tests.
- `sebastian/capabilities/registry.py`
  - Remove `_skill_tools`, `register_skill_specs`, `replace_skill_specs`, `get_skill_specs`, and skill call fallback.
- `sebastian/permissions/types.py`
  - Remove `SkillAllowlist`, `SkillSpecSnapshot`, `ToolCallContext.allowed_skills`, and `ToolCallContext.skill_specs_snapshot`.
- `sebastian/permissions/gate.py`
  - Remove Skill-specific visible spec and call branches.
- `sebastian/core/protocols.py`
  - Remove `allowed_skills` from `ToolSpecProvider.get_callable_specs`.
- `sebastian/core/agent_loop.py`
  - Remove `allowed_skills` state and calls.
- `sebastian/core/stream_helpers.py`
  - Remove `allowed_skills` and `skill_specs_snapshot` dispatch plumbing.
- `sebastian/core/base_agent.py`
  - Remove `allowed_skills`, Skill snapshot/reload prompt rebuilding, and replace `## Available Skills` with fixed bootstrap.
- `sebastian/agents/_loader.py`
  - Remove `AgentConfig.allowed_skills`; fail fast if `allowed_skills` appears in a manifest.
- `sebastian/agents/aide/manifest.toml`
- `sebastian/agents/forge/manifest.toml`
  - Delete `allowed_skills = []`.
- `sebastian/capabilities/skills/skill_manager/SKILL.md`
  - Update command guidance to `search` local default, `show --body`, `read`, and mutation-only-on-user-request.

Primary tests:

- `tests/unit/runtime/test_skills_cli.py`
- `tests/unit/skills_registry/test_installer.py`
- `tests/unit/capabilities/test_registry_filtering.py`
- `tests/unit/capabilities/test_capability_registry.py`
- `tests/unit/capabilities/test_skills_loader.py`
- `tests/unit/capabilities/test_skill_hot_reload.py`
- `tests/unit/core/test_prompt_builder.py`
- `tests/unit/core/test_agent_loop.py`
- `tests/unit/core/test_stream_helpers.py`
- `tests/unit/identity/test_policy_gate.py`
- `tests/unit/agents/test_agent_loader.py`

Docs:

- `README.md`
- `sebastian/README.md`
- `sebastian/capabilities/README.md`
- `sebastian/capabilities/tools/README.md`
- `sebastian/capabilities/skills/README.md`
- `sebastian/cli/README.md`
- `sebastian/agents/README.md`
- `sebastian/agents/forge/README.md`
- `sebastian/permissions/README.md`
- `docs/architecture/spec/capabilities/skill-package-manager.md`
- `docs/architecture/spec/core/system-prompt.md`
- `docs/architecture/spec/agents/permission.md`
- `docs/architecture/spec/overview/architecture.md`
- `docs/architecture/spec/overview/three-tier-agent.md`
- `docs/architecture/spec/agents/code-agent.md`
- spec index pages that mention `allowed_skills` or `skill__<name>` as callable tools
- `CHANGELOG.md`

## Implementation Notes

- Use PyCharm MCP for codebase search and navigation before falling back to shell search.
- Keep edits tightly scoped. Do not add a native Skill read tool.
- Do not whitelist Skill directories in generic `Read`.
- Do not make registry search the default.
- Keep `Bash` availability conditional on `allowed_tools`; do not inject `Bash` into all Agents.
- Existing package-manager install/update/remove behavior should continue to work.
- Use explicit file staging. Do not use `git add .`.

---

### Task 1: Local Skill Detail Model, Listing, And Safe Reads

**Files:**

- Modify: `sebastian/skills_registry/models.py`
- Modify: `sebastian/skills_registry/installer.py`
- Test: `tests/unit/skills_registry/test_installer.py`

- [ ] **Step 1: Add failing tests for local detail shape**

Add tests that create a Skill directory with:

```text
SKILL.md
references/notes.md
scripts/helper.py
.sebastian-origin.json
.hidden
.sebastian/private.json
link-out -> /tmp/outside.txt
```

Expected assertions:

```python
detail = show_local_skill("weather", tmp_path, builtin_dir=builtin_root)
assert detail.slug == "weather"
assert detail.name == "weather"
assert detail.registered_name == "skill__weather"
assert "references/notes.md" in detail.files
assert "scripts/helper.py" in detail.files
assert ".sebastian-origin.json" not in detail.files
assert ".hidden" not in detail.files
assert ".sebastian/private.json" not in detail.files
```

- [ ] **Step 2: Add failing tests for deterministic lookup**

Cover:

- slug wins over frontmatter name
- frontmatter name wins over registered-name compatibility
- `skill__weather` input normalizes to `weather`
- ambiguous matches fail with candidate slugs

Run:

```bash
pytest tests/unit/skills_registry/test_installer.py -k "show_local_skill or lookup" -v
```

Expected: FAIL because the model has no `name/files`, and lookup order still follows current behavior.

- [ ] **Step 3: Add failing tests for `read_local_skill_file()`**

Add tests for:

- reads `references/notes.md`
- rejects `/absolute/path`
- rejects `..`
- rejects `.sebastian-origin.json`
- rejects `.hidden`
- rejects `.sebastian/private.json`
- rejects symlink escape
- rejects directories
- rejects invalid UTF-8
- rejects files over 128 KiB

Use an expected exception of `SkillInstallError`.

Run:

```bash
pytest tests/unit/skills_registry/test_installer.py -k "read_local_skill_file" -v
```

Expected: FAIL because the function does not exist.

- [ ] **Step 4: Extend models**

In `sebastian/skills_registry/models.py`, update `LocalSkillDetail`:

```python
@dataclass(frozen=True)
class LocalSkillDetail:
    slug: str
    name: str
    registered_name: str
    description: str
    body: str
    files: tuple[str, ...]
    version: str | None
    registry: str | None
    managed: bool
    source: str
    path: Path
```

- [ ] **Step 5: Implement file exclusion helpers**

In `installer.py`, add constants and helpers near local Skill helpers:

```python
MAX_LOCAL_SKILL_READ_BYTES = 128 * 1024
MANAGER_OWNED_NAMES = {".sebastian-origin.json", ".sebastian-skills.lock.json"}
MANAGER_OWNED_DIRS = {".sebastian"}
```

Add helpers:

```python
def _is_hidden_or_manager_owned(relative: Path) -> bool:
    parts = relative.parts
    return any(part.startswith(".") for part in parts) or any(
        part in MANAGER_OWNED_NAMES or part in MANAGER_OWNED_DIRS for part in parts
    )
```

If the hidden check already covers manager-owned names, keep manager constants anyway for readability.

- [ ] **Step 6: Implement stable file listing**

Add:

```python
def _list_skill_files(skill_dir: Path) -> tuple[str, ...]:
    rows: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        relative = path.relative_to(skill_dir)
        if _is_hidden_or_manager_owned(relative):
            continue
        if path.is_dir() and not path.is_symlink():
            continue
        label = relative.as_posix()
        if path.is_symlink():
            label = f"{label} -> symlink"
        rows.append(label)
    return tuple(rows)
```

Do not follow symlinks for listing.

- [ ] **Step 7: Rewrite local Skill lookup**

Keep `_find_local_skill_matches()` or replace it with a clearer helper that returns matches by priority:

```python
def _find_local_skill_matches(identifier: str, installed: list[InstalledSkill]) -> list[InstalledSkill]:
    normalized = identifier[7:] if identifier.startswith("skill__") else identifier
    slug_matches = [skill for skill in installed if skill.slug == identifier]
    if slug_matches:
        return slug_matches
    name_matches = [skill for skill in installed if _skill_name(skill) == normalized]
    if name_matches:
        return name_matches
    return [skill for skill in installed if skill.registered_name == identifier]
```

Prefer parsing current `SKILL.md` for `name` so disk content is authoritative.

- [ ] **Step 8: Update `show_local_skill()`**

Return `name` and `files`, while still returning `body` for `show --body`.

Ensure parse errors still raise `SkillInstallError("Invalid local Skill metadata at ...")`.

- [ ] **Step 9: Implement `read_local_skill_file()`**

Add:

```python
def read_local_skill_file(identifier: str, relative_path: str, root: Path, *, builtin_dir: Path | None = None) -> str:
    ...
```

Rules:

- `Path(relative_path).is_absolute()` fails.
- empty, `.`, `..`, any `..` part fails.
- hidden/manager-owned relative path fails.
- resolve root and target.
- use `target.relative_to(skill_root_resolved)` to enforce containment.
- `target.is_file()` and not special.
- `target.stat().st_size <= MAX_LOCAL_SKILL_READ_BYTES`.
- `target.read_text(encoding="utf-8")`.

- [ ] **Step 10: Run focused tests**

Run:

```bash
pytest tests/unit/skills_registry/test_installer.py -k "show_local_skill or read_local_skill_file or lookup" -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add sebastian/skills_registry/models.py sebastian/skills_registry/installer.py tests/unit/skills_registry/test_installer.py
git commit -m "feat(skills): 收口本地 Skill 读取边界" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 2: CLI `show/read/search` Progressive Disclosure

**Files:**

- Modify: `sebastian/cli/skills.py`
- Test: `tests/unit/runtime/test_skills_cli.py`

- [ ] **Step 1: Add failing tests for `show` default vs `--body`**

Update the existing `test_show_prints_local_skill_instructions` into two tests:

```python
def test_show_prints_metadata_and_files_without_body(...):
    ...
    result = runner.invoke(app, ["skills", "show", "weather"])
    assert "Use this for weather." not in result.output
    assert "Files:" in result.output
    assert "references/notes.md" in result.output

def test_show_body_prints_instructions(...):
    ...
    result = runner.invoke(app, ["skills", "show", "weather", "--body"])
    assert "Instructions:" in result.output
    assert "Use this for weather." in result.output
```

Run:

```bash
pytest tests/unit/runtime/test_skills_cli.py -k "show" -v
```

Expected: FAIL because current `show` always prints body and no files.

- [ ] **Step 2: Add failing tests for CLI `read`**

Mock `skills.read_local_skill_file`:

```python
def fake_read(identifier: str, relative_path: str, root: Path) -> str:
    assert identifier == "weather"
    assert relative_path == "references/notes.md"
    return "notes"
```

Assert:

```python
result = runner.invoke(app, ["skills", "read", "weather", "references/notes.md"])
assert result.exit_code == 0
assert "notes" in result.output
```

Run:

```bash
pytest tests/unit/runtime/test_skills_cli.py -k "read" -v
```

Expected: FAIL because command does not exist.

- [ ] **Step 3: Add failing tests for local-default search**

Add tests:

- default `skills search weather` uses local list and does not call `RegistryClient`
- `--source local` same
- `--source registry` calls registry
- `--source all` prints both `LOCAL` and `REGISTRY`
- `--registry` with default/local source does not call registry

Use monkeypatch on `skills.list_installed` and `skills.RegistryClient`.

Run:

```bash
pytest tests/unit/runtime/test_skills_cli.py -k "search" -v
```

Expected: FAIL because current search always calls registry.

- [ ] **Step 4: Add source enum**

In `skills.py`:

```python
from enum import StrEnum

class SearchSource(StrEnum):
    LOCAL = "local"
    REGISTRY = "registry"
    ALL = "all"
```

- [ ] **Step 5: Implement local search helper**

Add:

```python
def search_local(query: str) -> list[InstalledSkill]:
    normalized = query.lower()
    return [
        skill for skill in list_installed()
        if normalized in skill.slug.lower()
        or normalized in skill.registered_name.lower()
    ]
```

If Task 1 added `name` to `InstalledSkill`, include it. If not, keep slug/registered_name/description where available.

- [ ] **Step 6: Update search command**

Change signature:

```python
def search(
    query: str,
    source: SearchSource = typer.Option(SearchSource.LOCAL, "--source"),
    registry: str | None = typer.Option(None, "--registry", help="Registry base URL"),
) -> None:
```

Print local section for `LOCAL` and `ALL`; registry section for `REGISTRY` and `ALL`.

- [ ] **Step 7: Update show output**

Change `_print_local_detail(detail, *, include_body: bool)`:

```python
typer.echo(f"Slug: {detail.slug}")
typer.echo(f"Name: {detail.name}")
typer.echo(f"Registered: {detail.registered_name}")
...
typer.echo("Files:")
for file in detail.files:
    typer.echo(f"- {file}")
if include_body:
    typer.echo("")
    typer.echo("Instructions:")
    typer.echo(detail.body or "-")
```

Add `body: bool = typer.Option(False, "--body")` to `show()`.

- [ ] **Step 8: Add `read` command**

Import `read_local_skill_file`.

```python
@app.command()
def read(identifier: str, relative_path: str) -> None:
    content = _run_or_exit(lambda: read_local_skill_file(identifier, relative_path, settings.skills_extensions_dir))
    typer.echo(content)
```

- [ ] **Step 9: Run focused CLI tests**

Run:

```bash
pytest tests/unit/runtime/test_skills_cli.py -k "skills or search or show or read" -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add sebastian/cli/skills.py tests/unit/runtime/test_skills_cli.py
git commit -m "feat(cli): 渐进式读取本地 Skill 内容" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 3: Remove Skill Specs From Capability Registry And PolicyGate

**Files:**

- Modify: `sebastian/capabilities/registry.py`
- Modify: `sebastian/permissions/gate.py`
- Modify: `sebastian/permissions/types.py`
- Modify: `sebastian/core/protocols.py`
- Test: `tests/unit/capabilities/test_registry_filtering.py`
- Test: `tests/unit/capabilities/test_capability_registry.py`
- Test: `tests/unit/identity/test_policy_gate.py`

- [ ] **Step 1: Rewrite registry filtering tests first**

In `test_registry_filtering.py`, replace skill assertions with:

```python
def test_registry_has_no_skill_registration_api() -> None:
    reg = CapabilityRegistry()
    assert not hasattr(reg, "register_skill_specs")
    assert not hasattr(reg, "replace_skill_specs")
    assert not hasattr(reg, "get_skill_specs")
```

Add:

```python
def test_get_callable_specs_returns_only_tools() -> None:
    reg = _make_registry()
    specs = reg.get_callable_specs(allowed_tools=ALL_TOOLS)
    names = {s["name"] for s in specs}
    assert {"mcp_tool_a", "mcp_tool_b"} <= names
    assert "research_skill" not in names
```

Run:

```bash
pytest tests/unit/capabilities/test_registry_filtering.py -v
```

Expected: FAIL because skill APIs still exist.

- [ ] **Step 2: Add PolicyGate signature tests**

Update any tests that call:

```python
gate.get_callable_specs(allowed_tools, allowed_skills)
```

to call:

```python
gate.get_callable_specs(allowed_tools)
```

Add a runtime test that a `skill__name` call is unknown unless native/MCP registers it.

Run:

```bash
pytest tests/unit/identity/test_policy_gate.py -k "skill or callable or allowed" -v
```

Expected: FAIL until implementation removes skill branch.

- [ ] **Step 3: Remove Skill fields from permission types**

In `permissions/types.py`:

- delete `SkillAllowlist`
- delete `SkillSpecSnapshot`
- delete `ToolCallContext.allowed_skills`
- delete `ToolCallContext.skill_specs_snapshot`

- [ ] **Step 4: Remove skill APIs from registry**

In `capabilities/registry.py`:

- remove `self._skill_tools`
- remove `get_skill_specs`
- change `get_callable_specs(self, allowed_tools=None)` to return `get_tool_specs(allowed_tools)`
- remove `register_skill_specs`
- remove `replace_skill_specs`
- remove `is_skill`
- remove skill branch from `call`

`get_all_tool_specs()` should continue:

```python
return self.get_callable_specs(allowed_tools=ALL_TOOLS)
```

- [ ] **Step 5: Remove skill handling from PolicyGate**

In `permissions/gate.py`:

- change `get_callable_specs(self, allowed_tools=None)`
- remove `_is_skill`, `_skill_snapshot`, `_skill_allowed` if present
- remove skill branch in `call`
- keep native/MCP reason injection behavior unchanged

- [ ] **Step 6: Update ToolSpecProvider**

In `core/protocols.py`:

```python
def get_callable_specs(self, allowed_tools: ToolAllowlist = None) -> list[dict[str, Any]]: ...
```

- [ ] **Step 7: Run focused runtime tests**

Run:

```bash
pytest tests/unit/capabilities/test_registry_filtering.py tests/unit/capabilities/test_capability_registry.py tests/unit/identity/test_policy_gate.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/capabilities/registry.py sebastian/permissions/gate.py sebastian/permissions/types.py sebastian/core/protocols.py tests/unit/capabilities/test_registry_filtering.py tests/unit/capabilities/test_capability_registry.py tests/unit/identity/test_policy_gate.py
git commit -m "refactor(runtime): 移除 Skill provider tool 链路" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 4: Remove Skill Snapshot Plumbing From Agent Runtime

**Files:**

- Modify: `sebastian/core/agent_loop.py`
- Modify: `sebastian/core/stream_helpers.py`
- Modify: `sebastian/core/base_agent.py`
- Test: `tests/unit/core/test_agent_loop.py`
- Test: `tests/unit/core/test_stream_helpers.py`
- Test: `tests/unit/core/test_prompt_builder.py`
- Test: `tests/unit/core/test_base_agent.py`

- [ ] **Step 1: Update AgentLoop tests**

Change expectations:

```python
registry.get_callable_specs.assert_called_once_with(allowed_tools={"Read"})
registry.get_callable_specs.assert_called_once_with(allowed_tools=None)
registry.get_callable_specs.assert_called_once_with(allowed_tools=ALL_TOOLS)
```

Remove all `allowed_skills=None` constructor and assertion arguments.

Run:

```bash
pytest tests/unit/core/test_agent_loop.py -k "allowed_tools or snapshot" -v
```

Expected: FAIL until runtime signature changes.

- [ ] **Step 2: Update stream helper tests**

Delete `test_dispatch_tool_call_passes_allowed_skills_to_tool_context` or rewrite it as:

```python
async def test_dispatch_tool_call_context_has_only_allowed_tools() -> None:
    ...
    await dispatch_tool_call(..., allowed_tools=["Read"], pending_blocks={})
    assert captured_context.allowed_tools == frozenset({"Read"})
    assert not hasattr(captured_context, "allowed_skills")
```

Run:

```bash
pytest tests/unit/core/test_stream_helpers.py -k "allowed" -v
```

Expected: FAIL until implementation removes fields.

- [ ] **Step 3: Update prompt tests**

Replace skill prompt tests with:

```python
async def test_base_agent_prompt_includes_skill_management_bootstrap(...):
    assert "## Skill Management" in agent.system_prompt
    assert "sebastian skills show <name-or-slug> --body" in agent.system_prompt
    assert "Do not use generic Read to access Skill directories" in agent.system_prompt

async def test_base_agent_prompt_does_not_include_installed_skill_bodies(...):
    reg = CapabilityRegistry()
    # Do not register skills; this is now impossible.
    assert "Travel skill" not in agent.system_prompt
```

Remove class-level `allowed_skills` declarations from test agents.

Run:

```bash
pytest tests/unit/core/test_prompt_builder.py -v
```

Expected: FAIL until bootstrap implementation lands.

- [ ] **Step 4: Update AgentLoop**

In `agent_loop.py`:

- remove constructor `allowed_skills`
- remove `self._allowed_skills`
- call `self._tool_provider.get_callable_specs(allowed_tools=self._allowed_tools)`

- [ ] **Step 5: Update stream helper dispatch signature**

In `stream_helpers.py`:

- remove `allowed_skills` parameter
- remove `skill_specs_snapshot` parameter
- stop populating those fields on `ToolCallContext`

- [ ] **Step 6: Update BaseAgent fields and snapshots**

In `base_agent.py`:

- remove class attr and constructor param `allowed_skills`
- remove assignment logic
- remove `_skills_section()` dynamic Skill listing
- add `_skill_management_section()` returning fixed bootstrap
- include this section in `build_system_prompt`
- remove `allowed_skills_snapshot`
- call `self._gate.get_callable_specs(_normalize_allowed_tools(self.allowed_tools))`
- remove `skill_specs_snapshot`
- remove `_skill_prompt_version` and skill prompt version rebuild logic if no longer needed
- keep `Bash` in `Sebastian.allowed_tools`, `forge`, and `aide`

Bootstrap text must include:

```text
## Skill Management
For Sebastian Skill-related requests, use Bash with:
...
`install`, `update`, and `remove` are mutation commands. Use them only when the user explicitly asks to manage installed Skills.
Skill management is the exception to the general "prefer Read over Bash for file reads" rule.
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/unit/core/test_agent_loop.py tests/unit/core/test_stream_helpers.py tests/unit/core/test_prompt_builder.py tests/unit/core/test_base_agent.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/core/agent_loop.py sebastian/core/stream_helpers.py sebastian/core/base_agent.py tests/unit/core/test_agent_loop.py tests/unit/core/test_stream_helpers.py tests/unit/core/test_prompt_builder.py tests/unit/core/test_base_agent.py
git commit -m "refactor(core): 移除 Skill 快照与 prompt 注入" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 5: Agent Manifest Migration And Fail-Fast Loader

**Files:**

- Modify: `sebastian/agents/_loader.py`
- Modify: `sebastian/agents/aide/manifest.toml`
- Modify: `sebastian/agents/forge/manifest.toml`
- Test: `tests/unit/agents/test_agent_loader.py`
- Test: `tests/unit/agents/test_agents_loader.py`

- [ ] **Step 1: Add failing loader tests**

In `tests/unit/agents/test_agent_loader.py`, update `AgentConfig` tests:

```python
field_names = {f.name for f in dataclasses.fields(AgentConfig)}
assert "allowed_skills" not in field_names
```

Add:

```python
def test_load_agents_rejects_allowed_skills(tmp_path: Path) -> None:
    _write_agent(..., 'allowed_skills = []\n')
    with pytest.raises(ValueError, match="allowed_skills is no longer supported"):
        load_agents(extra_dirs=[tmp_path])
```

Run:

```bash
pytest tests/unit/agents/test_agent_loader.py -k "allowed_skills or allowed_tools" -v
```

Expected: FAIL because field still exists and loader accepts it.

- [ ] **Step 2: Remove field and reject manifest key**

In `_loader.py`:

- remove `allowed_skills` from `AgentConfig`
- after reading `agent_section`, add:

```python
if "allowed_skills" in agent_section:
    raise ValueError(f"{manifest_path}: allowed_skills is no longer supported; Skill access is via Bash + sebastian skills CLI")
```

- remove `raw_skills`
- remove `allowed_skills=...` when building `AgentConfig`

- [ ] **Step 3: Remove built-in manifest fields**

Delete:

```toml
allowed_skills = []
```

from:

- `sebastian/agents/aide/manifest.toml`
- `sebastian/agents/forge/manifest.toml`

- [ ] **Step 4: Run agent loader tests**

Run:

```bash
pytest tests/unit/agents/test_agent_loader.py tests/unit/agents/test_agents_loader.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/agents/_loader.py sebastian/agents/aide/manifest.toml sebastian/agents/forge/manifest.toml tests/unit/agents/test_agent_loader.py tests/unit/agents/test_agents_loader.py
git commit -m "refactor(agents): 删除 allowed_skills manifest 语义" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 6: Skill Loader And Hot Reload Simplification

**Files:**

- Modify: `sebastian/capabilities/skills/_loader.py`
- Modify: `sebastian/capabilities/skills/hot_reload.py`
- Test: `tests/unit/capabilities/test_skills_loader.py`
- Test: `tests/unit/capabilities/test_skill_hot_reload.py`

- [ ] **Step 1: Rewrite loader tests around catalog metadata**

Current `test_skills_loader.py` expects tool specs. Replace with catalog expectations:

```python
catalog = load_skill_catalog(builtin_dir=tmp_path, extra_dirs=[])
assert catalog[0].name == "travel"
assert catalog[0].registered_name == "skill__travel"
assert catalog[0].description == "Travel"
assert catalog[0].path == tmp_path / "travel"
```

Run:

```bash
pytest tests/unit/capabilities/test_skills_loader.py -v
```

Expected: FAIL because `load_skill_catalog` does not exist.

- [ ] **Step 2: Implement catalog loader**

In `_loader.py`:

```python
@dataclass(frozen=True)
class SkillCatalogEntry:
    slug: str
    name: str
    registered_name: str
    description: str
    path: Path
    source: str
```

Add:

```python
def load_skill_catalog(builtin_dir: Path | None = None, extra_dirs: list[Path] | None = None) -> list[SkillCatalogEntry]:
    ...
```

Do not include `metadata.body`. Do not return `input_schema`.

Temporarily keep `load_skills` only if needed by older tests, but prefer deleting all runtime use in this task. If kept, mark it as compatibility for tests only and remove provider-tool behavior.

- [ ] **Step 3: Simplify hot reload tests**

Rewrite `test_skill_hot_reload.py` so it only verifies fingerprint behavior, not registry mutation:

- unchanged returns `changed=False`
- editing `SKILL.md` returns `changed=True` and increments version
- adding scripts does not trigger change
- failures retry

Remove assertions like:

```python
reg.get_skill_specs()
reg.replace_skill_specs(...)
```

- [ ] **Step 4: Simplify or remove `SkillHotReloader` registry dependency**

In `hot_reload.py`:

- remove `registry: CapabilityRegistry` constructor dependency
- remove `load_skills` import
- make `maybe_reload()` update only fingerprint/version
- or delete `SkillHotReloader` if no runtime code uses it after Task 4

Prefer keeping a tiny fingerprint helper only if tests/docs still find it useful.

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest tests/unit/capabilities/test_skills_loader.py tests/unit/capabilities/test_skill_hot_reload.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/capabilities/skills/_loader.py sebastian/capabilities/skills/hot_reload.py tests/unit/capabilities/test_skills_loader.py tests/unit/capabilities/test_skill_hot_reload.py
git commit -m "refactor(skills): 将 loader 收口为本地 catalog" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 7: Builtin Skill Manager And Documentation

**Files:**

- Modify: `sebastian/capabilities/skills/skill_manager/SKILL.md`
- Modify: `README.md`
- Modify: `sebastian/README.md`
- Modify: `sebastian/capabilities/README.md`
- Modify: `sebastian/capabilities/tools/README.md`
- Modify: `sebastian/capabilities/skills/README.md`
- Modify: `sebastian/cli/README.md`
- Modify: `sebastian/agents/README.md`
- Modify: `sebastian/agents/forge/README.md`
- Modify: `sebastian/permissions/README.md`
- Modify: `docs/architecture/spec/capabilities/skill-package-manager.md`
- Modify: `docs/architecture/spec/core/system-prompt.md`
- Modify: `docs/architecture/spec/agents/permission.md`
- Modify: `docs/architecture/spec/overview/architecture.md`
- Modify: `docs/architecture/spec/overview/three-tier-agent.md`
- Modify: `docs/architecture/spec/agents/code-agent.md`
- Modify: index docs that mention removed semantics
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Search doc references**

Use PyCharm MCP text search first:

- `allowed_skills`
- `skill__`
- `prompt/tool snapshot`
- `Skill registry`
- `SkillHotReloader`
- `sebastian skills search`
- `sebastian skills show`

- [ ] **Step 2: Update `skill_manager/SKILL.md`**

Required guidance:

```markdown
Use this Skill for Sebastian Skill-related requests.

Use:
- `sebastian skills list`
- `sebastian skills search <query>` (local by default)
- `sebastian skills search <query> --source registry` only when finding new Skills to install
- `sebastian skills show <name-or-slug>`
- `sebastian skills show <name-or-slug> --body`
- `sebastian skills read <name-or-slug> <relative-path>`

Do not treat registry inspect/search output as local installed usage instructions.
Install/update/remove only when the user explicitly asks to manage installed Skills.
```

- [ ] **Step 3: Update root README command examples**

Change:

```bash
sebastian skills search flight     # Search the Skill registry
```

to:

```bash
sebastian skills search flight     # Search local installed Skills
sebastian skills search flight --source registry
```

Mention `show --body` and `read`.

- [ ] **Step 4: Update capability and Skill docs**

Replace all Skill-as-tool wording:

- no `skill__<name>` provider tool
- no `allowed_skills`
- no prompt/tool snapshot refresh
- no Skill registry mutation inside `CapabilityRegistry`
- Skill content uses CLI reads

- [ ] **Step 5: Update permissions/tools docs**

Clarify:

- permission model covers executable tools only
- Skill CLI access requires `Bash`
- generic `Read` should not be used for Skill directories
- `Bash` remains controlled by `allowed_tools` and `PolicyGate`

- [ ] **Step 6: Update architecture docs**

Remove `allowed_skills = []` examples from:

- `docs/architecture/spec/overview/architecture.md`
- `docs/architecture/spec/overview/three-tier-agent.md`
- `docs/architecture/spec/agents/code-agent.md`

Update:

- `docs/architecture/spec/core/system-prompt.md` with Skill bootstrap
- `docs/architecture/spec/agents/permission.md` with tools-only policy chain
- index descriptions that mention Skill allowlists

- [ ] **Step 7: Update CHANGELOG**

Under `[Unreleased]`, add `Changed` entries:

```markdown
### Changed
- Skill 不再作为 LLM tool 暴露，Sebastian 改为通过 `sebastian skills show/read` 按需读取本地 Skill 内容。
- `sebastian skills search` 默认搜索本地已安装 Skill，远端 registry 搜索需要显式 `--source registry`。
```

- [ ] **Step 8: Run doc/reference search**

Run PyCharm searches again and ensure remaining `allowed_skills` references are only historical in the new spec or removed entirely from active docs.

- [ ] **Step 9: Commit docs**

```bash
git add README.md sebastian/README.md sebastian/capabilities/README.md sebastian/capabilities/tools/README.md sebastian/capabilities/skills/README.md sebastian/cli/README.md sebastian/agents/README.md sebastian/agents/forge/README.md sebastian/permissions/README.md sebastian/capabilities/skills/skill_manager/SKILL.md docs/architecture/spec/capabilities/skill-package-manager.md docs/architecture/spec/core/system-prompt.md docs/architecture/spec/agents/permission.md docs/architecture/spec/overview/architecture.md docs/architecture/spec/overview/three-tier-agent.md docs/architecture/spec/agents/code-agent.md CHANGELOG.md
git commit -m "docs(skills): 更新 Skill 渐进披露运行时说明" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

If index files changed, include them explicitly in `git add`.

---

### Task 8: Full Verification And Graph Update

**Files:**

- Modify if needed: files discovered by verification
- Generated/update: `graphify-out/` if graph rebuild changes tracked files

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
pytest tests/unit/skills_registry/test_installer.py tests/unit/runtime/test_skills_cli.py tests/unit/capabilities/test_registry_filtering.py tests/unit/capabilities/test_capability_registry.py tests/unit/capabilities/test_skills_loader.py tests/unit/capabilities/test_skill_hot_reload.py tests/unit/core/test_prompt_builder.py tests/unit/core/test_agent_loop.py tests/unit/core/test_stream_helpers.py tests/unit/identity/test_policy_gate.py tests/unit/agents/test_agent_loader.py tests/unit/agents/test_agents_loader.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader backend unit suite**

Run:

```bash
pytest tests/unit -q
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```bash
ruff check sebastian/ tests/
```

Expected: PASS.

If formatting is needed:

```bash
ruff format sebastian/ tests/
ruff check sebastian/ tests/
```

- [ ] **Step 4: Run type check**

Run:

```bash
mypy sebastian/
```

Expected: PASS.

- [ ] **Step 5: Run graphify rebuild**

Project rule requires graph update after code changes:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: exits 0.

- [ ] **Step 6: Inspect git status**

Run:

```bash
git status --short
```

Expected: only intentional files changed.

- [ ] **Step 7: Commit verification fallout if any**

If graphify or formatting changed files:

```bash
git add <specific-files>
git commit -m "chore(skills): 收口 Skill 渐进披露验证残留" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

- [ ] **Step 8: Final implementation summary**

Summarize:

- runtime Skill tools removed
- CLI progressive disclosure added
- docs updated
- verification commands and results

---

## Handoff Checklist

Before implementation starts:

- [ ] Confirm branch/worktree is correct and clean.
- [ ] Read `docs/superpowers/specs/2026-05-08-skill-progressive-disclosure-design.md`.
- [ ] Read `sebastian/README.md`, `sebastian/capabilities/README.md`, `sebastian/capabilities/skills/README.md`, and `sebastian/cli/README.md`.
- [ ] Use PyCharm MCP for Python symbol/text lookup before shell search.
- [ ] Keep each task independently commit-ready.
- [ ] Do not reintroduce a model-visible Skill tool.
