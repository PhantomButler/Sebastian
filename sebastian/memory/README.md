# memory

> 上级索引：[sebastian/](../README.md)

## 模块职责

提供 Agent 记忆系统的基础设施：

- **工作记忆**：`WorkingMemory`，进程内、任务作用域的临时状态。
- **会话历史兼容层**：`EpisodicMemory`，基于 `SessionStore` 读写当前 session 的消息历史，用于兼容现有对话上下文链路；它不是新的 Episode Store。
- **统一入口**：`MemoryStore`，当前聚合 working + session history compatibility layer。
- **Phase A 长期记忆基础设施**：记忆 artifact 类型、slot 注册表、FTS 分词辅助、决策日志写入器。
- **Phase B 画像与经历检索**：`ProfileMemoryStore`（profile 写入 / 查询，含 `valid_from/valid_until/status/subject_id` 四项 current truth 过滤）、`EpisodeMemoryStore`（经历 FTS 检索，含 summary-first 两阶段检索）、`retrieval.py`（检索 pipeline，含 Episode Lane query-aware summary-first 策略）、`resolver.py`（冲突解决）。检索结果在每次 LLM turn 前通过 `BaseAgent._memory_section()` 注入 system prompt；`memory_search` 工具输出 `citation_type`（`current_truth` / `historical_summary` / `historical_evidence`），并按 active lane 数量把用户请求的 `limit` 提升为 `effective_limit`，避免已激活通道被全局截断饿死。
- **Phase C LLM 沉淀**：`extraction.py`（`MemoryExtractor`，从会话片段提取候选 artifact；`ExtractorInput.task` 已对齐 spec，值为 `"extract_memory_artifacts"`）、`consolidation.py`（`MemoryConsolidator` + `SessionConsolidationWorker` + `MemoryConsolidationScheduler`）、`provider_bindings.py`（LLM binding 常量）。会话结束后由调度器触发后台沉淀，LLM 结果经 Normalize / Resolve 后方可写入，永不直接修改记忆状态。`memory_decision_log` 新增 `input_source` 字段，记录写入来源（`memory_save_tool` / `session_consolidation`）。
- **统一写入 pipeline**：`pipeline.py`（`process_candidates()`，将 validate → resolve → persist → log 四步封装为单一可复用入口）。`memory_save` 工具后台任务和 `SessionConsolidationWorker` 均通过此函数写入，消除重复逻辑。
- **Dynamic Slot System（动态 Slot 系统）**：`types.py` 新增 `ProposedSlot`、`slot_definition_store.py`（DB CRUD for `memory_slots` 表）、`slot_proposals.py`（`SlotProposalHandler`：校验 + 写 DB + 热更新 registry，savepoint 防并发 race）、`prompts.py`（Extractor / Consolidator 共享 prompt 模板）、`feedback.py`（`MemorySaveResult` 结构化结果 + `render_memory_save_summary()`）。Extractor 通过 `extract_with_slot_retry()` 支持 slot 被拒后注入反馈重试一次；`pipeline.py` 的 `process_candidates()` 在 `proposed_slots` 非空时强制要求 `slot_proposal_handler` 参数（否则 `raise ValueError`）。内置 seed slot 新增 `user.profile.name` / `user.profile.location` / `user.profile.occupation`（共 9 个）。
- **Memory Trace 日志**：`trace.py` 提供 `MEMORY_TRACE` 调试日志辅助，贯穿检索、注入、决策、写入、工具和会话沉淀链路，输出到现有 `main.log`。

语义记忆（向量检索）为后续规划能力，当前未实现。

## 目录结构

