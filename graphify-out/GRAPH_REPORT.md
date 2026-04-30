# Graph Report - /Users/ericw/work/code/ai/sebastian/sebastian  (2026-04-30)

## Corpus Check
- 189 files · ~72,689 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1570 nodes · 4688 edges · 42 communities detected
- Extraction: 43% EXTRACTED · 57% INFERRED · 0% AMBIGUOUS · INFERRED: 2682 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Event Bus & Protocol Core|Event Bus & Protocol Core]]
- [[_COMMUNITY_Core Types & Checkpoints|Core Types & Checkpoints]]
- [[_COMMUNITY_Context Compaction & Tool Base|Context Compaction & Tool Base]]
- [[_COMMUNITY_Agent Delegation Tools|Agent Delegation Tools]]
- [[_COMMUNITY_Agent Registry & Loader|Agent Registry & Loader]]
- [[_COMMUNITY_Bash & Shell Execution|Bash & Shell Execution]]
- [[_COMMUNITY_LLM Provider Catalog|LLM Provider Catalog]]
- [[_COMMUNITY_Memory Tools & Data Flow|Memory Tools & Data Flow]]
- [[_COMMUNITY_A2A Protocol & Engineering Docs|A2A Protocol & Engineering Docs]]
- [[_COMMUNITY_CLI Daemon Management|CLI Daemon Management]]
- [[_COMMUNITY_Memory Deduplication|Memory Deduplication]]
- [[_COMMUNITY_Capability Registry & Scheduler|Capability Registry & Scheduler]]
- [[_COMMUNITY_System Service Management|System Service Management]]
- [[_COMMUNITY_File System Tools|File System Tools]]
- [[_COMMUNITY_Agent Hierarchy & Whitelist|Agent Hierarchy & Whitelist]]
- [[_COMMUNITY_Gateway Auth & JWT|Gateway Auth & JWT]]
- [[_COMMUNITY_Configuration Settings|Configuration Settings]]
- [[_COMMUNITY_Config Layout & LLM Setup|Config Layout & LLM Setup]]
- [[_COMMUNITY_Episodic & Profile Memory Stores|Episodic & Profile Memory Stores]]
- [[_COMMUNITY_Logging & Debug Routes|Logging & Debug Routes]]
- [[_COMMUNITY_Session Context Builder|Session Context Builder]]
- [[_COMMUNITY_Project Identity & Overview Docs|Project Identity & Overview Docs]]
- [[_COMMUNITY_File State Tracker|File State Tracker]]
- [[_COMMUNITY_Approval REST Routes|Approval REST Routes]]
- [[_COMMUNITY_SSE Streaming Routes|SSE Streaming Routes]]
- [[_COMMUNITY_CLI Auto-Updater|CLI Auto-Updater]]
- [[_COMMUNITY_Memory Lexicon|Memory Lexicon]]
- [[_COMMUNITY_CLI Initialization|CLI Initialization]]
- [[_COMMUNITY_Gateway Setup Init|Gateway Setup Init]]
- [[_COMMUNITY_CLI Serve & Daemon Docs|CLI Serve & Daemon Docs]]
- [[_COMMUNITY_LLM Provider Design Rationale|LLM Provider Design Rationale]]
- [[_COMMUNITY_Config Rationale A|Config Rationale A]]
- [[_COMMUNITY_Config Rationale B|Config Rationale B]]
- [[_COMMUNITY_Todo Read Tool|Todo Read Tool]]
- [[_COMMUNITY_Todo Write Tool|Todo Write Tool]]
- [[_COMMUNITY_Send File Tool|Send File Tool]]
- [[_COMMUNITY_Screenshot Send Tool|Screenshot Send Tool]]
- [[_COMMUNITY_Check Sub-Agents Tool|Check Sub-Agents Tool]]
- [[_COMMUNITY_Inspect Session Tool|Inspect Session Tool]]
- [[_COMMUNITY_Resume Agent Tool|Resume Agent Tool]]
- [[_COMMUNITY_Stop Agent Tool|Stop Agent Tool]]
- [[_COMMUNITY_Memory Phase ABC Concept|Memory Phase A/B/C Concept]]

## God Nodes (most connected - your core abstractions)
1. `Event` - 73 edges
2. `LLMProviderRegistry` - 71 edges
3. `SessionStore` - 67 edges
4. `TextDelta` - 65 edges
5. `BaseAgent` - 60 edges
6. `EventType` - 58 edges
7. `Task` - 56 edges
8. `EpisodeMemoryStore` - 56 edges
9. `ProfileMemoryStore` - 54 edges
10. `EventBus` - 54 edges

