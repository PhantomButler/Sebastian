---
version: "1.1"
last_updated: 2026-05-09
status: draft
integrated_to: capabilities/skill-package-manager.md
integrated_at: 2026-05-08
---

# Skill Progressive Disclosure Runtime Redesign

## 1. Problem

Sebastian currently treats each local Skill as an LLM provider tool:

```text
SKILL.md -> load_skills() -> CapabilityRegistry -> provider tools
```

This was an implementation shortcut, but it creates the wrong model:

- A Skill is shown as `skill__<name>`, so the model can mistake it for an
  executable capability.
- `load_skills()` concatenates `description + body` into the tool description,
  so every installed Skill body can enter the model context.
- Skill visibility is filtered through `allowed_skills`, but Skills are not
  real execution units. This makes the permission boundary look stronger than
  it is.
- Registry search results can be long and noisy, and should not be the default
  path for local Skill usage.

The desired architecture is progressive disclosure:

1. The model starts with only a short Skill management bootstrap.
2. It uses the Sebastian CLI to list, search, show, or read local Skill files.
3. Full `SKILL.md` bodies, scripts, references, and assets are read only when
   needed.

## 2. Non-Goals

- Do not add a model-visible native `read_skill` or `install_skill` tool.
- Do not whitelist Skill directories in the generic `Read` tool.
- Do not default to network registry search.
- Do not inject all Skill names, summaries, or bodies into the default prompt.
- Do not keep `allowed_skills` as a separate permission model.
- Do not support Skill writes through `show` or `read`.

## 3. Core Decision

Remove Skill-as-provider-tool entirely.

Sebastian will keep one permission chain:

```text
LLM tool call -> allowed_tools -> PolicyGate -> native/MCP tool execution
```

Skills leave that chain. A Skill is a local catalog package:

```text
Skill directory -> SKILL.md metadata/body -> scripts/references/assets
```

The model reaches Skills through the existing `Bash` tool and the public
`sebastian skills ...` CLI. `Bash` remains governed by `allowed_tools` and
`PolicyGate`; the Skill CLI enforces its own read-only path safety rules.

This means Skill CLI availability is conditional on `Bash` availability. An
Agent that cannot use `Bash` cannot use `sebastian skills ...` either. That is
an intentional consequence of keeping Skill access inside the normal executable
tool policy instead of adding a second Skill permission chain.

The current built-in default Agents include `Bash`, so they can use Skill
progressive disclosure. A future restricted Agent profile may omit `Bash`; that
Agent will also omit Skill CLI access unless the profile explicitly grants
`Bash`.

## 4. Runtime Boundary

### Tools

Tools remain executable capabilities:

- native `@tool` tools
- MCP tools
- permission tiers
- reviewer preflight
- `allowed_tools`

`CapabilityRegistry.get_callable_specs()` should return only native and MCP
tool specs.

### Skills

Skills become catalog entries and local files. They are not callable specs.

Remove:

- `allowed_skills`
- `SkillAllowlist`
- `SkillSpecSnapshot`
- `CapabilityRegistry._skill_tools`
- `CapabilityRegistry.get_skill_specs()`
- `CapabilityRegistry.register_skill_specs()`
- `CapabilityRegistry.replace_skill_specs()`
- `ToolSpecProvider.get_callable_specs(..., allowed_skills=...)`
- Skill handling branches in `PolicyGate.call()`
- Skill snapshot propagation in `BaseAgent`, `AgentLoop`, and
  `stream_helpers`

Manifest migration must be fail-fast. `allowed_skills` should be removed from
built-in manifests and README examples. If the agent loader sees
`allowed_skills` in any manifest after this redesign, it should raise a clear
configuration error instead of silently ignoring it. Silent ignore would make
operators think a Skill ACL still exists.

The old `skill__<name>` registered-name convention may still appear in
installer metadata for compatibility, but it must no longer mean "provider tool
name". New documentation should prefer `name` or `slug` when discussing local
Skill lookup.

## 5. Skill Catalog

`load_skills()` should no longer return provider tool specs. It should either be
renamed or reshaped into a catalog scanner that returns local Skill metadata:

- `slug`
- `name`
- `registered_name` if retained for compatibility
- `description`
- `path`
- `source`: `builtin`, `managed`, or `unmanaged`
- `managed`
- `version`
- `registry`

The catalog is used by CLI commands, docs, and future management UI. It is not
automatically inserted into the model prompt.

Local Skill content is always read from disk at command time. `show` and `read`
must not depend on a gateway runtime registry snapshot.

Lookup by `<name-or-slug>` should be deterministic:

1. Exact slug match.
2. Exact frontmatter `name` match.
3. Exact `registered_name` match only for compatibility with existing metadata
   and user habits.
4. Legacy `skill__<name>` input may be normalized to `<name>` for the name
   lookup.

