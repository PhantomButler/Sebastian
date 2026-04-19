# Memory System Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement these plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a staged execution map for implementing Sebastian's new Memory（记忆）system without mixing architecture phases or introducing vector database dependencies.

**Architecture:** The implementation follows `docs/architecture/spec/memory/`: Phase A establishes protocols and schema, Phase B delivers DB-backed Profile/Episode retrieval with explicit tools, Phase C adds LLM extraction and background consolidation, and Phase D adds relation/admin enhancements. Existing `EpisodicMemory` remains a session history compatibility layer until a later safe rename.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy async, SQLite + FTS5, jieba, pytest, pytest-asyncio.

---

## Source Specs

- `docs/architecture/spec/memory/INDEX.md`
- `docs/architecture/spec/memory/overview.md`
- `docs/architecture/spec/memory/artifact-model.md`
- `docs/architecture/spec/memory/storage.md`
- `docs/architecture/spec/memory/write-pipeline.md`
- `docs/architecture/spec/memory/retrieval.md`
- `docs/architecture/spec/memory/consolidation.md`
- `docs/architecture/spec/memory/implementation.md`

## Execution Order

| Phase | Plan | Outcome |
|-------|------|---------|
| A | [2026-04-19-memory-phase-a-foundation.md](2026-04-19-memory-phase-a-foundation.md) | Stable protocol models, DB schema, FTS segmentation helpers, decision log foundation |
| B | [2026-04-19-memory-phase-b-profile-episode-retrieval.md](2026-04-19-memory-phase-b-profile-episode-retrieval.md) | Runtime memory toggle, usable Profile/Episode stores, retrieval lanes, prompt injection, `memory_save` / `memory_search` |
| C | [2026-04-19-memory-phase-c-llm-consolidation.md](2026-04-19-memory-phase-c-llm-consolidation.md) | `memory_extractor` / `memory_consolidator` bindings, structured LLM extraction, session consolidation |
| D | [2026-04-19-memory-phase-d-relation-admin-hardening.md](2026-04-19-memory-phase-d-relation-admin-hardening.md) | Relation/entity enhancements, owner management APIs, maintenance workers, observability hardening |

## Branch And Commit Guidance

- Work on the existing feature branch unless the user asks for a new branch.
- Keep one commit per completed task group, not one giant commit per phase.
- Use explicit `git add <file>` commands. Do not use `git add .`.
- Commit message format: `feat(memory): 中文摘要`, `test(memory): 中文摘要`, `docs(memory): 中文摘要`.
- Include `Co-Authored-By: Codex <noreply@openai.com>`.

## Non-Goals Across All Phases

- Do not introduce a vector database.
- Do not introduce embedding as a required dependency.
- Do not replace existing `sebastian/memory/episodic_memory.py` in Phase A/B.
- Do not expose `memory_list` / `memory_delete` as agent tools in the first usable release.
- Do not store DB-session-backed memory stores as global singletons; construct stores inside an `AsyncSession` scope.
- Do not add per-turn LLM inference hooks in Phase B/C. Session-end consolidation is the first inferred-memory path.
- Do not let LLM output directly mutate database state; all writes must pass Normalize（规范化）and Resolve（冲突解析）.
- `memory_enabled` must default to enabled. When disabled, existing memory data remains on disk but no automatic memory read/write/consolidation should run.

## Required Global Verification Before PR

- [ ] Run `ruff check sebastian/ tests/`
- [ ] Run `mypy sebastian/`
- [ ] Run `pytest`
- [ ] If Android files are not touched, do not run Android checks.
- [ ] Update `CHANGELOG.md` `[Unreleased]` after implementation PR scope is known.