## Surprising Connections (you probably didn't know these)
- `Scan built-in agents dir and optional extra dirs for manifest.toml files.      B` --uses--> `BaseAgent`  [INFERRED]
  agents/_loader.py → core/base_agent.py
- `Return the ToolCallContext for the currently executing tool, or None.` --uses--> `ToolCallContext`  [INFERRED]
  core/tool_context.py → permissions/types.py
- `run_headless_wizard()` --calls--> `hash_password()`  [INFERRED]
  cli/init_wizard.py → gateway/auth.py
- `serve()` --calls--> `ensure_data_dir()`  [INFERRED]
  main.py → config/__init__.py
- `init()` --calls--> `run_interactive_headless_cli()`  [INFERRED]
  main.py → cli/init_wizard.py

## Hyperedges (group relationships)
- **Memory Write Pipeline (Extractor → Resolver → PersistDecision → DecisionLog)** — memory_extraction_py, memory_resolver_py, memory_write_router_py, memory_decision_log_py, memory_pipeline_py [EXTRACTED 0.95]
- **LLM Provider Resolution Chain (Catalog → Account → Binding → Provider)** — llm_catalog_loader, llm_registry_py, llm_anthropic_py, llm_openai_compat_py [EXTRACTED 0.95]
- **Auto-Registration Pattern (loader scans dir → @tool/config/SKILL.md → registry)** — tools_loader_py, mcps_loader_py, skills_loader_py, capabilities_registry_py [EXTRACTED 0.90]
- **Gateway Lifespan Strict Init Order (DB→Store→EventBus→Agent→SSE)** — gateway_readme_lifespan, store_readme_session_store_facade, events_readme_global_singleton_bus, orchestrator_readme_sebastian_class, gateway_readme_sse_manager [EXTRACTED 1.00]
- **Permission Gate Decision Flow (tier→reviewer→approval)** — permissions_readme_policy_gate, permissions_readme_permission_reviewer, permissions_readme_approval_manager, permissions_readme_permission_tier [EXTRACTED 1.00]
- **Agent Delegation Pattern (delegate_to_agent + EventBus + asyncio)** — a2a_readme_delegate_to_agent, events_readme_event_bus_impl, orchestrator_readme_data_flow, gateway_readme_completion_notifier [INFERRED 0.85]

## Communities

### Community 0 - "Event Bus & Protocol Core"
Cohesion: 0.06
Nodes (123): BaseModel, EventBus, LLMProviderRegistry, ResolvedProvider, ConsolidationResult, ConsolidatorInput, MemoryConsolidationScheduler, MemoryConsolidator (+115 more)

### Community 1 - "Core Types & Checkpoints"
Cohesion: 0.05
Nodes (89): Checkpoint, Enumeration of task statuses throughout their lifecycle., Checkpoint representing a state snapshot during task execution., Resource budget constraints for task execution., Execution plan for a task., Core task representation in the Sebastian system., Conversation session that owns messages and child tasks., ResourceBudget (+81 more)

