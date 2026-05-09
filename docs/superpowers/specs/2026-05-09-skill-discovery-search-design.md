---
version: "1.0"
last_updated: 2026-05-09
status: draft
---

# Skill Discovery Search Design

## 1. Problem

The Skill progressive disclosure redesign correctly removed Skill bodies and
Skill names from the default model context. Skills are now local catalog
packages discovered through:

```bash
sebastian skills search <query>
sebastian skills show <name-or-slug> --body
```

That preserves context and permission boundaries, but it creates two practical
discovery problems:

- Sebastian may skip local Skill discovery and directly use a generic tool such
  as Browser when the user asks for a domain task.
- Local search is too literal for multilingual use. A Chinese request such as
  "查机票" may not match an installed English Skill whose metadata says
  "flight", "airfare", or "travel".

The goal is to improve Skill discovery without reintroducing Skill-as-tool,
Skill ACLs, automatic Skill body injection, registry network access, or
package metadata mutation.

## 2. Non-Goals

- Do not expose Skills as provider tools.
- Do not inject installed Skill names, summaries, or bodies into every prompt.
- Do not add `keywords` as a required Skill metadata field.
- Do not add local aliases or per-user Skill override files.
- Do not modify third-party installed Skill packages during install or search.
- Do not generate keywords at install time.
- Do not call an LLM from the Skill CLI.
- Do not use embeddings, vector search, or network services for local search.
- Do not make registry search the default path.
- Do not automatically inject top-k Skill candidates into every turn.

## 3. Core Decision

Use a prompt-first multilingual query expansion strategy plus deterministic
multi-token local search.

Sebastian remains responsible for turning the user's natural language request
into a better search query. The CLI remains a simple, offline local matcher.

For example, when the user says:

```text
帮我查一下去东京的机票
```

Sebastian should first try a local Skill search like:

```bash
sebastian skills search "机票 航班 飞机票 flight airfare airline ticket travel booking"
```

If a plausible local Skill appears, Sebastian should read it with:

```bash
sebastian skills show <slug> --body
```

Then Sebastian can follow the Skill instructions and use generic tools such as
Browser only when the Skill calls for them or when no useful Skill exists.

## 4. Prompt Policy

Update the fixed `## Skill Management` bootstrap in `BaseAgent` with a concise
discovery policy:

- For reusable domain tasks, search local Skills before using generic tools.
- Domain tasks include travel, flights, hotels, calendar, meetings, email,
  documents, spreadsheets, code, repository, browser automation, and other
  repeatable workflows.
- If the user speaks Chinese or uses non-English terms, include both the user's
  original keywords and likely English synonyms in the search query, separated
  by spaces.
- Use registry search only when the user wants to find new Skills to install.
- If local search returns plausible candidates, read the chosen Skill body with
  `sebastian skills show <name-or-slug> --body` before acting.
- If no plausible Skill is found, continue with normal tools.

The bootstrap should include a few examples, but must stay short and stable.
It must not list installed Skills.

Suggested examples:

```bash
sebastian skills search "机票 航班 飞机票 flight airfare airline ticket travel booking"
sebastian skills search "酒店 住宿 hotel lodging accommodation travel"
sebastian skills search "日程 会议 calendar schedule meeting"
```

## 5. CLI Search Semantics

`sebastian skills search <query>` remains local by default and must not contact
the registry unless `--source registry` or `--source all` is specified.

For local search:

1. Split `<query>` on whitespace into tokens.
2. Ignore empty tokens.
3. Match tokens using OR semantics. A Skill is included if any token matches any
   searchable field.
4. Search these fields:
   - `slug`
   - frontmatter `name`
   - `registered_name`
   - `description`
5. Sort results by descending score, then stable tie-breakers.

The implementation must make frontmatter `name` available to the local search
scoring path. If the existing installed Skill row shape does not expose it
directly, the search layer should read local metadata through the existing
safe metadata parser rather than guessing from `registered_name`.

### Scoring

Scoring is intentionally simple and deterministic:

- Exact `slug` or frontmatter `name` match: highest weight.
- Substring `slug` or frontmatter `name` match: high weight.
- `description` match: medium weight.
- `registered_name` match: lower weight.
- Multiple token matches accumulate.

Exact numeric weights are implementation details, but tests should assert the
observable ordering for representative cases.

Stable tie-breakers should be deterministic and intentional, for example
source priority followed by slug. Tests should not rely on incidental list or
filesystem ordering.

### Output

Keep local output machine-readable and consistent with the current progressive
disclosure CLI:

```text
LOCAL
slug    source    registered_name    description
```

Registry output remains separated under `REGISTRY` and is unchanged except for
any existing version/security formatting.

The CLI should not show hidden metadata, Skill bodies, or file contents during
search.

## 6. Data Flow

```text
User request
  -> BaseAgent Skill Management bootstrap nudges local Skill discovery
  -> Model calls Bash: sebastian skills search "<original terms + synonyms>"
  -> CLI tokenizes query and scores local catalog entries
  -> Model sees local candidates
  -> Model calls Bash: sebastian skills show <slug> --body
  -> Model follows Skill instructions or falls back to generic tools
```

Skill content remains read-on-demand from disk. No runtime registry snapshot is
introduced.

## 7. Error Handling

- Empty or whitespace-only search queries should return an empty `LOCAL` section
  and exit successfully.
- Invalid local Skill metadata should follow existing local catalog behavior:
  fail closed where local filesystem ambiguity could mislead, and keep existing
  tests for installed Skill listing and show/read safety.
- Registry errors remain scoped to registry-backed searches and should not
  affect default local search.

## 8. Documentation Updates

Update documentation that explains Skill discovery:

- `docs/superpowers/specs/2026-05-08-skill-progressive-disclosure-design.md`
- `docs/architecture/spec/core/system-prompt.md`
- `docs/architecture/spec/capabilities/skill-package-manager.md`
- `sebastian/capabilities/skills/README.md`
- `sebastian/cli/README.md`

Required wording:

- Local Skill discovery should happen before generic tools for reusable domain
  tasks.
- For multilingual user requests, Sebastian should include likely English
  synonyms in the local search query.
- `skills search` uses multi-token local OR matching across slug, name,
  registered name, and description.
- No `keywords`, aliases, package mutation, embeddings, or automatic candidate
  injection are part of this phase.

## 9. Testing Plan

### Prompt

- `BaseAgent` system prompt includes guidance to search local Skills before
  generic tools for reusable domain tasks.
- The prompt includes a Chinese + English Skill search example.
- The prompt still states registry search is only for finding new Skills to
  install.
- The prompt does not list installed Skills or Skill bodies.

### CLI Search

- A multi-token query such as `"机票 flight airfare"` matches a Skill whose
  description contains `"flight"`.
- A multi-token query matches if any token hits, not only if the full query is a
  substring.
- Search includes frontmatter `name` in addition to slug, registered name, and
  description.
- Results are sorted by score so stronger name/slug matches appear before weaker
  description-only matches.
- Empty or whitespace-only local search prints `LOCAL` and no rows.
- Default local search does not instantiate or call the registry client.
- `--registry` without `--source registry` or `--source all` still does not
  trigger network access.
- Registry and all-source search behavior remains separated.

## 10. Rollout

This is an incremental improvement on the progressive disclosure model.

Existing installed Skills continue to work without package updates. The change
does not require Skill authors to add metadata, and it does not modify installed
Skill files. The only behavior change is that Sebastian is more likely to
discover local Skills first, and the local CLI search handles multilingual,
multi-token queries more usefully.
