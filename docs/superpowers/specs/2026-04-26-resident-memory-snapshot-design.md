---
version: "1.0"
last_updated: 2026-04-26
status: planned
---

# Resident Memory Snapshot Design

## 1. Background

Sebastian already has a long-term memory read path through `BaseAgent._memory_section()`.
That path is dynamic: every turn it looks at the latest user message, runs a lightweight
retrieval planner, fetches matching memory lanes, and injects the result into the system
prompt only for that turn.

This is useful for contextual recall, but it is not a reliable carrier for always-relevant
user profile information. If the current message does not trigger the planner, the model may
not see basic facts such as the user's preferred language, preferred form of address, or
response style. In practice the agent often falls back to the explicit `memory_search` tool,
which is appropriate for deep lookup but not for every-turn personalization.

This design introduces a separate resident memory path for stable, high-confidence user
profile facts. The existing dynamic retrieval path remains, but its responsibility becomes
clearer: it provides turn-specific historical evidence and context, not the user's baseline
profile.

## 2. Goals

- Always inject a small, stable memory section for high-confidence user profile facts.
- Keep SQLite memory tables as the only source of truth; snapshot files are derived caches.
- Avoid per-turn database reads for resident profile data.
- Preserve dynamic retrieval for turn-specific recall.
- Fit the install/data layout v2: generated memory files live under `settings.user_data_dir`.
- Defer pin management UI/API and natural-language "pin this" behavior.

## 3. Non-Goals

- No new `memory_pin` tool or REST API in this phase.
- No natural-language "固定记住这个" workflow in this phase.
- No automatic promotion from inferred memory to pinned memory in this phase.
- No resident injection for sensitive memory in this phase.
- No replacement of `memory_search`; explicit search remains the deep lookup path.

## 4. Terminology

### Resident Memory

Memory that is expected to affect most conversations with the owner. It is injected every
turn when available. Examples include reply language, response style, preferred name, and
basic profile facts.

### Dynamic Retrieved Memory

Memory selected for the current user message by the retrieval planner. It may include current
context, historical evidence, relation records, or profile records relevant to the latest turn.
It is ephemeral: if the next turn does not trigger the same lane, it will not appear again.

### Pinned Notes

Records tagged with `policy_tags=["pinned"]`. They are supported by the resident snapshot
renderer, but this phase does not implement any mechanism for creating or removing pins.

## 5. Architecture

The memory read plane becomes two explicit paths:

1. `resident_memory_section`
   - Reads a pre-rendered Markdown snapshot from disk.
   - Injects stable, high-confidence profile facts every turn.
   - Does not query the database on the hot path.

2. `dynamic_memory_section`
   - The existing `_memory_section()` behavior.
   - Runs planner -> lane fetch -> assemble for the latest user message.
   - Remains allowed to return an empty string.

Prompt assembly order:

```text
Base system prompt

## Resident Memory
...

## Retrieved Memory
...

## Session Todos
...
```

`BaseAgent._stream_inner()` should assemble the resident section before dynamic retrieval:

1. Build the base system prompt.
2. Read resident snapshot.
3. Run dynamic memory retrieval.
4. Read session todos.
5. Join non-empty sections in that order.

Resident injection uses the same high-level access boundary as long-term automatic memory
injection: owner conversations at Sebastian depth 1 only. Depth >= 2 agents do not receive
resident memory in their system prompts. If memory is disabled through memory settings,
resident memory is also omitted.

## 6. Snapshot Files

Resident memory snapshot files live under the user data directory:

```text
<settings.user_data_dir>/memory/resident_snapshot.md
<settings.user_data_dir>/memory/resident_snapshot.meta.json
```

Default install path:

```text
~/.sebastian/data/memory/resident_snapshot.md
~/.sebastian/data/memory/resident_snapshot.meta.json
```

The files are derived artifacts. They can be deleted and rebuilt from the database.

`resident_snapshot.md` is prompt-ready Markdown.

`resident_snapshot.meta.json` stores operational metadata:

```json
{
  "schema_version": 1,
  "generated_at": "2026-04-26T00:00:00Z",
  "snapshot_state": "ready",
  "generation_id": "01J...",
  "source_max_updated_at": "2026-04-26T00:00:00Z",
  "markdown_hash": "sha256:...",
  "record_hash": "sha256:...",
  "source_record_ids": ["..."],
  "record_count": 2
}
```

