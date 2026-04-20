# Memory 读写链路详解

> 上级索引：[README.md](README.md)

本文档以代码为准，逐层描述 Memory 系统的两条核心链路：
**读（检索注入）** 和 **写（沉淀入库）**。

---

## 一、读路径：每次 LLM turn 前注入

### 触发点

每次 `run_streaming()` 调用时，[`_stream_inner()`](base_agent.py) 在构造 `effective_system_prompt` 之前同步等待记忆检索：

```
BaseAgent._stream_inner()                        base_agent.py:466
  ├─ _memory_section(session_id, agent, user_msg)
  └─ effective_system_prompt = base_prompt + memory_section + todo_section
```

### `_memory_section()` — 入口守卫

[`base_agent.py:236`](../core/base_agent.py)

```
_memory_section()
  ├─ 检查 db_factory 是否存在
  ├─ 检查 state.memory_settings.enabled
  ├─ resolve_subject(MemoryScope.USER, session_id, agent_type)
  │    └─ 返回 subject_id（当前用户的唯一标识）
  └─ retrieve_memory_section(RetrievalContext, db_session)
```

任何一步失败（包括 DB 异常）都静默返回空字符串，不阻断对话。

### `retrieve_memory_section()` — 检索主流程

[`retrieval.py:322`](retrieval.py)

```
retrieve_memory_section(context, db_session)
  │
  ├─ [1] MemoryRetrievalPlanner.plan(context)
  │       ── 对 user_message 做关键词匹配，决定激活哪些通道：
  │
  │          通道            激活条件
  │          profile_lane    永远 ON（非 small-talk）
  │          context_lane    含"现在/今天/now/this week"等词
  │          episode_lane    含"上次/之前/记得/remember"等词
  │          relation_lane   含"老婆/孩子/项目/team"等词
  │
  ├─ [2] 按 plan 各通道分别查 DB（见下文通道详解）
  │
  └─ [3] MemorySectionAssembler.assemble()
          ── 过滤 + 截断 + 拼 Markdown，返回 str
```

### 各通道查库方式

#### profile_lane → `ProfileMemoryStore.search_active()`
[`profile_store.py:118`](profile_store.py)

**纯 SQL，不用 FTS。**

```sql
SELECT * FROM profile_memories
WHERE subject_id = ?
  AND status = 'active'
  AND (valid_until IS NULL OR valid_until > now)
  AND (valid_from IS NULL OR valid_from <= now)
ORDER BY confidence DESC, created_at DESC
LIMIT 5
```

全量 profile 按置信度拿 top-5，不做关键词匹配。

---

#### context_lane → `ProfileMemoryStore.search_recent_context()`
[`profile_store.py:148`](profile_store.py)

**FTS 优先，无结果时降级为纯 SQL。**

```
terms = jieba.cut_for_search(user_message)  → terms_for_query()

若有 terms：
  for term in terms:
      SELECT memory_id FROM profile_memories_fts
      WHERE content_segmented MATCH '"<term>"'
  ── 统计每条记录命中 term 数（Counter）
  ── 按命中数排 rank，回查主表
  ── 叠加 7 天时间窗口过滤

若无 terms 或 FTS 无结果：
  fallback → confidence DESC, created_at DESC，7 天内
```

---

#### episode_lane → summary-first 两阶段 FTS
[`episode_store.py:118`](episode_store.py) / [`episode_store.py:133`](episode_store.py)

**完全依赖 FTS，无 terms 时直接返回 []，不降级。**

```
stage 1: search_summaries_by_query()
  ── FTS MATCH episode_memories_fts WHERE kind='summary'
  ── 按 term 命中数 rank + recorded_at DESC

if len(summaries) >= episode_limit:
    直接用 summaries

else:
    remaining = episode_limit - len(summaries)
    stage 2: search_episodes_only()
      ── FTS MATCH episode_memories_fts WHERE kind='episode'
    episode_records = summaries + detail_records
```

summary 优先的设计意图：summary 是经过 Consolidator 归纳的高密度信息，优先注入；
detail 只在 summary 不够时补充，避免把低密度原始对话塞入 prompt。

---

#### relation_lane → `EntityRegistry.list_relations()`
[`entity_registry.py`](entity_registry.py)

**纯 SQL，不用 FTS。** 按 `subject_id` 过滤 `relation_candidates` 表，直接拿 top-N，不做语义匹配。

---

### `MemorySectionAssembler.assemble()` — 过滤与排版

[`retrieval.py:147`](retrieval.py)

每条记录过 `_keep()` 检查：

