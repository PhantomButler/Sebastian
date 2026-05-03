---
version: "0.1"
last_updated: 2026-04-30
status: draft
integrated_to: memory/overview.md
integrated_at: 2026-05-03
---

# Memory Service 顶层抽象设计

## 1. 背景

Sebastian 的记忆模块已经从最初的 working / episodic / semantic 占位设计，演进成一个完整的长期记忆子系统：

- Profile、context、episode、summary、entity、relation 等记忆产物。
- 动态 slot 注册和基于 slot 的冲突解决。
- 统一候选记忆写入 pipeline。
- 会话沉淀和显式 `memory_save`。
- 自动 prompt 注入、显式 `memory_search`、常驻记忆快照。

这些内部能力已经有价值，但模块边界仍然过于扁平。外部调用方会直接依赖 `retrieval.py`、`pipeline.py`、`resident_snapshot.py`、`extraction.py`、`consolidation.py` 等实现文件。

这会让后续升级变困难。如果未来检索要演进到 M-flow 风格的 graph-routed bundle search、embedding 辅助 profile 检索，或者新增 memory maintenance worker，太多调用方会被迫理解当前到底走哪条内部路径。

因此第一步应该先建立一个稳定的顶层 service 抽象，并保持行为不变。

## 2. 目标

P0 引入一个 memory service facade，为 Sebastian 其他模块提供小而稳定的 API：

1. 为 prompt 注入检索记忆。
2. 为工具显式搜索记忆。
3. 通过现有 resolution pipeline 写入候选记忆产物。
4. 成功写入后标记 resident snapshot 为 dirty。
5. 保持当前行为和输出格式不变。

这个设计应让未来记忆升级局限在 memory 模块内部：

- 将 lane retrieval 替换为 graph-routed retrieval。
- 为某条 lane 增加 embedding-backed retrieval。
- 增加 topology-aware episode bundle。
- 增加 maintenance / compaction worker。
- 后续把内部文件移动到子包。

## 3. 非目标

P0 不做以下事情：

- 不移动现有文件到新子目录。
- 不修改数据库 schema。
- 不引入 vector DB 或 embedding。
- 不实现 M-flow 风格的 `Episode -> Facet -> FacetPoint -> Entity` 存储。
- 不修改 prompt section 的文案或顺序。
- 不修改 `memory_save` 或 `memory_search` 的用户可见行为。
- 不修改 consolidation 幂等逻辑或 session completion 语义。
- 不迁移 consolidation 内部的 retrieval path，例如 `DEFAULT_RETRIEVAL_PLANNER` / `EntityRegistry` 初始化；P0 只收口 candidate write path。
- 不新增 BaseAgent memory hook。

本次是边界重构，不是检索算法重写。

## 4. 新增包结构

P0 只新增两个子包：

```text
sebastian/memory/
+-- contracts/
|   +-- __init__.py
|   +-- retrieval.py
|   +-- writing.py
+-- services/
    +-- __init__.py
    +-- memory_service.py
    +-- retrieval.py
    +-- writing.py
```

现有实现文件保持原位：

```text
sebastian/memory/retrieval.py
sebastian/memory/pipeline.py
sebastian/memory/extraction.py
sebastian/memory/consolidation.py
sebastian/memory/profile_store.py
sebastian/memory/episode_store.py
sebastian/memory/entity_registry.py
sebastian/memory/resolver.py
sebastian/memory/write_router.py
sebastian/memory/slot_definition_store.py
sebastian/memory/slot_proposals.py
sebastian/memory/resident_snapshot.py
```

目录整理放到后续 P1。只有当外部调用方都切到 facade 之后，再做文件搬迁。

## 5. Contracts

Contracts 是 service 边界使用的 Pydantic models 或 dataclasses。它们不应该向调用方暴露 SQLAlchemy session、store class，或者实现细节里的 lane 对象。

### 5.1 Retrieval Contracts

