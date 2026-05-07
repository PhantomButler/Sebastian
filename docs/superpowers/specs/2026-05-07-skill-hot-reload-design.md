---
version: "1.0"
last_updated: 2026-05-07
status: planned
---

# Skill Hot Reload on New Session Design

## Background

Sebastian already supports skill extension directories:

- Built-in skills: `sebastian/capabilities/skills/`
- User skills: `<data_dir>/extensions/skills/`

At gateway startup, `load_skills()` scans these directories and registers each `SKILL.md`
as a `skill__<name>` capability. This lets users add instruction-based skills without
modifying core code.

The current limitation is lifecycle: skill specs are loaded only at process startup, and
each agent builds `system_prompt` only once during initialization. A user can update a
skill script and have `Bash` execute the latest file, but adding/removing a skill or
editing `SKILL.md` requires restarting Sebastian before the model sees the new skill
instructions.

This matters for script-backed skills such as `flight_search`, where the desired extension
model is:

```text
<data_dir>/extensions/skills/flight_search/
├── SKILL.md
└── scripts/
    └── search_flights.py
```

The skill should be installable and updatable from the user data directory without shipping
a new Sebastian version or growing the internal native tool list.

## Goals

1. Load newly added, changed, or deleted skills without restarting the gateway.
2. Avoid adding a model-visible management tool such as `reload_skills`.
3. Avoid scanning skill directories on every turn.
4. Reload only at a stable lifecycle boundary: before the first turn of a new session.
5. Rebuild only the current agent's prompt when skill specs change.
6. Keep tool specs and the `## Available Skills` prompt section consistent within a turn.
7. Preserve script-backed skill behavior: scripts are executed fresh by `Bash` and do not
   need skill registry reload when their contents change.

## Non-Goals

- No background file watcher.
- No every-turn scan.
- No new model-visible native tool for skill refresh.
- No native `search_flights` tool in core.
- No immediate refresh for existing sessions.
- No fingerprinting of arbitrary files under a skill directory, including `scripts/*.py`.
- No App settings UI or management API for manual refresh in this phase.

## Design Summary

Add an internal `SkillHotReloader` service. It fingerprints all discovered `SKILL.md` files,
reloads skills only when the fingerprint changes, and is invoked before the first LLM turn
of each new agent/session pair.

When a change is detected:

1. Reload skill specs from built-in and user extension directories.
2. Replace the registry's current skill specs atomically.
3. Advance a monotonic skill registry version.
4. Rebuild only the current agent type singleton's `system_prompt`.
5. Continue the turn using the updated prompt and callable skill specs.

The reloader is not exposed to the model. It is runtime infrastructure, not a tool.

Even when no reload occurs, the current agent still compares its prompt's skill version
against the reloader's current version. If another agent reloaded skills earlier, this
new-session check catches the current agent up before its provider request starts.

## Components

### `SkillHotReloader`

Responsibility: detect `SKILL.md` changes and refresh registry skill specs.

State:

- `builtin_dir: Path`
- `extra_dirs: list[Path]`
- `registry: CapabilityRegistry`
- `_fingerprint: SkillFingerprint | None`
- `_version: int`
- `_lock: asyncio.Lock`

Public method:

```python
async def maybe_reload(self) -> SkillReloadResult:
    """Reload changed skills and return the current skill registry version."""
```

Result shape:

```python
@dataclass(frozen=True)
class SkillReloadResult:
    changed: bool
    version: int
    fingerprint: SkillFingerprint
```

Fingerprint input:

- Each discovered `SKILL.md` relative path
- `stat().st_mtime_ns`
- `stat().st_size`

This is intentionally narrow. Editing `scripts/search_flights.py` does not trigger reload;
the script is executed fresh each time by `Bash`.

The reloader must be constructed and seeded during gateway lifespan immediately after the
startup skill load. Startup and hot reload therefore share the same directories and initial
fingerprint. This avoids missing changes made after startup but before the first new session:
the first `maybe_reload()` compares against the startup fingerprint, not against a fresh
baseline captured at first use.

Version rules:

- Startup seed version is `0`.
- Each successful registry replacement increments `_version`.
- Agents use this version to decide whether their cached prompt reflects the latest skill
  registry state.

### `CapabilityRegistry.replace_skill_specs()`

Current `register_skill_specs()` stores skills and MCP tools in the same internal dictionary,
using `_skill_names` as the discriminator. Hot reload needs replacement semantics and
deterministic collision behavior.

First implementation should split skill storage from MCP storage:

```python
class CapabilityRegistry:
    _mcp_tools: dict[str, tuple[dict[str, Any], McpToolFn]]
    _skill_tools: dict[str, tuple[dict[str, Any], ToolFn]]
```

`get_tool_specs()` reads native + MCP tools. `get_skill_specs()` reads only `_skill_tools`.
This removes skill/MCP collision ambiguity and makes replacement a pure skill operation.

If a broader refactor is deferred, `replace_skill_specs()` must still explicitly preserve
non-skill MCP entries and include collision tests.

Add:

```python
def replace_skill_specs(self, specs: list[dict[str, Any]]) -> None:
    """Replace all currently registered skill specs with the provided set."""
```

Behavior:

1. Clear the skill-only storage.
2. Register the new specs using the same skill function behavior as existing registration.
3. Leave native and MCP tool registrations untouched.

This keeps deleted skills from lingering in the registry.