| 检查项 | 规则 |
|--------|------|
| `policy_tags` | `do_not_auto_inject` → 跳过；`access:<purpose>` / `agent:<type>` 不匹配 → 跳过 |
| `confidence` | < 0.3 → 跳过 |
| `valid_until` | <= now → 跳过 |
| `status` | != active → 跳过 |
| `subject_id` | 与 context.subject_id 不一致 → 跳过 |
| `valid_from` | > now（未生效）→ 跳过 |

通过后按通道 limit 截断，拼成如下 Markdown 注入 system prompt 末尾：

```markdown
## Current facts about user
- [fact] 用户偏好简短回复
- [preference] 偏好中文

## Current context
- [fact] 本周专注 Sebastian memory 模块

## Important relationships
- [relation] owner is_working_on Sebastian

## Historical evidence (may be outdated)
- [summary] 上次讨论了 memory 写入 pipeline 设计
```

---

## 二、写路径：记忆如何进库

### 两个入口

#### 入口 A：`memory_save` 工具（主动触发）

[`capabilities/tools/memory_save/__init__.py`](../capabilities/tools/memory_save/__init__.py)

Agent 在对话中调用 `memory_save(content)` 时：

```
memory_save(content)
  ├─ 立即返回 ToolResult(ok=True)  ← fire-and-forget，不阻塞对话
  └─ asyncio.create_task(_do_save(content, session_id, agent_type))

_do_save():
  ├─ 从 state 取 memory_extractor（app 启动时注入）
  ├─ resolve_subject() → subject_id
  ├─ 构造 ExtractorInput:
  │    ├─ subject_context: {subject_id, agent_type}
  │    ├─ conversation_window: [{role: "user", content: content}]
  │    └─ known_slots: DEFAULT_SLOT_REGISTRY.list_all() 序列化
  ├─ extractor.extract(input) → list[CandidateArtifact]
  ├─ 注入 session_id 到 evidence（审计追踪）
  └─ process_candidates(candidates, ...)  ← 统一写入管道
```

**known_slots 来源**：`DEFAULT_SLOT_REGISTRY` 是代码里硬编码的 6 个内置 slot（`_BUILTIN_SLOTS`），**不查库**，进程启动时固定在内存中。

---

#### 入口 B：会话结束自动沉淀（SESSION_COMPLETED 事件）

[`consolidation.py`](consolidation.py)

```
会话结束 → EventBus.publish(SESSION_COMPLETED)
  └─ MemoryConsolidationScheduler._handle()
       ├─ 检查 memory_enabled
       └─ asyncio.create_task(worker.consolidate_session(session_id, agent_type))

SessionConsolidationWorker.consolidate_session():
  ├─ [幂等] 若 SessionConsolidationRecord 已存在 → 直接返回
  ├─ 开单一 async 事务（所有写 + 标记插入都在同一事务）
  │
  ├─ [准备上下文] 在事务内查现有数据（让 LLM 看到全局状态）：
  │    ├─ profile_store.search_active()  ← 当前活跃 profile（top 32）
  │    ├─ episode_store.search_summaries()  ← 最近 summary（top 8）
  │    └─ entity_registry.snapshot()  ← 实体快照（top 64）
  │
  ├─ [Step 4a] MemoryExtractor.extract(messages)
  │    └─ 从对话窗口提取候选 artifacts
  │
  ├─ [Step 5] MemoryConsolidator.consolidate(ConsolidatorInput)
  │    ├─ 输入：messages + extractor 结果 + 活跃记忆 + slot 定义 + 实体快照
  │    └─ 输出：ConsolidationResult
  │         ├─ summaries: 会话级摘要
  │         ├─ proposed_artifacts: 建议写入的 artifacts
  │         └─ proposed_actions: EXPIRE 动作
  │
  ├─ summaries → 转成 CandidateArtifact(kind=SUMMARY, confidence=0.8)
  ├─ process_candidates(summaries + proposed_artifacts)  ← 统一写入管道
  │
  ├─ [EXPIRE] 对每个 EXPIRE 类 proposed_action：
  │    └─ 直接构造 ResolveDecision(EXPIRE) → persist_decision()
  │       （EXPIRE 不走 process_candidates，因为它针对已有 memory_id，而非候选）
  │
  ├─ 插入 SessionConsolidationRecord（幂等标记）
  └─ commit（若并发已提交 → IntegrityError → rollback → 返回）
```

**Extractor 和 Consolidator 的分工**：

| 组件 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `MemoryExtractor` | 从对话逐条提取细粒度事实 | 对话消息 + known_slots | `list[CandidateArtifact]` |
| `MemoryConsolidator` | 在 Extractor 结果基础上做跨轮归纳，提出生命周期变更 | 全部上下文（含 Extractor 输出） | `ConsolidationResult`（summaries + artifacts + actions） |