The reader must validate metadata before serving the Markdown file. Metadata is not only for
debugging: it is the freshness and safety gate for resident prompt injection.

`snapshot_state` values:

| State | Meaning | Reader behavior |
| --- | --- | --- |
| `ready` | Snapshot was successfully rebuilt from the current DB view. | May serve Markdown after validation. |
| `dirty` | A committed memory mutation may have changed resident eligibility. | Return empty and schedule rebuild. |
| `rebuilding` | Rebuild is in progress. | Return empty. |
| `error` | Last rebuild failed after the snapshot was dirtied. | Return empty. |

`record_hash` is a deterministic hash of the selected records' prompt-relevant fields:
`id`, `content`, `slot_id`, `kind`, `confidence`, `status`, `valid_from`, `valid_until`,
`policy_tags`, and `updated_at`. `source_max_updated_at` is the maximum `updated_at` among
selected records. `markdown_hash` is the SHA-256 hash of the exact Markdown file contents.

The metadata file is the commit pointer. The reader may serve Markdown only when:

```text
snapshot_state = "ready"
resident_snapshot.md exists
sha256(resident_snapshot.md bytes) == markdown_hash
```

This prevents a crash between Markdown and metadata writes from producing mixed served state.
The reader does not query SQLite on the hot path to prove freshness.

## 7. Selection Rules

SQLite remains the source of truth. The snapshot builder reads active memory records and
selects only high-confidence, low-risk entries.

Common filters:

```text
scope = "user"
subject_id = "owner"
status = "active"
confidence >= 0.8
valid_from is null or valid_from <= now
valid_until is null or valid_until > now
policy_tags does not contain "do_not_auto_inject"
policy_tags does not contain "needs_review"
policy_tags does not contain "sensitive"
```

A record enters the resident snapshot when it passes the common filters and either:

1. `slot_id` is in the resident profile allowlist.
2. `policy_tags` contains `pinned` and the pinned record satisfies the pinned eligibility
   contract below.

Initial resident profile allowlist:

```text
user.profile.name
user.profile.location
user.profile.occupation
user.preference.language
user.preference.response_style
user.preference.addressing
```

If any of these slots do not exist in the builtin slot registry, this feature should add them
as builtin slots. The allowlist must stay small. It must not include every preference slot,
because ordinary preferences such as food, entertainment, or shopping should not appear in
every system prompt.

Pinned records are not exempt from the common filters. A pinned sensitive or low-confidence
record is skipped in this phase.

Pinned eligibility contract for this phase:

```text
source is "explicit" or "system_derived"
content length <= 300 characters
content contains no Markdown heading markers
content contains no fenced code blocks
content contains no tool/system/developer instruction language
```

This phase does not provide pin creation or owner review UI. The pinned path is included only
so future reviewed pins can share the same snapshot mechanism. If existing manually seeded
pinned records do not meet this contract, the builder must skip them.

## 8. Rendering

The snapshot renderer outputs a compact section:

```markdown
## Resident Memory

### Core Profile
- 用户偏好使用中文交流。
- 用户偏好回答简洁、直接。

### Pinned Notes
- ...
```

Rules:

- Omit `Core Profile` when no allowlisted profile records pass filters.
- Omit `Pinned Notes` when no pinned records pass filters.
- Omit the entire file content when both sections are empty.
- Render each bullet as framed data, not as free-form instructions.
- Sort profile records by allowlist order, then by `updated_at` descending.
- Sort pinned records by `confidence` descending, then `updated_at` descending.
- Cap `Core Profile` at 8 records.
- Cap `Pinned Notes` at 10 records.
- Cap each rendered bullet at 300 characters.
- Strip Markdown headings, fenced code blocks, control characters, and leading list markers.

The caps keep the resident section small enough to be safe for every turn.

Bullet format:

```markdown
- Profile memory: 用户偏好使用中文交流。
- Pinned memory: ...
```

The wording must frame the content as memory data about the user, not as instructions that
override the system prompt. A record whose content still looks like an instruction after
normalization is skipped.

## 9. Refresh Lifecycle