If more than one local Skill matches, the command must fail and list candidate
slugs. It must not guess.

## 6. CLI Semantics

### List

```bash
sebastian skills list
```

Lists local builtin, package-managed, and unmanaged Skills.

### Search

```bash
sebastian skills search <query>
sebastian skills search <query> --source local
sebastian skills search <query> --source registry
sebastian skills search <query> --source all
```

Default source is `local`. It must not contact the registry.

`--registry <url>` only selects the remote registry URL. It does not imply
network access. Network access happens only with `--source registry` or
`--source all`.

Output should separate local and registry results:

```text
LOCAL
slug    source    registered_name    description

REGISTRY
slug    version/security    description
```

Registry search is for finding new Skills to install. It is not authoritative
for installed Skill usage.

### Show

```bash
sebastian skills show <name-or-slug>
sebastian skills show <name-or-slug> --body
```

Default output:

- metadata
- path
- source
- managed/version/registry when available
- file list

Default output must not print the full `SKILL.md` body.

`--body` prints the local `SKILL.md` body. The local disk file is authoritative.

File listing rules:

- List files relative to the Skill root.
- Exclude manager-owned metadata such as `.sebastian-origin.json`,
  `.sebastian/`, and `.sebastian-skills.lock.json`.
- Exclude hidden files and hidden directories by default.
- Mark symlinks as symlinks in the listing, but do not follow them for listing.
- Sort paths lexicographically for stable output.

### Read

```bash
sebastian skills read <name-or-slug> <relative-path>
```

Reads a text file inside the matched Skill directory. This is for files such as:

- `references/provider-notes.md`
- `scripts/helper.py`
- `assets/prompt-template.md`

Safety rules:

- Accept only relative paths.
- Reject absolute paths.
- Reject empty paths, `.`, `..`, and any path containing `..`.
- Resolve the Skill root and target path with `Path.resolve()`.
- Reject symlink escape by requiring the resolved target to stay within the
  resolved Skill root.
- Reject hidden paths and manager-owned metadata using the same exclusion policy
  as `show` file listing. For example, `read` must not return
  `.sebastian-origin.json`, files under `.sebastian/`, hidden files, or files in
  hidden directories.
- Read only regular files.
- Reject directories, sockets, devices, FIFOs, and other special files.
- Decode as UTF-8 text. Binary or undecodable content fails closed.
- Enforce a maximum output size. The initial limit should be 128 KiB for
  `show --body` and `read`. If content exceeds the limit, fail with a message
  telling the user to read a smaller file or add a future paged read design.
- Never write or modify files.

Install, update, and remove remain package-manager operations. Manual edits are
ordinary user filesystem actions, not CLI `read/show` actions.

## 7. Prompt Bootstrap

Replace the current `## Available Skills` prompt section with a fixed, short
bootstrap:

```markdown
## Skill Management

For Sebastian Skill-related requests, use Bash with:
- `sebastian skills list`
- `sebastian skills search <query>`
- `sebastian skills show <name-or-slug>`
- `sebastian skills show <name-or-slug> --body`
- `sebastian skills read <name-or-slug> <relative-path>`
- `sebastian skills inspect/install/update/remove ...`

Local Skill content is authoritative for installed Skills. Registry
inspect/search results are only remote metadata.
`sebastian skills search <query>` searches local Skills by default. Use
`--source registry` only when the user wants to find new Skills to install.
For reusable domain tasks, search local Skills before falling back to generic
tools. Build concise search queries from the user's intent; for Chinese or
other non-English requests, include the original meaningful terms plus likely
English synonyms so local Skill metadata can match either language.

Examples:
- User asks: "帮我查机票和航班" -> `sebastian skills search "机票 航班 flight airfare travel"`
- User asks: "整理发票报销" -> `sebastian skills search "发票 报销 invoice reimbursement expense"`
- User asks: "resume polish" -> `sebastian skills search "resume polish CV"`

`install`, `update`, and `remove` are mutation commands. Use them only when the
user explicitly asks to manage installed Skills.
Skill management is the exception to the general "prefer Read over Bash for
file reads" rule. Do not use generic Read to access Skill directories; use the
`sebastian skills` CLI instead.
```

The bootstrap tells the model how to discover Skills without listing every
installed Skill name or injecting any Skill body. It is stable, small, and
independent of the installed catalog.

The builtin `skill_manager` Skill remains a local Skill package. Its full rules
can be read through:

```bash
sebastian skills show skill_manager --body
```

It is no longer exposed as `skill__skill_manager`.

## 8. Hot Reload

The old hot reload path refreshed provider tool specs and rebuilt prompt/tool
snapshots for new sessions. That behavior should end.

After this redesign:

- New Skill files are immediately visible to `sebastian skills list/show/read`
  because those commands read disk.
