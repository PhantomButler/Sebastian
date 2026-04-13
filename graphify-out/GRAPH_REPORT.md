# Graph Report - .  (2026-04-13)

## Corpus Check
- 227 files · ~67,332 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1079 nodes · 1917 edges · 88 communities detected
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 636 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Event Bus & Agent Registry|Event Bus & Agent Registry]]
- [[_COMMUNITY_LLM Provider Layer|LLM Provider Layer]]
- [[_COMMUNITY_Agent Loop & Core Runtime|Agent Loop & Core Runtime]]
- [[_COMMUNITY_Permission & Policy Engine|Permission & Policy Engine]]
- [[_COMMUNITY_Sub-Agent Plugin System|Sub-Agent Plugin System]]
- [[_COMMUNITY_SQLAlchemy Store Models|SQLAlchemy Store Models]]
- [[_COMMUNITY_BaseAgent & CodeAgent Spec|BaseAgent & CodeAgent Spec]]
- [[_COMMUNITY_Android Chat & Data Layer|Android Chat & Data Layer]]
- [[_COMMUNITY_CLI Commands & Entrypoints|CLI Commands & Entrypoints]]
- [[_COMMUNITY_Android UI Screens|Android UI Screens]]
- [[_COMMUNITY_Remote DTOs & Android Models|Remote DTOs & Android Models]]
- [[_COMMUNITY_Session & Task API Endpoints|Session & Task API Endpoints]]
- [[_COMMUNITY_Episodic Memory|Episodic Memory]]
- [[_COMMUNITY_Log Manager System|Log Manager System]]
- [[_COMMUNITY_Architecture Spec & Overview|Architecture Spec & Overview]]
- [[_COMMUNITY_JWT & Auth Security|JWT & Auth Security]]
- [[_COMMUNITY_Android Repository Layer|Android Repository Layer]]
- [[_COMMUNITY_App Settings & Config|App Settings & Config]]
- [[_COMMUNITY_PID File Process Management|PID File Process Management]]
- [[_COMMUNITY_Web UI Scripts|Web UI Scripts]]
- [[_COMMUNITY_Owner Init Wizard|Owner Init Wizard]]
- [[_COMMUNITY_Sub-Agent Delegation|Sub-Agent Delegation]]
- [[_COMMUNITY_Tool Permission Tiers|Tool Permission Tiers]]
- [[_COMMUNITY_Encryption & Secret Keys|Encryption & Secret Keys]]
- [[_COMMUNITY_Composer UI Architecture|Composer UI Architecture]]
- [[_COMMUNITY_File State Write Guard|File State Write Guard]]
- [[_COMMUNITY_Todo Store|Todo Store]]
- [[_COMMUNITY_Database Init & Migrations|Database Init & Migrations]]
- [[_COMMUNITY_Android Composer Components|Android Composer Components]]
- [[_COMMUNITY_Setup Wizard Security|Setup Wizard Security]]
- [[_COMMUNITY_Approval Action Handlers|Approval Action Handlers]]
- [[_COMMUNITY_Android Hilt DI|Android Hilt DI]]
- [[_COMMUNITY_Skill Loader|Skill Loader]]
- [[_COMMUNITY_SSE Stream Endpoint|SSE Stream Endpoint]]
- [[_COMMUNITY_FastAPI App Bootstrap|FastAPI App Bootstrap]]
- [[_COMMUNITY_Tool Capability Loader|Tool Capability Loader]]
- [[_COMMUNITY_Todo Write Tool|Todo Write Tool]]
- [[_COMMUNITY_Setup Package|Setup Package]]
- [[_COMMUNITY_Agent HTTP Endpoints|Agent HTTP Endpoints]]
- [[_COMMUNITY_Android Markdown DI|Android Markdown DI]]
- [[_COMMUNITY_Write Tool|Write Tool]]
- [[_COMMUNITY_Read Tool|Read Tool]]
- [[_COMMUNITY_Edit Tool|Edit Tool]]
- [[_COMMUNITY_Owner State|Owner State]]
- [[_COMMUNITY_Setup Routes|Setup Routes]]
- [[_COMMUNITY_Android App Bootstrap|Android App Bootstrap]]
- [[_COMMUNITY_Android Theme System|Android Theme System]]
- [[_COMMUNITY_Android ThinkButton|Android ThinkButton]]
- [[_COMMUNITY_Session Persistence Rationale|Session Persistence Rationale]]
- [[_COMMUNITY_Module Group 49|Module Group 49]]
- [[_COMMUNITY_Module Group 50|Module Group 50]]
- [[_COMMUNITY_Module Group 51|Module Group 51]]
- [[_COMMUNITY_Module Group 52|Module Group 52]]
- [[_COMMUNITY_Module Group 53|Module Group 53]]
- [[_COMMUNITY_Module Group 54|Module Group 54]]
- [[_COMMUNITY_Module Group 55|Module Group 55]]
- [[_COMMUNITY_Module Group 56|Module Group 56]]
- [[_COMMUNITY_Module Group 57|Module Group 57]]
- [[_COMMUNITY_Module Group 58|Module Group 58]]
- [[_COMMUNITY_Module Group 59|Module Group 59]]
- [[_COMMUNITY_Module Group 60|Module Group 60]]
- [[_COMMUNITY_Module Group 61|Module Group 61]]
- [[_COMMUNITY_Module Group 62|Module Group 62]]
- [[_COMMUNITY_Module Group 63|Module Group 63]]
- [[_COMMUNITY_Module Group 64|Module Group 64]]
- [[_COMMUNITY_Module Group 65|Module Group 65]]
- [[_COMMUNITY_Module Group 66|Module Group 66]]
- [[_COMMUNITY_Module Group 67|Module Group 67]]
- [[_COMMUNITY_Module Group 68|Module Group 68]]
- [[_COMMUNITY_Module Group 69|Module Group 69]]
- [[_COMMUNITY_Module Group 70|Module Group 70]]
- [[_COMMUNITY_Module Group 71|Module Group 71]]
- [[_COMMUNITY_Module Group 72|Module Group 72]]
- [[_COMMUNITY_Module Group 73|Module Group 73]]
- [[_COMMUNITY_Module Group 74|Module Group 74]]
- [[_COMMUNITY_Module Group 75|Module Group 75]]
- [[_COMMUNITY_Module Group 76|Module Group 76]]
- [[_COMMUNITY_Module Group 77|Module Group 77]]
- [[_COMMUNITY_Module Group 78|Module Group 78]]
- [[_COMMUNITY_Module Group 79|Module Group 79]]
- [[_COMMUNITY_Module Group 80|Module Group 80]]
- [[_COMMUNITY_Module Group 81|Module Group 81]]
- [[_COMMUNITY_Module Group 82|Module Group 82]]
- [[_COMMUNITY_Module Group 83|Module Group 83]]
- [[_COMMUNITY_Module Group 84|Module Group 84]]
- [[_COMMUNITY_Module Group 85|Module Group 85]]
- [[_COMMUNITY_Module Group 86|Module Group 86]]
- [[_COMMUNITY_Module Group 87|Module Group 87]]