Introduce `ResidentMemorySnapshotRefresher`.

Responsibilities:

- `rebuild()`
  - Query eligible profile records.
  - Render Markdown.
  - Write Markdown and metadata atomically.

- `mark_dirty()`
  - Mark that a refresh is needed after memory state changes.

- `schedule_refresh()`
  - Debounce refresh requests so clustered memory writes produce a single snapshot rewrite.

The refresher owns a process-local synchronization primitive called the resident snapshot
barrier. It can be implemented as an async read/write lock or equivalent service-level lock.
Both prompt-time resident reads and memory write dirty marking must participate in this
barrier:

- Resident reads acquire the read side before validating metadata and reading Markdown.
- Memory mutations acquire the write side from before DB commit through `mark_dirty()`.
- Snapshot publication acquires the write side before replacing ready metadata.

This barrier is intentionally process-local. Sebastian's current gateway runtime is a single
process; if future deployment supports multiple writer processes, this spec must be extended
with an inter-process lock or DB-backed revision protocol before enabling resident snapshots
in that mode.

Startup behavior:

1. `ensure_data_dir()` creates the data layout.
2. Gateway startup initializes memory storage.
3. The resident snapshot refresher performs one `rebuild()`.
4. Startup continues even if rebuild fails; the failure is logged and resident memory is
   omitted until a later successful refresh.

Write behavior:

1. A memory mutation that may affect resident eligibility acquires the resident snapshot
   barrier write side.
2. The memory write pipeline commits database changes.
3. Before the write API returns or releases the memory write service lock, the caller triggers
   `mark_dirty()`.
4. `mark_dirty()` immediately writes metadata with `snapshot_state = "dirty"` and replaces
   `resident_snapshot.md` with an empty file.
5. The refresher schedules a debounce refresh outside the transaction.

The refresher must not write snapshot files inside a database transaction. This avoids a
rolled-back database write leaving a stale file that appears newer than the true state.

The resident reader must never serve a stale pre-mutation snapshot after a committed mutation
that may affect resident eligibility. When in doubt, it returns an empty resident section
until a successful rebuild writes `snapshot_state = "ready"`.

The gap between DB commit and dirty metadata must be serialized by the resident snapshot
barrier. Prompt assembly may race with a mutation before the commit is visible, but it cannot
read resident snapshot files while a writer is between DB commit and `mark_dirty()`.

Ready snapshot writes use metadata as the final commit pointer:

1. Render Markdown bytes and compute `markdown_hash`.
2. Write `resident_snapshot.md.tmp`.
3. Replace `resident_snapshot.md`.
4. Write `resident_snapshot.meta.json.tmp` with `snapshot_state = "ready"`,
   `generation_id`, and `markdown_hash`.
5. Replace `resident_snapshot.meta.json`.

If the process crashes after step 3 and before step 5, the old metadata remains. Because the
reader verifies `markdown_hash`, it will not serve the new Markdown with old ready metadata.

Rebuild publication must also be versioned against dirty writes:

1. At rebuild start, read the current `dirty_generation` from the refresher.
2. Query DB and render Markdown without holding the write side.
3. Before publishing `ready` metadata, acquire the barrier write side.
4. Publish only if the current `dirty_generation` still equals the observed generation.
5. If the generation changed, discard the rendered snapshot and reschedule rebuild.

`mark_dirty()` increments `dirty_generation` before writing dirty metadata. This prevents an
in-flight rebuild based on an old DB view from overwriting a later dirty marker with stale
`ready` metadata.

## 10. Error Handling

Resident memory is an enhancement, not a hard dependency.

- Missing snapshot file: return an empty resident section.
- Snapshot read failure: log warning, return empty section.
- Metadata mismatch: write `snapshot_state = "dirty"` if possible, schedule rebuild, and
  return empty.
- Rebuild failure after dirty: write `snapshot_state = "error"` and an empty Markdown file;
  keep serving without resident memory.
- Empty eligible records: write empty Markdown and metadata with `record_count = 0`.

Dynamic retrieval failures keep existing behavior: `_memory_section()` logs and returns an
empty string.

Serving last-known-good resident memory is not allowed after the snapshot has been dirtied.
Last-known-good behavior is only acceptable if the metadata still says `ready` and no mutation
has marked the snapshot dirty.