两者都只产出"建议"，**不直接写库**。

---

### 统一写入管道：`process_candidates()`

[`pipeline.py:22`](pipeline.py)

`memory_save` 工具和 Consolidation 都汇入此函数：

```
for each CandidateArtifact:

  [1] resolve_subject(candidate.scope, session_id, agent_type)
       └─ 按 scope（USER/PROJECT/AGENT）确定 subject_id

  [2] slot_registry.validate_candidate(candidate)
       规则：
         ├─ kind == fact/preference → slot_id 不能为 None
         ├─ slot_id 必须在 DEFAULT_SLOT_REGISTRY 里注册
         └─ kind 必须符合该 slot 的 kind_constraints
       失败 → DISCARD + decision_log，跳过此 candidate

  [3] resolve_candidate()   resolver.py:58   ← 纯确定性，不查 LLM，不写 DB
       ├─ kind == EPISODE/SUMMARY
       │    └─ find_active_exact() → 精确重复? DISCARD : ADD
       ├─ 无 slot_id + confidence < 0.3 → DISCARD
       ├─ MERGE policy + 精确匹配现有记录 → MERGE（走 supersede 路径）
       ├─ MULTI cardinality / APPEND_ONLY policy → ADD
       ├─ SINGLE cardinality
       │    ├─ get_active_by_slot() 无记录 → ADD
       │    ├─ 新候选 source rank 低 + confidence 不高于阈值 → DISCARD
       │    └─ 否则 → SUPERSEDE（替换所有旧记录）
       └─ fallback → ADD

  [4] 非 DISCARD → persist_decision()   write_router.py:17
       按 kind 路由到对应 store：
         EPISODE / SUMMARY → EpisodeMemoryStore.add_episode / add_summary()
         ENTITY            → EntityRegistry.upsert_entity()
         RELATION          → 写 relation_candidates 表
         FACT / PREFERENCE
           SUPERSEDE/MERGE → profile_store.supersede()（expire 旧 + add 新）
           ADD             → profile_store.add()（含同步写 FTS 虚拟表）

  [5] decision_logger.append()   ← 所有决策（含 DISCARD）写 memory_decision_log
```

**核心约束**：LLM 永远不直接修改记忆状态。Extractor 和 Consolidator 的输出都是"候选"，必须经过 Resolver → persist_decision 才能落库。

---

## 三、Slot 系统与 LLM 的边界

LLM **不能创造新 slot**。流程是：

1. `known_slots`（6 个内置 slot 的定义）序列化后随 `ExtractorInput` 传给 LLM
2. LLM 从中选择合适的 `slot_id` 填入 `CandidateArtifact`
3. `pipeline.py` 的 `validate_candidate()` 拦截任何未注册的 `slot_id` → DISCARD

新增 slot 只有一条路：修改 `slots.py` 的 `_BUILTIN_SLOTS` 列表并重启，无运行时动态注册机制。

---

## 四、FTS 分词机制

[`segmentation.py`](segmentation.py)

写入时：`segment_for_fts(content)` → jieba 搜索模式分词 → 空格连接存入 `content_segmented` 列（FTS 虚拟表）

查询时：`terms_for_query(query)` → jieba 分词 → 过滤长度 ≤ 1 的 token → 每个 term 单独做 `MATCH '"<term>"'`（双引号防止 FTS5 运算符注入）

命中计数：`Counter(memory_id)` 统计每条记录命中多少个 term，命中越多排名越靠前。

---

## 五、关键区分

| 易混淆 | 实际区别 |
|--------|---------|
| `EpisodicMemory` vs `EpisodeMemoryStore` | `EpisodicMemory`（episodic_memory.py）是**会话消息历史兼容层**，底层是 `SessionStore`，和长期记忆无关。`EpisodeMemoryStore`（episode_store.py）才是长期 Episode/Summary 的 CRUD。 |
| profile_lane 为何永远开 | 用户画像（偏好/事实）对任何非 small-talk 请求都有价值，是最基础的上下文，无条件激活。 |
| EXPIRE 为何不走 process_candidates | EXPIRE 针对**已有 memory_id**（生命周期操作），`process_candidates` 针对**未入库的候选 artifact**，语义不同，不能混用。 |
| context_lane 和 episode_lane 的 FTS 降级差异 | context_lane 在无 FTS 结果时降级为 confidence+recency 排序；episode_lane 无 terms 时直接返回 `[]`，不降级。 |

---

*← 返回 [README.md](README.md)*