```
memory/
├── __init__.py              # 空，包入口
├── decision_log.py          # MemoryDecisionLogger：把 ResolveDecision 写入 memory_decision_log
├── entity_registry.py       # EntityRegistry：实体 CRUD（entities 表）
├── episode_store.py         # EpisodeMemoryStore：经历写入、FTS 检索；ensure_episode_fts 建表
├── episodic_memory.py       # EpisodicMemory：会话历史兼容层，底层依赖 SessionStore，不是新 Episode Store
├── errors.py                # 记忆系统异常体系（InvalidCandidateError / InvalidSlotProposalError 等）
├── feedback.py              # MemorySaveResult + render_memory_save_summary()：memory_save 结果摘要渲染
├── profile_store.py         # ProfileMemoryStore：画像 CRUD、search_active、supersede
├── prompts.py               # Extractor / Consolidator 共享 prompt 模板（build_extractor_prompt 等）
├── resolver.py              # MemoryResolver：冲突检测 + ResolveDecision 生成
├── retrieval.py             # 检索 pipeline：MemoryRetrievalPlanner → 查 DB → MemorySectionAssembler → str
├── segmentation.py          # jieba FTS 分词辅助：索引分词、查询分词、实体词注入
├── slot_definition_store.py # SlotDefinitionStore：memory_slots 表 CRUD（insert / get / list）
├── slot_proposals.py        # SlotProposalHandler：proposed slot 校验 + 写 DB + 热更新 registry，savepoint 防 race
├── slots.py                 # SlotRegistry + 9 个内置 SlotDefinition + DEFAULT_SLOT_REGISTRY
├── startup.py               # init_memory_storage()：建 FTS 虚拟表；seed_builtin_slots；bootstrap_slot_registry
├── store.py                 # MemoryStore：统一聚合 working + 会话历史兼容层
├── subject.py               # resolve_subject()：按 scope/session/agent 派生 subject_id
├── trace.py                 # MEMORY_TRACE 调试日志辅助：trace、preview_text、record_ref
├── types.py                 # 记忆系统 Pydantic models 与 StrEnum 类型（含 ProposedSlot）
├── working_memory.py        # WorkingMemory：进程内 dict，按 task_id 隔离，任务结束后清除
├── write_router.py          # persist_decision()：按 kind 分发 memory artifact 到各 store
├── provider_bindings.py     # LLM binding 常量：MEMORY_EXTRACTOR_BINDING / MEMORY_CONSOLIDATOR_BINDING
├── extraction.py            # MemoryExtractor：LLM 提取候选 artifact；extract_with_slot_retry() 支持 slot 拒绝重试
├── pipeline.py              # process_candidates()：统一 validate→resolve→persist→log 写入流程（含 slot 注册）
└── consolidation.py         # MemoryConsolidator + SessionConsolidationWorker + MemoryConsolidationScheduler
```

## Phase A 基础文件

| 文件 | 当前职责 |
|------|----------|
| [types.py](types.py) | 定义长期记忆基础类型：`MemoryKind`、`MemoryScope`、`MemoryStatus`、`MemorySource`、`MemoryDecisionType`、`Cardinality`、`ResolutionPolicy`、`SlotDefinition`、`CandidateArtifact`、`MemoryArtifact`、`ResolveDecision` |
| [slots.py](slots.py) | 提供 `SlotRegistry`、6 个内置 `SlotDefinition` 和 `DEFAULT_SLOT_REGISTRY`；当前校验 `fact` / `preference` 必须绑定已注册 slot |
| [segmentation.py](segmentation.py) | 提供基于 `jieba.cut_for_search()` 的 FTS5 中文分词辅助：`segment_for_fts()`、`terms_for_query()`、`add_entity_terms()` |
| [decision_log.py](decision_log.py) | 提供 `MemoryDecisionLogger.append()`，把 `ResolveDecision` 写入 `MemoryDecisionLogRecord` |

> Phase B 已完成注入：每次 LLM turn 前，`BaseAgent._memory_section()` 通过 `retrieve_memory_section()` 拉取画像和经历记录，拼入 system prompt。不要把 [episodic_memory.py](episodic_memory.py) 当作新的 Episode Store 扩展；它只负责现有 session 消息历史兼容。

## Phase C LLM 沉淀组件

### Provider Bindings（`provider_bindings.py`）

定义两个 LLM binding 常量：

- `MEMORY_EXTRACTOR_BINDING = "memory_extractor"`
- `MEMORY_CONSOLIDATOR_BINDING = "memory_consolidator"`

两者复用 `AgentLLMBindingRecord.agent_type` 字段作为组件 key，**不新建表**。可绑定到相同模型，也可分开绑定。

### MemoryExtractor（`extraction.py`）

- 通过 `memory_extractor` binding 解析 LLM
- 输出严格 JSON，schema 为 `list[CandidateArtifact]`
- schema 校验失败时重试一次，重试后仍失败则返回 `[]`
- **永不写入任何存储**；提取结果由调用方决定是否送入 Normalize / Resolve

### MemoryConsolidator（`consolidation.py`）

- 通过 `memory_consolidator` binding 解析 LLM
- 输出严格 JSON，schema 为 `ConsolidationResult`
- schema 校验失败时重试一次，重试后仍失败则返回空 `ConsolidationResult`
- **永不写入任何存储**；只生成 proposed artifacts，由 Worker 经 Normalize / Resolve 后写入

### process_candidates（`pipeline.py`）

`process_candidates(candidates, *, session_id, agent_type, db_session, ...)` 是记忆写入的统一入口：

1. 对每个 `CandidateArtifact` 依次执行：`resolve_subject` → `validate_candidate` → `resolve_candidate` → `persist_decision` → `decision_logger.append`
2. 校验失败（`InvalidCandidateError`）时直接生成 DISCARD 决策并写 decision log，跳过当前 candidate
3. **不处理 EXPIRE**——EXPIRE 由调用方直接构造 `ResolveDecision` 并走 `persist_decision`，不经此函数
4. **不 commit**——调用方负责事务边界
5. 返回所有决策（含 DISCARD），供调用方统计