`sebastian/memory/contracts/retrieval.py`

```python
class PromptMemoryRequest(BaseModel):
    session_id: str
    agent_type: str
    user_message: str
    subject_id: str
    resident_record_ids: set[str] = Field(default_factory=set)
    resident_dedupe_keys: set[str] = Field(default_factory=set)
    resident_canonical_bullets: set[str] = Field(default_factory=set)


class PromptMemoryResult(BaseModel):
    section: str


class ExplicitMemorySearchRequest(BaseModel):
    query: str
    session_id: str
    agent_type: str
    subject_id: str
    limit: int = 5


class ExplicitMemorySearchResult(BaseModel):
    items: list[dict[str, Any]]
```

说明：

- `PromptMemoryResult.section` 保持当前生成的 Markdown section，不改变格式。
- `ExplicitMemorySearchResult.items` P0 可以镜像当前工具输出结构。保留这个 contract 是为了未来能在稳定边界后面引入更丰富的 citation 对象。
- request 携带 `subject_id`；根据入口不同，可以由调用方传入，也可以由 service 内部派生。P0 不改变 `resolve_subject()` 语义。

### 5.2 Writing Contracts

`sebastian/memory/contracts/writing.py`

```python
class MemoryWriteRequest(BaseModel):
    candidates: list[CandidateArtifact]
    proposed_slots: list[ProposedSlot] = Field(default_factory=list)
    session_id: str
    agent_type: str
    worker_id: str
    model_name: str | None = None
    rule_version: str
    input_source: dict[str, Any]
    proposed_by: Literal["extractor", "consolidator"] = "extractor"


@dataclass
class MemoryWriteResult:
    decisions: list[ResolveDecision] = field(default_factory=list)
    proposed_slots_registered: list[str] = field(default_factory=list)
    proposed_slots_rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def saved_count(self) -> int: ...

    @property
    def discarded_count(self) -> int: ...
```

`MemoryWriteResult` 必须使用 dataclass，对齐现有 `PipelineResult` 的语义。它不是 API response model，不依赖 `model_dump()`；调用方如果需要用户可见输出，应显式转换为 `MemorySaveResult` 或工具 output dict。

## 6. Services

### 6.1 MemoryService

`sebastian/memory/services/memory_service.py`

`MemoryService` 是运行时 memory 操作的单一组合入口。

```python
class MemoryService:
    def __init__(
        self,
        *,
        db_factory: async_sessionmaker[AsyncSession],
        retrieval: MemoryRetrievalService | None = None,
        writing: MemoryWriteService | None = None,
        resident_snapshot_refresher: ResidentMemorySnapshotRefresher | None = None,
        memory_settings_fn: Callable[[], bool] | None = None,
    ) -> None: ...

    async def retrieve_for_prompt(self, request: PromptMemoryRequest) -> PromptMemoryResult: ...

    async def search(self, request: ExplicitMemorySearchRequest) -> ExplicitMemorySearchResult: ...

    async def write_candidates(self, request: MemoryWriteRequest) -> MemoryWriteResult: ...

    async def write_candidates_in_session(
        self,
        request: MemoryWriteRequest,
        *,
        db_session: AsyncSession,
        profile_store: ProfileMemoryStore,
        episode_store: EpisodeMemoryStore,
        entity_registry: EntityRegistry,
        decision_logger: MemoryDecisionLogger,
        slot_registry: SlotRegistry,
        slot_proposal_handler: SlotProposalHandler | None,
    ) -> MemoryWriteResult: ...
```

`MemoryService` 负责跨链路运行时决策：

- memory enabled / disabled 检查。
- DB factory 可用性检查。
- 将非预期检索失败转换为空结果。
- 成功写入后标记 resident snapshot dirty。
- 在 service 边界写 trace log。

它不直接实现检索评分，也不直接实现冲突解决。