### Current-Agent Prompt Rebuild

`BaseAgent` currently builds `self.system_prompt` in `__init__`. Add a rebuild hook:

```python
def rebuild_system_prompt(self) -> None:
    self.system_prompt = self.build_system_prompt(self._gate)
```

Also add an agent-local prompt version marker:

```python
_skill_prompt_version: int = 0

def mark_skill_prompt_version(self, version: int) -> None:
    self._skill_prompt_version = version
```

`Sebastian` already has a specialized `rebuild_system_prompt()` because its prompt includes
the agent registry. It should keep that override:

```python
def rebuild_system_prompt(self) -> None:
    self.system_prompt = self.build_system_prompt(self._gate, self._agent_registry)
```

Agents are singleton instances per agent type, not per session. "Current agent" therefore
means the current agent type singleton handling this turn. Rebuilding it updates future
sessions for the same agent type, but it does not rebuild other agent type singletons.

Concurrent turns already running on the same singleton continue with the effective prompt
they assembled before their provider request. A rebuild affects later turns only.

### New-Session Trigger

Invoke skill hot reload before the first LLM turn of a new agent/session pair.

The trigger should live in `BaseAgent.run_streaming()` after the worker session is resolved
and before memory/todo prompt assembly. That location has access to:

- `session_id`
- current `agent_context`
- current agent instance
- session metadata

Preferred first-turn detection:

- Use persisted session/timeline state if a reliable exchange count or first-turn marker is
  already available.
- If no reliable persisted marker exists, use an in-memory set keyed by
  `(agent_context, session_id)` as the initial implementation.

The in-memory fallback is acceptable because the reloader's fingerprint check is cheap and
idempotent. After process restart, an old session may be treated as unseen once, but reload
still happens only if `SKILL.md` files changed.

Pseudo-flow:

```python
worker_session = await session_store.get_session_for_agent_type(session_id, agent_context)

if self._should_check_skills_for_new_session(worker_session, session_id, agent_context):
    result = await state.skill_hot_reloader.maybe_reload()
    if self._skill_prompt_version != result.version:
        self.rebuild_system_prompt()
        self.mark_skill_prompt_version(result.version)
```

The call must complete before the provider request starts.

## Data Flow

```text
User installs or edits SKILL.md
        │
        ▼
User starts a new conversation/session
        │
        ▼
BaseAgent.run_streaming resolves worker session
        │
        ▼
SkillHotReloader fingerprints SKILL.md files
        │
        ├── unchanged → compare current agent prompt version
        │
        └── changed
              │
              ▼
        load_skills()
              │
              ▼
        CapabilityRegistry.replace_skill_specs()
              │
              ▼
        advance skill registry version
              │
              ▼
        current agent type singleton rebuilds prompt if its prompt version is stale
              │
              ▼
        AgentLoop.stream() fetches callable specs from registry
```

The prompt's `## Available Skills` section and the LLM tool specs are therefore derived from
the same registry state for that turn.

## Concurrency

Multiple new sessions can start at nearly the same time. `SkillHotReloader.maybe_reload()`
uses an async lock so only one scan/reload can mutate the registry at a time.

Inside the lock:

1. Compute latest fingerprint.
2. Compare with cached fingerprint.
3. If unchanged, return the current version with `changed=False`.
4. If changed, load and replace skill specs, update cached fingerprint, increment version,
   and return the new version with `changed=True`.

Readers should not observe a partially updated skill registry because replacement happens
inside one synchronous registry method.

## Error Handling

If reload fails:

- Do not clear existing skill specs.
- Log a warning with enough path/error detail for debugging.
- Continue the current turn using the last known good registry and prompt.
- Return the last known good version so agents do not mark prompts as refreshed against a
  failed registry update.

Invalid individual skills should follow existing `load_skills()` behavior. This spec does
not add validation beyond the current loader rules.

## Testing

Unit coverage:

- `SkillHotReloader` returns `SkillReloadResult(changed=False, version=current)` when
  fingerprint is unchanged.
- Adding a `SKILL.md` returns `changed=True` and registers the new skill.
- Editing `SKILL.md` returns `changed=True` and updates the skill description/instructions.
- Deleting a skill returns `changed=True` and removes the old skill from registry specs.
- Editing a script file under `scripts/` does not trigger reload.
- Concurrent `maybe_reload()` calls do not produce duplicate or partial registry state.
- `CapabilityRegistry.replace_skill_specs()` removes deleted skills and preserves non-skill MCP/native entries.
- Skill/MCP name collisions are deterministic and do not delete or misclassify MCP tools.
- Startup seeds the initial fingerprint, so changes made after gateway startup but before
  the first new session are detected.

Agent-level coverage:

- New session first turn invokes hot reload check.
- Existing session subsequent turn does not invoke hot reload check.
- When reload changes specs, only the current agent type singleton's prompt is rebuilt.
- If another agent type already advanced the skill version, a later new session on this
  agent type rebuilds its prompt even when `maybe_reload()` returns `changed=False`.
- Sebastian's prompt rebuild keeps its sub-agent section.

## Future Work

- Add an App settings refresh button or management API when a skill marketplace exists.
- Add content hashing if `mtime_ns + size` proves unreliable on target filesystems.
- Add persisted first-turn detection if the current session model exposes a stable exchange
  count.
- Add skill installation UX that places skill directories under `<data_dir>/extensions/skills/`.