### SessionConsolidationWorker（`consolidation.py`）

- **幂等性**：通过 `SessionConsolidationRecord(session_id, agent_type)` DB 标记保证同一 session 只执行一次
- **原子性**：存在检查 + 全部写入 + 标记插入在**一个事务**内完成；`IntegrityError` → 事务回滚 → 直接返回（防重复执行）
- 执行前检查 `memory_settings_fn()` 返回的 `memory_enabled` 标志，未启用则跳过
- summaries 和 proposed_artifacts 统一经 `process_candidates()` 写入；EXPIRE 动作仍保持 inline
- proposed artifacts 必须经过 Normalize + Resolve 才能落库，Consolidator 的 LLM 输出绝不直接修改记忆状态

### MemoryConsolidationScheduler（`consolidation.py`）

- 订阅 EventBus 上的 `SESSION_COMPLETED` 事件
- 收到事件后先检查 `memory_enabled`，通过才调用 `asyncio.create_task` 派发后台沉淀
- 跟踪所有 pending task，`aclose()` 时等待清理
- 在 `sebastian/gateway/app.py` 的 lifespan startup 中创建并订阅，shutdown 时调用 `aclose()`

### Dynamic Slot System（`slot_definition_store.py` + `slot_proposals.py` + `prompts.py` + `feedback.py`）

LLM 在对话中可提议新的记忆 slot，提议经校验后写入 `memory_slots` 表并热加载到 `SlotRegistry`：

- **`types.ProposedSlot`**：LLM 提议的 slot 结构（三段式 slot_id 命名、scope、cardinality 等）
- **`slot_definition_store.SlotDefinitionStore`**：`memory_slots` 表的 DB CRUD（insert / get / list_builtin / list_dynamic）
- **`slot_proposals.SlotProposalHandler`**：
  - `validate_proposed_slot()`：命名规则（三段式、首段 ∈ scope、≤64 字符）+ 字段组合校验
  - `register_or_reuse()`：savepoint 隔离 INSERT；`IntegrityError` → 读赢家 → 同步内存 registry（并发 race 保护）
- **`extraction.MemoryExtractor.extract_with_slot_retry()`**：Extractor 调 `attempt_register` 回调预注册 proposed slot；被拒项附原因注入对话，最多重试 1 次 LLM 请求
- **`pipeline.process_candidates()`**：`proposed_slots` 非空时 `slot_proposal_handler` 必须传入（否则 `raise ValueError`）；被拒 slot 对应 candidate 的 `slot_id` 降级为 `None`
- **`prompts.py`**：Extractor / Consolidator 共享的 prompt 构建函数，按 kind 分组展示已知 slot 清单
- **`feedback.MemorySaveResult`** + **`render_memory_save_summary()`**：`memory_save` 工具的结构化返回值与自然语言摘要渲染

### 核心约束

> **LLM 永远不直接修改记忆状态。** Extractor 和 Consolidator 的输出都是"建议"，最终写入前必须经过 Normalize 和 Resolve 流水线。

## 已实现功能边界说明