`memory_settings_fn` 只返回 `bool`，不能引用 `sebastian.gateway.state.MemoryRuntimeSettings`，避免 `memory -> gateway` 循环依赖。`None` 表示默认启用。

`retrieval` / `writing` 参数用于测试注入；未传入时，`MemoryService.__init__` 默认构造 `MemoryRetrievalService()` 和 `MemoryWriteService(db_factory=db_factory)`。

`MemoryService.retrieve_for_prompt()` 和 `MemoryService.search()` 由 `MemoryService` 负责 `async with db_factory()` 打开 session，并把 session 传给 `MemoryRetrievalService`。`MemoryRetrievalService` 不持有 `db_factory`，只负责在给定 session 上执行检索。

`write_candidates_in_session()` 是给 `SessionConsolidationWorker` 使用的顶层 caller-owned 事务入口。它委托 `MemoryWriteService.write_candidates_in_session()`，但不要求调用方直接访问 `memory_service.writing` 子服务。

### 6.2 MemoryRetrievalService

`sebastian/memory/services/retrieval.py`

P0 实现只是当前检索函数的薄适配层：

```text
MemoryService.retrieve_for_prompt()
  -> async with db_factory() as db_session
  -> MemoryRetrievalService.retrieve_for_prompt(request, db_session=db_session)

MemoryRetrievalService.retrieve_for_prompt(request, db_session)
  -> build RetrievalContext
  -> call existing retrieve_memory_section()
  -> return PromptMemoryResult(section=...)
```

`MemoryRetrievalService.search()` 应包住当前 `memory_search` 工具使用的显式记忆搜索路径。如果当前工具中存在 inline lane 逻辑，应把这部分逻辑移动到 service 后面，但不改变输出结构。

规则：

- 自动 prompt 注入继续使用 `access_purpose="context_injection"`。
- 显式工具搜索继续使用 `access_purpose="tool_search"`。
- 当前 lane planner、confidence thresholds、resident dedupe、assembler 行为全部保持不变。

未来 retriever 可以挂在这个 service 后面：

```text
MemoryRetrievalService
  +-- LaneMemoryRetriever        # 当前 P0 行为
  +-- EmbeddingProfileRetriever  # 未来局部 lane 升级
  +-- GraphBundleRetriever       # 未来 M-flow 风格 topology retrieval
```

P0 不需要提前实现完整 class hierarchy，除非实现时确有必要。关键点是调用方依赖 `MemoryRetrievalService`，而不是直接依赖 `retrieval.py`。

### 6.3 MemoryWriteService

`sebastian/memory/services/writing.py`

P0 实现包住现有写入 pipeline：

```text
MemoryWriteService.write_candidates()
  -> open db session or use caller-owned session
  -> construct ProfileMemoryStore / EpisodeMemoryStore / EntityRegistry
  -> construct MemoryDecisionLogger / SlotProposalHandler
  -> call existing process_candidates()
  -> return MemoryWriteResult
```

事务所有权必须显式：

- 对 `memory_save` 来说，service 可以拥有 session 并提交事务，因为工具调用本身就是顶层写入操作。
- 对 `SessionConsolidationWorker` 来说，现有 worker transaction 必须继续作为事务 owner。service 应支持 caller-owned `db_session` 路径，或提供一个不 commit 的内部 helper。

这个区别很重要：consolidation 当前会在同一个事务里写 summary、proposed artifacts、EXPIRE decisions 和 idempotency marker。P0 不能拆散这个原子边界。

## 7. 运行时接线

### 7.1 Gateway State

在 `sebastian/gateway/state.py` 增加 memory service 单例：

```python
memory_service: MemoryService | None = None
```

在 gateway lifespan 中，等 DB factory 和 memory runtime 依赖可用后初始化：

```text
init DB/store
-> init memory storage / slot registry / resident snapshot
-> create MemoryService
-> assign state.memory_service
-> continue agent/runtime startup
```

除非未来 service 自己启动后台任务，否则 shutdown 不需要额外 cleanup；继续复用现有 resident snapshot 和 memory scheduler cleanup。