## God Nodes (most connected - your core abstractions)
1. `BaseAgent` - 46 edges
2. `SessionStore` - 46 edges
3. `ToolResult` - 36 edges
4. `Event` - 32 edges
5. `EventBus` - 29 edges
6. `LLMProviderRegistry` - 28 edges
7. `Task` - 26 edges
8. `IndexStore` - 25 edges
9. `EventType` - 24 edges
10. `Return a '## Session Todos' section reflecting current todos.json.          Empt` - 23 edges

## Surprising Connections (you probably didn't know these)
- `NetworkModule (DI)` --conceptually_related_to--> `ApiService Retrofit Interface`  [INFERRED]
  ui/mobile-android/app/src/main/java/com/sebastian/android/di/README.md → ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt
- `RepositoryModule (DI)` --conceptually_related_to--> `ApiService Retrofit Interface`  [INFERRED]
  ui/mobile-android/app/src/main/java/com/sebastian/android/di/README.md → ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt
- `ChatViewModel (documented)` --conceptually_related_to--> `SseClient OkHttp SSE`  [INFERRED]
  ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md → ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/SseClient.kt
- `SSE Event Protocol (complete event table + frame format)` --implements--> `gateway/sse.py (SSEManager)`  [INFERRED]
  docs/architecture/spec/core/runtime.md → sebastian/gateway/README.md
- `LLMProviderRecord ORM Model` --implements--> `LLM Provider Spec`  [INFERRED]
  sebastian/store/README.md → docs/architecture/spec/core/llm-provider.md