### Community 2 - "Context Compaction & Tool Base"
Cohesion: 0.06
Nodes (76): ABC, CompactionRange, CompactionResult, CompactionScheduler, group_by_exchange(), _has_incomplete_tool_chain(), Orchestrate a single context-compaction pass for one session.      Dependencies, Run a single context-compaction pass for *session_id*/*agent_type*.          Exe (+68 more)

### Community 3 - "Agent Delegation Tools"
Cohesion: 0.03
Nodes (96): ask_parent(), _get_state(), check_sub_agents(), _get_state(), Conservatively estimate tokens for a message list.          Serializes each mess, Conservative local token estimator used when provider usage is unavailable., TokenEstimator, Core Agent Engine README (+88 more)

### Community 4 - "Agent Registry & Loader"
Cohesion: 0.03
Nodes (66): AgentConfig, load_agents(), Scan built-in agents dir and optional extra dirs for manifest.toml files.      B, AideAgent, BaseAgent, Pure-logic headless init wizard (unit-testable).      Raises RuntimeError if Seb, Typer-driven interactive CLI entrypoint for `sebastian init --headless`., run_headless_wizard() (+58 more)

### Community 5 - "Bash & Shell Execution"
Cohesion: 0.04
Nodes (83): bash(), _heartbeat(), _interpret_exit_code(), _is_silent_command(), 返回 True 当命令第一个 token 在 _SILENT_COMMANDS 白名单中。, 返回退出码的语义解释。仅匹配命令行第一个 token，无解释时返回 None。, 每隔 _HEARTBEAT_INTERVAL_S 秒调用一次 progress_cb，直到 stop_event 被设置。, MCPClient (+75 more)

### Community 6 - "LLM Provider Catalog"
Cohesion: 0.04
Nodes (75): Base, _build_catalog(), CatalogValidationError, LLMCatalog, LLMModelSpec, LLMProviderSpec, load_builtin_catalog(), load_catalog_from_path() (+67 more)

### Community 7 - "Memory Tools & Data Flow"
Cohesion: 0.04
Nodes (54): Memory Data Flow (Read & Write Paths), Return currently valid active relation candidates for a subject, newest first., Return up to *limit* most recently created entities, newest first.          Used, Return all canonical_names and aliases as a flat list.          Shared by sync_j, Register all entity canonical names and aliases with jieba., Trigger planner trigger-set refresh after a write. No-op if unwired., Create or update an entity by canonical name.          If an entity with the sam, Return entities whose canonical_name equals text or whose aliases JSON contains (+46 more)

### Community 8 - "A2A Protocol & Engineering Docs"
Cohesion: 0.03
Nodes (76): delegate_to_agent Tool (A2A replacement), SESSION_COMPLETED Event, SESSION_STALLED Event, CLI init_wizard.py (headless init), Code Quality Principles (shortest path, no patches, no over-engineering), Agent Communication Guidelines, Execution Safety Risk Table, Engineering Workflow (Clarify-Plan-Execute-Verify-Report) (+68 more)

### Community 9 - "CLI Daemon Management"
Cohesion: 0.07
Nodes (52): is_running(), pid_path(), Write current (or given) PID to file., Read PID from file. Returns None if missing or corrupt., Remove PID file if it exists., Check whether a process with the given PID is alive., Send SIGTERM to the process recorded in PID file. Returns True if killed., Return the standard PID file path inside run_dir. (+44 more)

### Community 10 - "Memory Deduplication"
Cohesion: 0.06
Nodes (37): canonical_bullet(), canonical_json(), normalize_memory_text(), Strip fenced code blocks, control chars, headings, list markers; collapse whites, Normalize to canonical form for exact-bullet deduplication., Stable JSON with sorted keys, no extra whitespace, UTF-8., Generate slot_value dedupe key. Returns None if structured_payload has no 'value, sha256_text() (+29 more)

### Community 11 - "Capability Registry & Scheduler"
Cohesion: 0.1
Nodes (13): Mark a profile memory record as EXPIRED. Returns rowcount (0 = not found)., Shared attachment validation helpers for turn and session creation endpoints., Validate attachment IDs and write user turn + attachment timeline items atomical, Upsert *key* → *value*. Caller must commit the session., AttachmentConflictError, AttachmentNotFoundError, AttachmentStore, AttachmentValidationError (+5 more)

### Community 12 - "System Service Management"
Cohesion: 0.12
Nodes (30): _check_linger(), cmd_install(), cmd_start(), cmd_status(), cmd_stop(), cmd_uninstall(), install(), _install_launchd() (+22 more)

### Community 13 - "File System Tools"
Cohesion: 0.1
Nodes (21): edit(), glob(), _build_grep_cmd(), _build_rg_cmd(), _check_rg(), grep(), _run_cmd(), read() (+13 more)

### Community 14 - "Agent Hierarchy & Whitelist"
Cohesion: 0.1
Nodes (25): AideAgent (general execution Sub-Agent), allowed_tools Whitelist (two-layer enforcement), ForgeAgent (code writing Sub-Agent), Three-Layer Agent Hierarchy (Sebastian depth=1, Team Lead depth=2, Worker depth=3), manifest.toml Format (agent declaration), 6 Protocol Tools Auto-injected by _loader.py, agents/ Sub-Agent Plugin Directory README, Capabilities Module README (+17 more)

### Community 15 - "Gateway Auth & JWT"
Cohesion: 0.11
Nodes (17): create_access_token(), decode_token(), get_signer(), hash_password(), JwtSigner, FastAPI dependency: validates Bearer token and returns the payload., Encapsulates JWT encode/decode with secret loaded from file or env fallback., Lazy-loaded global JwtSigner, refreshed by reset_signer(). (+9 more)

### Community 16 - "Configuration Settings"
Cohesion: 0.1
Nodes (10): BaseSettings, ensure_data_dir(), Create required data directory structure (idempotent).      Runs the layout-v2 m, Settings, _ensure_v2_dirs(), _has_any_legacy_artifact(), migrate_layout_v2(), Filesystem layout migration for Sebastian data directory.  Schema versions: - v1 (+2 more)

### Community 17 - "Config Layout & LLM Setup"
Cohesion: 0.15
Nodes (16): Data Directory Layout v2 (~/.sebastian/app|data|logs|run), Config Module README, Settings (pydantic-settings global singleton), builtin_providers.json (Catalog), CatalogLoader, decrypt(), encrypt(), _fernet() (+8 more)

### Community 18 - "Episodic & Profile Memory Stores"
Cohesion: 0.13
Nodes (15): Segment text for FTS5 indexing. Returns space-separated tokens., segment_for_fts(), _backfill_episode_fts(), _backfill_profile_fts(), bootstrap_slot_registry(), ensure_profile_fts(), init_memory_storage(), 服务启动时调用：把 memory_slots 表全部数据灌入 registry。 (+7 more)

### Community 19 - "Logging & Debug Routes"
Cohesion: 0.15
Nodes (13): get_log_manager(), 初始化全局 LogManager 并调用 setup()。Gateway lifespan 调用一次。, 获取全局 LogManager 单例（需在 setup_logging() 之后调用）。, setup_logging(), LogManager, _make_rotating_handler(), 管理三个 RotatingFileHandler 的生命周期，支持热切换 llm_stream / sse。, 初始化日志目录和 handlers；在 Gateway lifespan 启动时调用一次。 (+5 more)

### Community 20 - "Session Context Builder"
Cohesion: 0.13
Nodes (18): _build_anthropic(), _build_anthropic_assistant_blocks(), build_context_messages(), _build_openai(), _flush_tool_results(), _flush_tool_results_into_user(), _flush_tool_results_into_user_list(), _group_by_call() (+10 more)

### Community 21 - "Project Identity & Overview Docs"
Cohesion: 0.13
Nodes (15): Identity Module README (Phase 5 placeholder), agents/ Module, Sebastian Backend Guide, capabilities/ Module, cli/ Module, context/ Module, core/ Module, gateway/ Module (+7 more)

### Community 22 - "File State Tracker"
Cohesion: 0.29
Nodes (6): check_write(), invalidate(), Write 前调用。     - 文件不存在 → 允许（新建）     - 文件存在但从未 Read → 拒绝     - 文件存在且 Read 过但 mtim, Write/Edit 成功后调用，更新缓存 mtime。, Read 成功后调用，记录当前 mtime。, record_read()

### Community 23 - "Approval REST Routes"
Cohesion: 0.53
Nodes (5): _approval_description(), deny_approval(), grant_approval(), list_approvals(), _resolve()

### Community 24 - "SSE Streaming Routes"
Cohesion: 0.6
Nodes (4): global_stream(), _parse_last_event_id(), SSE endpoint: streams all events to the connected client., session_stream()

### Community 26 - "CLI Auto-Updater"
Cohesion: 0.67
Nodes (3): sebastian update command, SHA256 Release Verification, CLI updater.py (self-upgrade logic)

### Community 27 - "Memory Lexicon"
Cohesion: 1.0
Nodes (1): Intent-classification lexicons for MemoryRetrievalPlanner.  Each lane has a froz

### Community 28 - "CLI Initialization"
Cohesion: 1.0
Nodes (1): Sebastian CLI subcommands.

### Community 29 - "Gateway Setup Init"
Cohesion: 1.0
Nodes (1): Setup mode package: first-run wizard and secret key provisioning.

### Community 30 - "CLI Serve & Daemon Docs"
Cohesion: 1.0
Nodes (2): CLI daemon.py (PID file management), sebastian serve command

### Community 32 - "LLM Provider Design Rationale"
Cohesion: 1.0
Nodes (1): Yield LLMStreamEvent objects for one complete LLM call.          The last event

### Community 45 - "Config Rationale A"
Cohesion: 1.0
Nodes (1): Root install / data directory (~/.sebastian by default).

### Community 46 - "Config Rationale B"
Cohesion: 1.0
Nodes (1): User data subdir (db, secret.key, workspace, extensions).

### Community 59 - "Todo Read Tool"
Cohesion: 1.0
Nodes (1): todo_read Tool

### Community 60 - "Todo Write Tool"
Cohesion: 1.0
Nodes (1): todo_write Tool

### Community 61 - "Send File Tool"
Cohesion: 1.0
Nodes (1): send_file Tool

### Community 62 - "Screenshot Send Tool"
Cohesion: 1.0
Nodes (1): capture_screenshot_and_send Tool

### Community 63 - "Check Sub-Agents Tool"
Cohesion: 1.0
Nodes (1): check_sub_agents Tool (Protocol)

### Community 64 - "Inspect Session Tool"
Cohesion: 1.0
Nodes (1): inspect_session Tool (Protocol)

### Community 65 - "Resume Agent Tool"
Cohesion: 1.0
Nodes (1): resume_agent Tool (Protocol)

### Community 66 - "Stop Agent Tool"
Cohesion: 1.0
Nodes (1): stop_agent Tool (Protocol)

### Community 67 - "Memory Phase A/B/C Concept"
Cohesion: 1.0
Nodes (1): Memory Phase A/B/C Implementation Stages

## Ambiguous Edges - Review These
- `consolidation.py` → `consolidation.py`  [AMBIGUOUS]
  sebastian/memory/consolidation.py · relation: semantically_similar_to

## Knowledge Gaps
- **192 isolated node(s):** `Single-call LLM abstraction. Multi-turn loop lives in AgentLoop, not here.`, `Yield LLMStreamEvent objects for one complete LLM call.          The last event`, `Read the encryption secret from the secret.key file.`, `Encrypt a plaintext string. Returns URL-safe base64 ciphertext.`, `Decrypt a Fernet-encrypted string back to plaintext.` (+187 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Memory Lexicon`** (2 nodes): `retrieval_lexicon.py`, `Intent-classification lexicons for MemoryRetrievalPlanner.  Each lane has a froz`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `CLI Initialization`** (2 nodes): `__init__.py`, `Sebastian CLI subcommands.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Gateway Setup Init`** (2 nodes): `__init__.py`, `Setup mode package: first-run wizard and secret key provisioning.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `CLI Serve & Daemon Docs`** (2 nodes): `CLI daemon.py (PID file management)`, `sebastian serve command`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LLM Provider Design Rationale`** (1 nodes): `Yield LLMStreamEvent objects for one complete LLM call.          The last event`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Config Rationale A`** (1 nodes): `Root install / data directory (~/.sebastian by default).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Config Rationale B`** (1 nodes): `User data subdir (db, secret.key, workspace, extensions).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Todo Read Tool`** (1 nodes): `todo_read Tool`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Todo Write Tool`** (1 nodes): `todo_write Tool`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Send File Tool`** (1 nodes): `send_file Tool`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Screenshot Send Tool`** (1 nodes): `capture_screenshot_and_send Tool`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Check Sub-Agents Tool`** (1 nodes): `check_sub_agents Tool (Protocol)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Inspect Session Tool`** (1 nodes): `inspect_session Tool (Protocol)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Resume Agent Tool`** (1 nodes): `resume_agent Tool (Protocol)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Stop Agent Tool`** (1 nodes): `stop_agent Tool (Protocol)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Memory Phase A/B/C Concept`** (1 nodes): `Memory Phase A/B/C Implementation Stages`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `consolidation.py` and `consolidation.py`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `lifespan()` connect `Agent Registry & Loader` to `Event Bus & Protocol Core`, `Core Types & Checkpoints`, `Context Compaction & Tool Base`, `Agent Delegation Tools`, `Bash & Shell Execution`, `LLM Provider Catalog`, `Capability Registry & Scheduler`, `Configuration Settings`, `Episodic & Profile Memory Stores`, `Logging & Debug Routes`?**
  _High betweenness centrality (0.144) - this node is a cross-community bridge._
- **Why does `SessionStore` connect `Core Types & Checkpoints` to `Context Compaction & Tool Base`, `Agent Delegation Tools`, `Session Context Builder`, `Agent Registry & Loader`?**
  _High betweenness centrality (0.128) - this node is a cross-community bridge._
- **Why does `ToolResult` connect `Context Compaction & Tool Base` to `File System Tools`, `Agent Delegation Tools`, `Bash & Shell Execution`, `Memory Tools & Data Flow`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 71 inferred relationships involving `Event` (e.g. with `Run an agent on a session asynchronously. Sets status on completion/failure.` and `BaseAgent`) actually correct?**
  _`Event` has 71 INFERRED edges - model-reasoned connections that need verification._
- **Are the 52 inferred relationships involving `LLMProviderRegistry` (e.g. with `LLMCatalog` and `LLMModelSpec`) actually correct?**
  _`LLMProviderRegistry` has 52 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `SessionStore` (e.g. with `Run an agent on a session asynchronously. Sets status on completion/failure.` and `Allocate an exchange slot for the upcoming user→assistant turn.      Returns ``(`) actually correct?**
  _`SessionStore` has 34 INFERRED edges - model-reasoned connections that need verification._