| 功能 | 状态 | 说明 |
|------|------|------|
| current truth 过滤 | 已实现 | `profile_store.py` 三个查询方法加 `valid_from <= now` 过滤；`retrieval.py` Assembler `_keep()` 加 `status/subject_id/valid_from` 二次过滤 |
| ExtractorInput.task 契约字段 | 已实现 | `ExtractorInput.task: Literal["extract_memory_artifacts"]`，与 spec §6 对齐 |
| Episode Lane summary-first | 已实现 | `episode_store.py` 新增 `search_summaries_by_query`、`search_episodes_only`；检索 pipeline 先查 summary，不足时再补 episode detail |
| memory_search citation_type | 已实现 | profile item → `current_truth`；episode summary → `historical_summary`；episode detail → `historical_evidence` |
| decision_log input_source | 已实现 | `MemoryDecisionLogRecord` / `MemoryDecisionLogger.append()` 新增 `input_source` 字段，标记 `memory_save_tool` 或 `session_consolidation` |
| Session Consolidation | 已实现 | `SessionConsolidationWorker` + startup catch-up sweep |
| Assembler kind labels 全通道 | 已实现 | Context/Episode/Relation 通道均保留 `[kind]` 前缀，与 Profile 通道行为一致 |
| `memory_search` 全通道检索 | 已实现 | profile/context/episode(summary-first)/relation 四通道；返回 `lane` 字段区分通道来源；`effective_limit = max(requested_limit, active_lane_count)`，确保每条 active lane 至少有 1 个候选名额 |
| Profile 行持久化协议字段 | 已实现 | `cardinality`/`resolution_policy` 已写入 DB；支持存量数据库幂等迁移 |
| Episode 行持久化有效期字段 | 已实现 | `valid_from`/`valid_until` 已写入 DB；支持存量数据库幂等迁移 |
| Relation candidate 持久化 policy_tags | 已实现 | `policy_tags` 已写入 DB（JSON）；支持存量数据库幂等迁移 |
| `memory_save` fire-and-forget + extractor slot 分配 | 已实现 | 工具接口仅 `content: str`，立即返回；后台任务调 `MemoryExtractor` 分配 slot/kind，结果经 `process_candidates()` 写入；extractor 返回空则跳过，无降级 fallback |
| `memory_save` provenance 含 session_id | 已实现 | session 上下文存在时注入 `evidence=[{"session_id": ...}]`，提升审计追踪可靠性 |
| Episode/Summary 精确去重 | 已实现 | `EpisodeMemoryStore.find_active_exact()` 新增；相同 content 二次写入返回 DISCARD |
| MERGE 最小执行路径 | 已实现 | `ProfileMemoryStore.find_active_exact()` 新增；merge-policy slot 精确匹配走 MERGE → supersede；无模糊语义合并 |
| EXPIRE 统一走写入路由 | 已实现 | consolidation 不再直接调 `profile_store.expire()`；所有 EXPIRE 生命周期动作经 `write_router.persist_decision()` 路由 |
| `ConsolidatorInput.task` Literal 契约 | 已实现 | `ConsolidatorInput.task: Literal["consolidate_memory"]`，非法值在运行时被 Pydantic 拒绝 |
| `RetrievalContext.active_project_or_agent_context` | 已实现 | 字段已添加（`dict[str, Any] \| None = None`）；`BaseAgent._memory_section()` 注入基本 agent 上下文；planner 后续阶段可消费 |
| Cross-Session Consolidation | **deferred** | 需单独 spec，明确触发频率、扫描窗口、证据合并规则和幂等 key |
| Full Maintenance Worker | **deferred** | 降权、重复压缩、索引修复需单独 spec |
| Exclusive Relation | **deferred** | 互斥关系语义需单独设计 |
| Summary Replacement | **deferred** | episode summary 替换策略需单独设计 |

## 链路文档

- [data-flow.md](data-flow.md) — 读写链路完整解析：检索注入流程、各通道查库方式（FTS/SQL）、memory_save 工具、Session Consolidation、process_candidates 管道、Slot 边界

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 任务临时状态的存取（set/get/clear） | [working_memory.py](working_memory.py) |
| 现有 session 对话历史的写入与读取（add_turn/get_turns） | [episodic_memory.py](episodic_memory.py) |
| 统一记忆入口（同时访问 working + 会话历史兼容层） | [store.py](store.py) |
| 记忆 artifact、slot、决策等数据结构 | [types.py](types.py) |
| slot 定义、内置 slot、候选 artifact slot 校验 | [slots.py](slots.py) |
| SQLite FTS5 中文预分词、查询 term 生成、实体词注入 | [segmentation.py](segmentation.py) |
| 记忆冲突/写入决策审计日志 | [decision_log.py](decision_log.py) |
| Profile 画像的写入、查询、supersede | [profile_store.py](profile_store.py) |
| 经历事件的写入与 FTS 检索 | [episode_store.py](episode_store.py) |
| 每轮记忆检索 pipeline（planner → fetch → assemble） | [retrieval.py](retrieval.py) |
| Memory 链路调试日志（MEMORY_TRACE） | [trace.py](trace.py) |
| 画像冲突检测与决策生成 | [resolver.py](resolver.py) |
| 实体管理（CRUD） | [entity_registry.py](entity_registry.py) |
| 语义记忆 / 向量检索（后续阶段，待实现） | 新建 `semantic_memory.py`，并按需要在 `store.py` 中注册 |
| LLM binding 常量（extractor / consolidator） | [provider_bindings.py](provider_bindings.py) |
| 从会话片段提取候选 artifact（LLM 提取） | [extraction.py](extraction.py) |
| 候选 artifact 统一写入（validate→resolve→persist→log） | [pipeline.py](pipeline.py) |
| 会话沉淀 Worker、Consolidator、Scheduler | [consolidation.py](consolidation.py) |
| Extractor / Consolidator 共享 prompt 模板 | [prompts.py](prompts.py) |
| 动态 slot 的 DB 存储（memory_slots 表 CRUD） | [slot_definition_store.py](slot_definition_store.py) |
| 动态 slot 校验、注册、并发 race 保护 | [slot_proposals.py](slot_proposals.py) |
| memory_save 结构化结果与自然语言摘要渲染 | [feedback.py](feedback.py) |

---

> 修改本目录或模块后，请同步更新此 README。