## Hyperedges (group relationships)
- **Global Approval Flow: GlobalApprovalViewModel → GlobalApprovalBanner → ChatRepository** — globalapprovalviewmodel_kt, globalapprovalbanner, chatrepository [EXTRACTED 0.90]
- **Provider Management: ProviderFormViewModel + SettingsViewModel + SettingsRepository** — providerformviewmodel_kt, settingsviewmodel_kt, settingsrepository [EXTRACTED 0.92]
- **SSE Streaming Pipeline: SseFrameParser → StreamEvent → ChatViewModel** — sseclient_kt, streamevent_model, chatviewmodel_kt [EXTRACTED 0.95]
- **Message Rendering Pipeline** — messagelist_MessageList, streamingmessage_MessageBubble, streamingmessage_AssistantMessageBlocks, thinkingcard_ThinkingCard, toolcallcard_ToolCallCard, markdownview_MarkdownView [EXTRACTED 0.95]
- **ChatScreen Three-Pane Layout Flow** — chatscreen_ChatScreen, slidingthreepanelayout_SlidingThreePaneLayout, sessionpanel_SessionPanel, todopanel_TodoPanel [EXTRACTED 0.95]
- **Composer Input Bar Components** — composer_Composer, thinkbutton_ThinkButton, sendbutton_SendButton [EXTRACTED 0.98]
- **UI Theme System (Color + Theme Composable + Icons)** — color_colorkt, sebastiantheme_sebastiantheme, sebastianicons_sebastianicons [INFERRED 0.85]
- **Hilt DI Module Suite** — networkmodule_networkmodule, repositorymodule_repositorymodule, markdownmodule_markdownmodule, coroutinemodule_coroutinemodule, storagemodule_storagemodule [EXTRACTED 1.00]
- **Repository Layer (Interface + Impl pattern)** — settingsrepository_settingsrepository, settingsrepositoryimpl_settingsrepositoryimpl, chatrepository_chatrepository, chatrepositoryimpl_chatrepositoryimpl, sessionrepository_sessionrepository, sessionrepositoryimpl_sessionrepositoryimpl, agentrepository_agentrepository, agentrepositoryimpl_agentrepositoryimpl [EXTRACTED 1.00]
- **Message Content Block Model** — message_Message, contentblock_ContentBlock, streamevent_StreamEvent [INFERRED 0.88]
- **SSE Event Processing Pipeline** — sseclient_SseClient, sseframedto_SseFrameParser, streamevent_StreamEvent [EXTRACTED 0.95]
- **DTO to Domain Model Mapping Layer** — messagedto_MessageDto, sessiondto_SessionDto, agentdto_AgentDto, providerdto_ProviderDto [EXTRACTED 0.95]
- **LLM Provider Ecosystem: Anthropic + OpenAI + Registry** — llm_provider, llm_anthropic, llm_openai_compat, llm_registry [EXTRACTED 1.00]
- **Core Runtime: BaseAgent + AgentLoop + TaskManager** — core_base_agent, core_agent_loop, core_task_manager, core_session_runner, core_stalled_watchdog [EXTRACTED 1.00]
- **Capability Layer: Registry + Tools + MCPs + Skills** — caps_capability_registry, caps_tools_loader, caps_mcps_loader, caps_skills_loader, caps_mcp_client [EXTRACTED 1.00]
- **Native Tools Set** — caps_tool_bash, caps_tool_edit, caps_tool_glob, caps_tool_grep, caps_tool_read, caps_tool_write, caps_tool_todo_write [EXTRACTED 1.00]
- **Memory Layers: Working + Episodic + Semantic(planned)** — memory_store, memory_working, memory_episodic, memory_semantic_planned [EXTRACTED 1.00]
- **Engineering Guidelines: Workflow + Code Quality + Safety** — eng_guideline_workflow, eng_guideline_code_quality, eng_guideline_execution_safety, agents_code_engineering_guidelines [EXTRACTED 1.00]
- **Permission System: Gate + Reviewer + Types** — permissions_gate, permissions_reviewer, permissions_types, caps_permission_tier [EXTRACTED 1.00]
- **Orchestration Flow: Sebastian → delegate_to_agent → Sub-Agent** — orchestrator_sebas, orchestrator_tools, agents_code, core_session_runner [EXTRACTED 1.00]
- **Gateway Lifespan Initialization Chain** — gateway_readme_app_py, store_readme_database_py, store_readme_session_store_py, gateway_readme_event_bus, gateway_readme_agent_instances, gateway_readme_sse_py [EXTRACTED 1.00]
- **CI/CD Quality Gate Jobs** — infra_ci_yml, infra_branch_protection, infra_release_yml, infra_release_artifacts [EXTRACTED 1.00]
- **LLM Provider Abstraction Chain** — core_llm_provider_abstraction, core_llm_anthropic_adapter, core_llm_openai_compat_adapter, core_llm_registry, core_runtime_agent_loop [EXTRACTED 1.00]
- **Core Tools with Permission Tiers** — capabilities_tool_read, capabilities_tool_write, capabilities_tool_edit, capabilities_tool_bash, capabilities_tool_glob, capabilities_tool_grep, agents_permission_tier [EXTRACTED 1.00]
- **Permission System Components** — agents_policy_gate, agents_permission_reviewer, agents_approval_manager, agents_permission_tier, agents_tool_call_context [EXTRACTED 1.00]
- **Android Streaming Pipeline** — mobile_overview_sse_client, mobile_streaming_thread_model, mobile_streaming_delta_throttle, mobile_streaming_markwon, mobile_streaming_content_block [EXTRACTED 1.00]
- **Android Data Layer Component Set** — mobile_datalayer_viewmodel, mobile_datalayer_repository, mobile_datalayer_apiservice, mobile_datalayer_settingsdatastore, mobile_datalayer_securetokenstore [EXTRACTED 1.00]
- **Composer Slot Components** — mobile_composer_slotarch, mobile_composer_voiceslot, mobile_composer_attachmentslot, mobile_composer_fullduplex [EXTRACTED 1.00]
- **Three-Tier Agent System** — three_tier_model, three_tier_singleton, three_tier_tools, three_tier_stalled_detection, three_tier_llm_routing [EXTRACTED 1.00]
- **Permission Enforcement Triad: PolicyGate + PermissionReviewer + ToolCallContext** — agents_policy_gate, agents_permission_reviewer, agents_tool_call_context [EXTRACTED 0.95]
- **Workspace Boundary Enforcement: PathUtils + PolicyGate + PermissionReviewer** — agents_path_utils, agents_policy_gate, agents_permission_reviewer [EXTRACTED 0.90]
- **Agent Knowledge Loading: BaseAgent + _knowledge_section + manifest.toml** — agents_base_agent, agents_knowledge_section, agents_manifest_toml [EXTRACTED 0.90]