### 7.2 BaseAgent Prompt 注入

`BaseAgent._memory_section()` 应停止直接 import `retrieve_memory_section()`。

新流程：

```text
BaseAgent._memory_section()
  -> depth guard
  -> resolve subject_id
  -> build PromptMemoryRequest
  -> state.memory_service.retrieve_for_prompt()
  -> return result.section
```

如果 `state.memory_service` 不存在，返回 `""` 并继续无记忆上下文执行，保持当前 fail-closed 行为。`BaseAgent` 不再直接检查 `state.memory_settings.enabled`；enabled 检查统一由 `MemoryService` 处理，避免 feature flag 逻辑分散在多个调用方。

P0 中 resident snapshot 读取路径保持独立。它产生的 dedupe sets 传入 `PromptMemoryRequest`。

### 7.3 memory_search 工具

`memory_search` 工具应调用 `state.memory_service.search()`，不再直接组装 retrieval 内部逻辑。

输出必须兼容当前工具契约：

- 相同 item 字段。
- 相同 `citation_type`。
- 相同 lane-aware effective limit 行为。
- 相同显式搜索 confidence 行为。

### 7.4 memory_save 工具

`memory_save` 工具保持当前用户可见契约。拿到 extractor 输出后，调用：

```text
state.memory_service.write_candidates(MemoryWriteRequest(...))
```

如果成功 commit 且至少保存一条非 DISCARD 记忆，service 应标记 resident snapshot dirty。

### 7.5 Session Consolidation Worker

`SessionConsolidationWorker` 必须继续拥有自己的 transaction 和 idempotency marker。

在现有事务内，将直接 `process_candidates()` 调用替换为 caller-owned-session service 方法，例如：

```python
await memory_service.write_candidates_in_session(
    request,
    db_session=db_session,
    profile_store=profile_store,
    episode_store=episode_store,
    entity_registry=entity_registry,
    decision_logger=decision_logger,
    slot_registry=slot_registry,
    slot_proposal_handler=slot_proposal_handler,
)
```

这个 helper 不允许 commit。

P0 中 EXPIRE actions 继续 inline 处理，因为它们面向已有 memory_id，而不是候选 artifact。后续如果要把 EXPIRE 也收进 service，需要先定义明确的 lifecycle contract。

Consolidation 内部为了让 Entity 写入后刷新 planner 触发词，仍可直接使用 `DEFAULT_RETRIEVAL_PLANNER` 构造 `EntityRegistry`。这条 retrieval/planner 依赖 P0 不迁移。

## 8. 错误处理

P0 保持当前降级行为：

- Prompt retrieval 失败返回空 section。
- 显式搜索失败返回 `ok=false` 或当前工具错误结构。
- 写入失败在同步调用方路径中记录日志并返回给调用方。
- Consolidation task 失败继续由 scheduler / worker 路径记录日志。
- LLM 输出仍然永远不能直接写数据库。

`MemoryService` 应集中处理边界日志，避免未来实现重复写通用 error wrapper。

## 9. 未来扩展点

### 9.1 P1 目录重组

当 P0 调用方都依赖 service 后，内部文件可以安全移动：

```text
retrieval.py       -> retrieval/lane.py
pipeline.py        -> writing/pipeline.py
resolver.py        -> writing/resolver.py
profile_store.py   -> storage/profile.py
episode_store.py   -> storage/episode.py
entity_registry.py -> topology/entities.py
resident_snapshot.py / resident_dedupe.py -> snapshot/
```

这应该是单独的机械 PR，只做 import 行为不变的搬迁。

### 9.2 P2 Graph-Routed Retrieval

M-flow 风格检索应进入 `MemoryRetrievalService` 后面，而不是直接进入 BaseAgent 或 tools。

未来概念可放在 `topology/` 下：