## 11. Current `_memory_section()` Repositioning

`BaseAgent._memory_section()` currently acts as the only automatic memory injection hook. This
design narrows its meaning:

- It is the dynamic retrieved memory section.
- It is expected to be empty for many turns.
- It should not be judged responsible for stable user profile injection.
- It remains depth-gated to Sebastian depth 1.
- It remains separate from `memory_search`, which explicitly searches all lanes.

The code may keep the method name for compatibility in the first implementation, but docs and
tests should describe it as dynamic retrieval. A later cleanup may rename it to
`_dynamic_memory_section()` if the call surface is small enough.

## 12. Data Directory Impact

The install flow overhaul keeps `SEBASTIAN_DATA_DIR` as the root directory and introduces
`settings.user_data_dir` for user-owned data:

```text
settings.data_dir       -> ~/.sebastian
settings.user_data_dir  -> ~/.sebastian/data
settings.logs_dir       -> ~/.sebastian/logs
settings.run_dir        -> ~/.sebastian/run
```

Resident snapshot files must live under `settings.user_data_dir / "memory"`, not
`settings.data_dir / "memory"`. This keeps snapshots with the database, secret key,
workspace, and extensions, and prevents app/log/run concerns from mixing with user data.

## 13. Testing

Unit tests:

- Snapshot builder includes allowlisted records with `confidence >= 0.8`.
- Snapshot builder excludes records below `0.8`.
- Snapshot builder excludes `sensitive`, `needs_review`, and `do_not_auto_inject`.
- Snapshot builder excludes inactive, expired, and future-dated records.
- Pinned records outside the allowlist enter `Pinned Notes` when they pass common filters.
- Pinned records still obey confidence and policy filters.
- Renderer omits empty subsections and empty whole sections.
- Snapshot path is `settings.user_data_dir / "memory"`.
- Reader returns empty string when the snapshot file is missing or unreadable.
- Atomic write writes both Markdown and metadata.
- After a committed status, policy tag, confidence, validity, content update, or delete,
  `mark_dirty()` prevents the reader from serving old disallowed content.
- Rebuild failure after dirty leaves `snapshot_state = "error"` and an empty Markdown file.
- Metadata mismatch deterministically returns empty and schedules rebuild.
- Partial atomic write/crash leaves either a previous `ready` snapshot or an empty
  non-ready snapshot; it must never leave mixed Markdown/metadata that is served as ready.
- Crash after Markdown replace but before metadata replace is not served because
  `markdown_hash` does not match.
- A committed resident-eligible mutation racing with prompt assembly cannot be reported as
  successful before `mark_dirty()` has made the resident reader return empty.
- Resident reads wait behind any writer that is between DB commit and `mark_dirty()`.
- An in-flight rebuild cannot publish stale `ready` metadata after a later dirty generation.

BaseAgent tests:

- Prompt order is base system prompt -> resident memory -> dynamic retrieved memory -> todos.
- Existing `_memory_section()` tests remain but are renamed/reworded as dynamic retrieval tests.
- Dynamic retrieval returning empty no longer means resident memory is empty.
- Prompt assembly reads resident Markdown without SQLite access on the hot path.

Integration tests:

- Gateway startup rebuilds resident snapshot after data directory setup.
- A memory write followed by dirty refresh updates the snapshot outside the DB transaction.

## 14. Deferred Work

- `memory_pin` / `memory_unpin` owner-only management API.
- Android or Web UI for pinning, unpinning, reviewing skipped pinned records.
- Automatic pin suggestions from cross-session consolidation.
- Manual owner-editable resident notes file.
- Sensitive-memory redaction and policy-specific resident injection.
- Renaming `_memory_section()` to `_dynamic_memory_section()` after compatibility review.

## 15. Acceptance Criteria

- Every Sebastian depth-1 turn can include resident memory without querying SQLite.
- Resident memory comes from a rebuildable snapshot under `settings.user_data_dir`.
- Only high-confidence allowlisted profile records and filtered pinned records enter the
  resident snapshot.
- Dynamic retrieval remains available and clearly documented as turn-specific recall.
- No new pin creation workflow is introduced in this phase.