## Communities

### Community 0 - "Event Bus & Agent Registry"
Cohesion: 0.04
Nodes (48): Create a singleton instance for each registered agent type., EventBus, Clear all handlers. Used in tests to prevent handler leakage between tests., ConversationManager, Conversation plane: manages pending approval futures.      Approval requests are, Persist approval record, then suspend until user grants or denies., Called by the approval API endpoint to resolve a pending request., Exception (+40 more)

### Community 1 - "LLM Provider Layer"
Cohesion: 0.02
Nodes (97): Anthropic SDK Adapter (AnthropicProvider), llm/crypto.py (Fernet API key encryption), OpenAI-Compatible Adapter (OpenAICompatProvider), LLMProvider Abstract Interface, LLM Provider Spec, Rationale: Fernet key derived from JWT secret (no extra env var), thinking_capability (5-level model: none/toggle/effort/adaptive/always_on), Thinking Effort Full-Chain Propagation (+89 more)

### Community 2 - "Agent Loop & Core Runtime"
Cohesion: 0.07
Nodes (48): ABC, AgentLoop, _is_empty_output(), Check if tool output is semantically empty., Core reasoning loop. Drives multi-turn LLM conversation via LLMProvider., Yield LLM stream events; accept tool results injected via asend()., _tool_result_content(), _validate_injected_tool_result() (+40 more)