- `EpisodeBundle`
- `Facet`
- `FacetPoint`
- `EvidencePath`
- `PathCostScorer`

service 边界应允许 `GraphBundleRetriever` 在内部保留更丰富 citation 的同时，对外继续返回相同的 prompt-section 和 explicit-search contracts。

### 9.3 P3 Maintenance Service

decay、dedupe、re-index、stale running repair、summary replacement 等维护任务，未来应通过 `MemoryMaintenanceService` 执行。scheduler jobs 不应直接调用底层 store。

## 10. 迁移计划

P0 应按小步、行为保持的方式实现：

1. 新增 `contracts/` models。
2. 新增包住当前 prompt retrieval 的 `MemoryRetrievalService`。
3. 新增包住当前 `process_candidates()` 的 `MemoryWriteService`。
4. 新增 `MemoryService` composition root。
5. 在 gateway lifespan 初始化 `state.memory_service`。
6. 将 `BaseAgent._memory_section()` 迁移到 service。
7. 将 `memory_search` 迁移到 service。
8. 将 `memory_save` 迁移到 service。
9. 将 `SessionConsolidationWorker` 的候选写入迁移到 service helper，同时保留事务所有权。
10. 更新 README 和架构文档。

每一步都应保持测试通过。

## 11. 测试策略

### 11.1 单元测试

- `MemoryRetrievalService.retrieve_for_prompt()` 构造预期 `RetrievalContext`，并返回现有 section string。
- Prompt retrieval 失败时返回空 section 并记录 warning。
- `MemoryWriteService.write_candidates()` 委托 `process_candidates()`，saved / discarded count 保持不变。
- caller-owned write path 不 commit。
- service-owned write path 只在 pipeline 成功完成后 commit。
- 只有至少保存一条 memory 时才标记 resident snapshot dirty。
- memory disabled 时返回空 prompt result，且不访问 store。

### 11.2 集成测试

- BaseAgent memory prompt 输出与现有 fixture 保持一致。
- `memory_search` 返回相同 item 字段和 `citation_type`。
- `memory_save` 返回相同 `MemorySaveResult` 摘要。
- Session consolidation 仍在同一事务中写 candidate artifacts 和 idempotency marker。
- 现有 memory retrieval / pipeline 测试继续通过。

## 12. 文档更新

实现时应更新：

- `sebastian/memory/README.md`
- `docs/architecture/spec/memory/INDEX.md`
- `docs/architecture/spec/memory/overview.md`
- `docs/architecture/spec/memory/retrieval.md`
- `docs/architecture/spec/memory/write-pipeline.md`

文档应描述新的 service 边界，但不能声称 graph-routed retrieval 或目录重组已经实现。

## 13. 验收标准

- `BaseAgent`、`memory_search`、`memory_save` 和 consolidation candidate writes 调用 memory service facade，而不是直接 import 顶层 retrieval 或 pipeline 内部实现。
- 不引入 memory 数据库 schema 变更。
- 不改变现有 memory prompt section 格式。
- 不改变现有 memory tool 输出结构。
- Consolidation transaction ownership 保持不变。
- Resident snapshot dedupe 对 dynamic retrieval 仍然生效。
- 现有 memory unit / integration tests 通过。
- 新增 service-level tests 覆盖 retrieval、writing、disabled-memory 行为和 caller-owned transaction 行为。

## 14. 不变量

- LLM 输出仍然只是候选，不允许直接修改数据库。
- P0 中 `process_candidates()` 仍是唯一写入 pipeline。
- P0 中 `retrieve_memory_section()` 仍是 prompt retrieval 实现。
- `MemoryService` 是 facade，不是新的 memory business rules 来源。
- 自动 prompt retrieval 和显式工具 search 继续使用不同 access purpose。
- current truth 与 historical evidence 在 prompt assembly 中继续分离。
- P0 必须可逆：如果需要，调用方可以切回现有函数；本次不应把行为改动和抽象改动纠缠在一起。