- Provider tool specs do not change when Skills are added, edited, or removed.
- The fixed prompt bootstrap does not need per-Skill rebuilds.

`SkillHotReloader` may be removed or reduced to a lightweight catalog
fingerprint helper if another subsystem still needs change detection. It must
not mutate provider tools.

## 9. Documentation Updates

Update these docs to remove Skill-as-tool language:

- `README.md`
- `sebastian/README.md`
- `sebastian/capabilities/README.md`
- `sebastian/capabilities/tools/README.md`
- `sebastian/capabilities/skills/README.md`
- `sebastian/cli/README.md`
- `sebastian/agents/README.md`
- `sebastian/permissions/README.md`
- `sebastian/agents/*/manifest.toml`
- `sebastian/agents/*/README.md`
- `docs/architecture/spec/capabilities/skill-package-manager.md`
- `docs/architecture/spec/core/system-prompt.md`
- `docs/architecture/spec/agents/permission.md`
- `docs/architecture/spec/overview/architecture.md`
- `docs/architecture/spec/overview/three-tier-agent.md`
- `docs/architecture/spec/agents/code-agent.md`
- relevant spec index pages if references mention `allowed_skills` or
  `skill__<name>` as a callable tool

Required wording changes:

- Skill is a catalog package, not an LLM tool.
- Skill content is read through `sebastian skills show/read`.
- Generic `Read` does not get a Skill directory whitelist.
- Registry search is opt-in for remote discovery.
- The only default model context is the short Skill bootstrap.
- Sebastian currently has no Skill ACL. Execution policy covers tools.
- Skill CLI access requires `Bash`; Agents without `Bash` cannot use Skills
  through the CLI.

## 10. Testing Plan

### CLI

- `show` prints metadata and files but not body by default.
- `show --body` prints the `SKILL.md` body.
- `show` reads the latest disk content, not a runtime snapshot.
- `show` lists files with manager metadata and hidden files excluded.
- `show --body` fails when body output exceeds the size limit.
- `read` reads a normal UTF-8 file inside the Skill root.
- `read` rejects absolute paths.
- `read` rejects `..` traversal.
- `read` rejects symlink escape.
- `read` rejects hidden paths and manager-owned metadata paths.
- `read` rejects directories and special files.
- `read` rejects undecodable/binary content.
- `read` fails when file output exceeds the size limit.
- lookup prefers slug, then frontmatter name, then compatibility
  `registered_name`; ambiguous matches fail with candidates.
- `search` defaults to local and does not instantiate or call the registry
  client.
- `search --source registry` calls the registry client.
- `search --source all` prints separate local and registry sections.
- `--registry` without a registry source does not trigger network access.

### Runtime

- `CapabilityRegistry.get_callable_specs()` does not include
  `skill__skill_manager` or any other Skill.
- `CapabilityRegistry.call()` returns unknown tool for old `skill__<name>`
  calls unless a real native/MCP tool has that name.
- `PolicyGate.get_callable_specs()` handles only native and MCP tools.
- `PolicyGate.call()` has no Skill-specific branch.
- `ToolSpecProvider.get_callable_specs()` no longer accepts `allowed_skills`.
- `ToolCallContext` has no `allowed_skills` or `skill_specs_snapshot`.
- `BaseAgent` prompt includes the Skill bootstrap.
- `BaseAgent` prompt does not include installed Skill bodies.
- `BaseAgent`, `AgentLoop`, and `stream_helpers` no longer pass Skill snapshots.
- Agent manifest loading fails clearly if `allowed_skills` is present.
- Built-in manifests no longer contain `allowed_skills`.
- Built-in default Agents retain `Bash`, so they can use the Skill CLI.
- An Agent without `Bash` cannot use Skill CLI access.

### Regression

- Existing native and MCP tool filtering through `allowed_tools` still works.
- `allowed_tools=None` still exposes no executable capability tools.
- `allowed_tools=ALL_TOOLS` still exposes all executable capability tools.
- `allowed_tools={"Read"}` still exposes only the named tool.

## 11. Rollout

This is a breaking internal runtime redesign but should be user-positive:

- Existing local Skill files keep working as CLI-readable Skill packages.
- Existing package-managed install/update/remove flows remain.
- Sessions no longer see stale Skill tool snapshots because Skills are no
  longer provider tools.
- Users and agents use local CLI reads to access current Skill content.

Implementation should land as one focused branch because the old model crosses
registry, policy, prompt, and stream snapshot code. Splitting the runtime
removal from CLI read/show changes would leave a half-migrated permission model.

## 12. Open Follow-Up

Sebastian intentionally does not implement Skill ACL in this design.

If future dedicated Agents need restricted Skill visibility, design that as an
Agent capability profile with a concrete enforcement point. Do not reintroduce
Skill-as-provider-tool to simulate permissions.