### Community 3 - "Permission & Policy Engine"
Cohesion: 0.05
Nodes (60): _match_dangerous_bash(), _normalize_path_inputs(), PolicyGate, Delegate to registry for skill specs., Return tool specs in Anthropic API format.          For MODEL_DECIDES tools (inc, Execute a tool after enforcing its permission tier., 若工具含 file_path/path 参数且路径在 workspace 外，请求用户审批。          返回 ToolResult 表示流程已在此终止；, MODEL_DECIDES 审批流：静态检查优先，通过后再交 LLM 审查。 (+52 more)

### Community 4 - "Sub-Agent Plugin System"
Cohesion: 0.03
Nodes (79): Code Agent Forge Sub-Agent, Engineering Guidelines Code Agent Knowledge, Code Agent manifest.toml Declaration, Agents Loader manifest.toml Scanner, CapabilityRegistry Unified Tool Access, MCPClient MCP Server Integration, MCPs Loader Config.toml Scanner, Skills Loader SKILL.md Scanner (+71 more)

### Community 5 - "SQLAlchemy Store Models"
Cohesion: 0.07
Nodes (50): Base, BaseModel, Base, DeclarativeBase, EventLog, Append-only event persistence.      All events flow through EventBus first, then, Append an event to the log., create_llm_provider() (+42 more)

### Community 6 - "BaseAgent & CodeAgent Spec"
Cohesion: 0.07
Nodes (43): ApprovalManagerProtocol, BaseAgent, CodeAgent Spec, CodeAgent Persona (senior software engineer), Code Agent Spec, engineering_guidelines.md (CodeAgent knowledge file), _guidelines_section() (workspace + tool preference injected in system prompt), Agents Module Spec Index (+35 more)

### Community 7 - "Android Chat & Data Layer"
Cohesion: 0.07
Nodes (42): AgentAnimState (Enum), AgentInfo (data model), AgentRepository, ChatRepository, ChatUiState, ChatViewModel, ComposerState (Enum), ConnectionTestResult (sealed class) (+34 more)

### Community 8 - "CLI Commands & Entrypoints"
Cohesion: 0.08
Nodes (39): init(), logs(), Tail Sebastian log file., Update Sebastian to the latest GitHub release in place., Initialize Sebastian (create owner account + generate JWT secret)., Start the Sebastian gateway server., Stop the background Sebastian server., Check whether Sebastian is running. (+31 more)

### Community 9 - "Android UI Screens"
Cohesion: 0.06
Nodes (41): AgentListScreen, AppearancePage, SettingToggleRow, ChatScreen, Composer, ConnectionPage, LoggedInContent, LoginContent (+33 more)

### Community 10 - "Remote DTOs & Android Models"
Cohesion: 0.08
Nodes (35): AgentDto, AgentListResponse DTO, AgentInfo Domain Model, ApiService Retrofit Interface, ContentBlock Sealed Class, ToolStatus Enum, LogConfigPatchDto, LogStateDto (+27 more)

### Community 11 - "Session & Task API Endpoints"
Cohesion: 0.16
Nodes (16): cancel_session_post(), cancel_task(), cancel_task_post(), create_agent_session(), delete_session(), get_session(), get_session_recent(), get_session_task() (+8 more)

### Community 12 - "Episodic Memory"
Cohesion: 0.14
Nodes (7): EpisodicMemory, Conversation history backed by the file-based SessionStore., TurnEntry, MemoryStore, Unified access point for all memory layers.     working: task-scoped in-process, In-process task-scoped memory. Holds ephemeral state for the duration     of a t, WorkingMemory

### Community 13 - "Log Manager System"
Cohesion: 0.17
Nodes (11): get_log_manager(), 初始化全局 LogManager 并调用 setup()。Gateway lifespan 调用一次。, 获取全局 LogManager 单例（需在 setup_logging() 之后调用）。, setup_logging(), LogManager, _make_rotating_handler(), 管理三个 RotatingFileHandler 的生命周期，支持热切换 llm_stream / sse。, 初始化日志目录和 handlers；在 Gateway lifespan 启动时调用一次。 (+3 more)

### Community 14 - "Architecture Spec & Overview"
Cohesion: 0.14
Nodes (18): Agent Inheritance Model (BaseAgent), Sebastian Overall Architecture Design, Castle Management Three-Tier Model, Dynamic Tool Factory, Overview Spec Index, Three-Layer Memory Structure, Non-Blocking Execution Mechanism, Phase 1-5 Implementation Roadmap (+10 more)

### Community 15 - "JWT & Auth Security"
Cohesion: 0.17
Nodes (10): create_access_token(), decode_token(), get_signer(), JwtSigner, FastAPI dependency: validates Bearer token and returns the payload., Encapsulates JWT encode/decode with secret loaded from file or env fallback., Lazy-loaded global JwtSigner, refreshed by reset_signer()., Drop cached signer so next get_signer() rereads the secret file.      Used right (+2 more)

### Community 16 - "Android Repository Layer"
Cohesion: 0.18
Nodes (15): AgentRepository Interface, AgentRepositoryImpl, ChatRepository Interface, ChatRepositoryImpl, CoroutineModule (Hilt), IoDispatcher Qualifier, NetworkModule (Hilt), SseOkHttp Qualifier (+7 more)

### Community 17 - "App Settings & Config"
Cohesion: 0.15
Nodes (4): BaseSettings, ensure_data_dir(), Create required data directory structure., Settings

### Community 18 - "PID File Process Management"
Cohesion: 0.19
Nodes (12): is_running(), pid_path(), Write current (or given) PID to file., Read PID from file. Returns None if missing or corrupt., Remove PID file if it exists., Check whether a process with the given PID is alive., Send SIGTERM to the process recorded in PID file. Returns True if killed., Return the standard PID file path. (+4 more)

### Community 19 - "Web UI Scripts"
Cohesion: 0.24
Nodes (6): findNodeById(), getBranchId(), renderBusDetail(), renderFiles(), renderInspector(), renderSimpleItems()

### Community 20 - "Owner Init Wizard"
Cohesion: 0.21
Nodes (6): Pure-logic headless init wizard (unit-testable).      Raises RuntimeError if Seb, Typer-driven interactive CLI entrypoint for `sebastian init --headless`., run_headless_wizard(), run_interactive_headless_cli(), OwnerStore, Thin helper around UserRecord scoped to the single-owner account.

### Community 21 - "Sub-Agent Delegation"
Cohesion: 0.29
Nodes (7): check_sub_agents(), delegate_to_agent(), _get_spawn_lock(), _get_state(), inspect_session(), _log_task_failure(), spawn_sub_agent()

### Community 22 - "Tool Permission Tiers"
Cohesion: 0.25
Nodes (9): PermissionTier LOW/MODEL_DECIDES/HIGH_RISK, Tool bash_execute Shell Command, Tool file_edit Precise Replacement, Tool file_glob Pattern Match, Tool file_grep Content Search, Tool file_read File Reader, Tool file_write Mtime Protected Writer, File State Read Precondition Tracker (+1 more)

### Community 23 - "Encryption & Secret Keys"
Cohesion: 0.36
Nodes (7): decrypt(), encrypt(), _fernet(), Read the encryption secret from the secret.key file., Encrypt a plaintext string. Returns URL-safe base64 ciphertext., Decrypt a Fernet-encrypted string back to plaintext., _read_secret()

### Community 24 - "Composer UI Architecture"
Cohesion: 0.25
Nodes (8): AttachmentSlot (Phase 2), Composer Component Design, Composer Slot Architecture, VoiceSlot (Phase 2), Repository Layer (Android), ViewModel Layer (Android), Sebastian Android Native Client Spec Index, Rationale: Slot Architecture for Composer Extensibility

### Community 25 - "File State Write Guard"
Cohesion: 0.29
Nodes (6): check_write(), invalidate(), Write 前调用。     - 文件不存在 → 允许（新建）     - 文件存在但从未 Read → 拒绝     - 文件存在且 Read 过但 mtim, Write/Edit 成功后调用，更新缓存 mtime。, Read 成功后调用，记录当前 mtime。, record_read()

### Community 26 - "Todo Store"
Cohesion: 0.38
Nodes (2): JSON-file storage for per-session todo lists.      Stores a single `todos.json`, TodoStore

### Community 27 - "Database Init & Migrations"
Cohesion: 0.43
Nodes (6): _apply_idempotent_migrations(), get_engine(), get_session_factory(), init_db(), Create all tables. Call once at startup., Apply best-effort schema patches for columns added after initial create_all.

### Community 28 - "Android Composer Components"
Cohesion: 0.29
Nodes (7): Full-Duplex Voice Mode (Phase 3), SendButton Component, ComposerState State Machine, ApiService (Retrofit), ChatRepository Interface, ChatViewModel, SSE Collection Lifecycle (ViewModel)

### Community 29 - "Setup Wizard Security"
Cohesion: 0.33
Nodes (2): Localhost-only + single-use token guard for the setup wizard., SetupSecurity

### Community 30 - "Approval Action Handlers"
Cohesion: 0.53
Nodes (5): _approval_description(), deny_approval(), grant_approval(), list_approvals(), _resolve()

### Community 31 - "Android Hilt DI"
Cohesion: 0.47
Nodes (6): Hilt Injection Topology, Hilt NetworkModule, SecureTokenStore (JWT), SettingsDataStore (Jetpack DataStore), SettingsRepository Interface, Rationale: Dynamic BaseUrl Strategy (OkHttp Interceptor)

### Community 32 - "Skill Loader"
Cohesion: 0.5
Nodes (4): load_skills(), _parse_frontmatter(), Scan dirs for skill subdirectories containing SKILL.md.      Returns a list of t, Parse YAML-style frontmatter from SKILL.md content.      Returns (metadata_dict,

### Community 33 - "SSE Stream Endpoint"
Cohesion: 0.6
Nodes (4): global_stream(), _parse_last_event_id(), SSE endpoint: streams all events to the connected client., session_stream()

### Community 34 - "FastAPI App Bootstrap"
Cohesion: 0.67
Nodes (2): _initialize_agent_instances(), lifespan()

### Community 35 - "Tool Capability Loader"
Cohesion: 0.67
Nodes (2): load_tools(), Scan capabilities/tools/ and import:     1. Flat .py modules (non-underscore-pre

### Community 36 - "Todo Write Tool"
Cohesion: 1.0
Nodes (2): _parse_todos(), todo_write()

### Community 37 - "Setup Package"
Cohesion: 0.67
Nodes (1): Setup mode package: first-run wizard and secret key provisioning.

### Community 38 - "Agent HTTP Endpoints"
Cohesion: 0.67
Nodes (0): 

### Community 39 - "Android Markdown DI"
Cohesion: 1.0
Nodes (3): MarkdownModule (Hilt), MarkdownParser Interface, MarkwonMarkdownParser

### Community 40 - "Write Tool"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Read Tool"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Edit Tool"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Owner State"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Setup Routes"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Android App Bootstrap"
Cohesion: 1.0
Nodes (2): Android App build.gradle.kts, SebastianApp (HiltAndroidApp)

### Community 46 - "Android Theme System"
Cohesion: 1.0
Nodes (2): Theme Color Definitions, SebastianTheme

### Community 47 - "Android ThinkButton"
Cohesion: 1.0
Nodes (2): ThinkButton Component, LLMProviderRecord Data Model

### Community 48 - "Session Persistence Rationale"
Cohesion: 1.0
Nodes (2): Session as First-Class Entity, Rationale: File System for Session Persistence

### Community 49 - "Module Group 49"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Module Group 50"
Cohesion: 1.0
Nodes (1): Yield LLMStreamEvent objects for one complete LLM call.          The last event

### Community 51 - "Module Group 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Module Group 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Module Group 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Module Group 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Module Group 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Module Group 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Module Group 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Module Group 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Module Group 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Module Group 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Module Group 61"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Module Group 62"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Module Group 63"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Module Group 64"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Module Group 65"
Cohesion: 1.0
Nodes (0): 

### Community 66 - "Module Group 66"
Cohesion: 1.0
Nodes (0): 

### Community 67 - "Module Group 67"
Cohesion: 1.0
Nodes (0): 

### Community 68 - "Module Group 68"
Cohesion: 1.0
Nodes (0): 

### Community 69 - "Module Group 69"
Cohesion: 1.0
Nodes (0): 

### Community 70 - "Module Group 70"
Cohesion: 1.0
Nodes (0): 

### Community 71 - "Module Group 71"
Cohesion: 1.0
Nodes (0): 

### Community 72 - "Module Group 72"
Cohesion: 1.0
Nodes (1): Android Root build.gradle.kts

### Community 73 - "Module Group 73"
Cohesion: 1.0
Nodes (1): Android settings.gradle.kts

### Community 74 - "Module Group 74"
Cohesion: 1.0
Nodes (1): SettingsRepositoryTest (DataStore key test)

### Community 75 - "Module Group 75"
Cohesion: 1.0
Nodes (1): SebastianIcons

### Community 76 - "Module Group 76"
Cohesion: 1.0
Nodes (1): StorageModule (Hilt)

### Community 77 - "Module Group 77"
Cohesion: 1.0
Nodes (1): CreateSessionRequest DTO

### Community 78 - "Module Group 78"
Cohesion: 1.0
Nodes (1): Tool todo_write Session Todo List

### Community 79 - "Module Group 79"
Cohesion: 1.0
Nodes (1): SessionViewModel (documented)

### Community 80 - "Module Group 80"
Cohesion: 1.0
Nodes (1): SettingsViewModel (documented)

### Community 81 - "Module Group 81"
Cohesion: 1.0
Nodes (1): SubAgentViewModel (documented)

### Community 82 - "Module Group 82"
Cohesion: 1.0
Nodes (1): SessionRepository Interface

### Community 83 - "Module Group 83"
Cohesion: 1.0
Nodes (1): Protocol Stack (MCP/direct-call/SSE/FCM)

### Community 84 - "Module Group 84"
Cohesion: 1.0
Nodes (1): Technology Stack Decisions

### Community 85 - "Module Group 85"
Cohesion: 1.0
Nodes (1): Extension Specifications (Sub-Agent/Tool/MCP/Skill)

### Community 86 - "Module Group 86"
Cohesion: 1.0
Nodes (1): Event Bus SSE Event Types

### Community 87 - "Module Group 87"
Cohesion: 1.0
Nodes (1): Relationship to OpenJax Predecessor

## Ambiguous Edges - Review These
- `CLI Updater Self-Upgrade Logic` → `Sandbox Executor Docker Isolation (Planned)`  [AMBIGUOUS]
  sebastian/cli/README.md · relation: conceptually_related_to

## Knowledge Gaps
- **214 isolated node(s):** `Single-call LLM abstraction. Multi-turn loop lives in AgentLoop, not here.`, `Yield LLMStreamEvent objects for one complete LLM call.          The last event`, `Read the encryption secret from the secret.key file.`, `Encrypt a plaintext string. Returns URL-safe base64 ciphertext.`, `Decrypt a Fernet-encrypted string back to plaintext.` (+209 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Write Tool`** (2 nodes): `write()`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Read Tool`** (2 nodes): `read()`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Edit Tool`** (2 nodes): `edit()`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Owner State`** (2 nodes): `state.py`, `get_owner_store()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Setup Routes`** (2 nodes): `setup_routes.py`, `create_setup_router()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Android App Bootstrap`** (2 nodes): `Android App build.gradle.kts`, `SebastianApp (HiltAndroidApp)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Android Theme System`** (2 nodes): `Theme Color Definitions`, `SebastianTheme`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Android ThinkButton`** (2 nodes): `ThinkButton Component`, `LLMProviderRecord Data Model`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Session Persistence Rationale`** (2 nodes): `Session as First-Class Entity`, `Rationale: File System for Session Persistence`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 50`** (1 nodes): `Yield LLMStreamEvent objects for one complete LLM call.          The last event`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 51`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 52`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 53`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 54`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 55`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 56`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 57`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 58`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 59`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 60`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 61`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 62`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 63`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 64`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 65`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 66`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 67`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 68`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 69`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 70`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 71`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 72`** (1 nodes): `Android Root build.gradle.kts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 73`** (1 nodes): `Android settings.gradle.kts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 74`** (1 nodes): `SettingsRepositoryTest (DataStore key test)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 75`** (1 nodes): `SebastianIcons`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 76`** (1 nodes): `StorageModule (Hilt)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 77`** (1 nodes): `CreateSessionRequest DTO`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 78`** (1 nodes): `Tool todo_write Session Todo List`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 79`** (1 nodes): `SessionViewModel (documented)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 80`** (1 nodes): `SettingsViewModel (documented)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 81`** (1 nodes): `SubAgentViewModel (documented)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 82`** (1 nodes): `SessionRepository Interface`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 83`** (1 nodes): `Protocol Stack (MCP/direct-call/SSE/FCM)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 84`** (1 nodes): `Technology Stack Decisions`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 85`** (1 nodes): `Extension Specifications (Sub-Agent/Tool/MCP/Skill)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 86`** (1 nodes): `Event Bus SSE Event Types`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 87`** (1 nodes): `Relationship to OpenJax Predecessor`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `CLI Updater Self-Upgrade Logic` and `Sandbox Executor Docker Isolation (Planned)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `BaseAgent` connect `Agent Loop & Core Runtime` to `Event Bus & Agent Registry`, `Permission & Policy Engine`, `Episodic Memory`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `Config Global Runtime Settings` connect `Sub-Agent Plugin System` to `Agent Loop & Core Runtime`, `Permission & Policy Engine`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `BaseAgent` (e.g. with `Run an agent on a session asynchronously. Sets status on completion/failure.` and `LLMProvider`) actually correct?**
  _`BaseAgent` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `SessionStore` (e.g. with `Run an agent on a session asynchronously. Sets status on completion/failure.` and `BaseAgent`) actually correct?**
  _`SessionStore` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `ToolResult` (e.g. with `ToolSpec` and `Specification and metadata for a registered tool.`) actually correct?**
  _`ToolResult` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `Event` (e.g. with `Run an agent on a session asynchronously. Sets status on completion/failure.` and `BaseAgent`) actually correct?**
  _`Event` has 30 INFERRED edges - model-reasoned connections that need verification._