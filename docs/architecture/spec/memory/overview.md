---
version: "1.3"
last_updated: 2026-05-03
status: in-progress
---

# Memory（记忆）总体架构

> 模块索引：[INDEX.md](INDEX.md)
> 架构图：[../../diagrams/memory/overview.html](../../diagrams/memory/overview.html)

---

## 1. 设计目标

Sebastian 的记忆系统必须同时覆盖三类能力：

1. **个人画像**：稳定记住用户偏好、身份信息、长期事实，并在新信息到来时正确更新
2. **对话回忆**：能回想过去讨论过什么、做过什么、作出过哪些决定
3. **动态状态**：能区分“过去成立”和“当前成立”，避免把旧事实当成现状

工程目标：

- 先把边界设计对，再分阶段实现
- 后续增加关系图、图谱检索、记忆 UI 时不推翻主模型
- 写入、检索、沉淀、审计走统一协议

---

## 2. 非目标

首期不要求立即实现：

- 复杂图数据库或多跳图推理
- 记忆管理 UI
- 多用户权限模型完整产品化
- 外部知识库批量导入与治理
- 向量数据库、embedding（向量嵌入）、hybrid retrieval（混合检索）

---

## 3. 逻辑模型

Sebastian 的长期记忆采用三层逻辑模型：

| 层 | 职责 |
|----|------|
| `ProfileMemory`（画像记忆） | 用户画像、偏好、长期事实、当前状态 |
| `EpisodicMemory`（情景/经历记忆） | 事件、经历、任务过程、会话回忆、阶段摘要 |
| `RelationalMemory`（关系记忆） | 实体、关系、时间区间、多实体语义连接 |

---

## 4. 首期物理落地

首期物理实现采用：

- `Profile Store`（画像存储）
  - 承载 `fact` / `preference`
- `Episode Store`（经历存储）
  - 承载 `episode` / `summary`
- `Entity Registry`（实体注册表）
  - 承载实体规范化与 alias lookup
- `Relation Layer`（关系层）
  - 首期至少落 `relation_candidates`，不要求成为主查询依赖
- `memory_decision_log`（记忆决策日志）
  - 首期即落盘，支持审计、调试和后续 UI

设计理由：

- “事实/画像”和“经历/回忆”的数据本质不同，必须分开优化更新规则和检索规则
- 关系图层是高价值增强层，但不适合作为 Day 1 主存储
- 首版先把“记忆是否正确”做好，再增强“语义召回是否最强”

---

## 5. 与现有架构集成

### 5.0 MemoryService — 顶层访问边界

`MemoryService`（`sebastian/memory/services/memory_service.py`）是记忆系统对外的**唯一访问边界**。所有外部调用方均通过 `MemoryService` 接入，不直接调用 `stores/`、`retrieval/` 或 `writing/` 内部实现。

```
外部调用方
  ├── BaseAgent._memory_section()        → MemoryService.retrieve_for_prompt()
  ├── memory_search 工具                  → MemoryService.search()
  ├── memory_save 工具                    → MemoryService.write_candidates()
  └── SessionConsolidationWorker         → MemoryService.write_candidates_in_session()
                         │
                         ▼
              MemoryRetrievalService      封装 retrieve_memory_section()
              MemoryWriteService          封装 process_candidates()
                         │
                         ▼
              retrieval/ / writing/       内部实现子包
```

`contracts/` 子包（`contracts/retrieval.py`、`contracts/writing.py`）定义服务边界的 Pydantic 入参与返回值模型，与内部实现解耦。

图路由检索（graph-routed retrieval）为 P1/P2 后续工作，当前不实现。

### 5.0.1 Memory 内部包结构

当前 `sebastian/memory/` 已按 facade 后的内部职责拆分：

```text
memory/
├── contracts/       # PromptMemoryRequest / ExplicitMemorySearchRequest / MemoryWriteRequest
├── services/        # MemoryService / MemoryRetrievalService / MemoryWriteService
├── stores/          # ProfileMemoryStore / EpisodeMemoryStore / EntityRegistry / SlotDefinitionStore
├── writing/         # process_candidates / resolver / write_router / decision_log / slots
├── retrieval/       # RetrievalPlanner / Assembler / lexicon / depth guard / segmentation
├── consolidation/   # MemoryExtractor / MemoryConsolidator / SessionConsolidationWorker
└── resident/        # ResidentMemorySnapshotRefresher / resident_dedupe
```

根目录只保留跨链路基础模块：`types.py`、`subject.py`、`trace.py`、`constants.py`、`errors.py`、`startup.py`、`store.py`、`working_memory.py`。

依赖方向：

```text
external callers
  → memory.contracts / memory.services
      → memory.retrieval / memory.writing / memory.consolidation / memory.resident / memory.stores
```

Gateway startup 是运行时装配层，允许直接 import memory 内部组件做初始化（storage、slot registry、planner entity triggers、consolidation scheduler、resident snapshot、MemoryService 创建），但请求处理路径和工具路径不得绕过 `MemoryService` 直接读写 memory 业务数据。

### 5.1 WorkingMemory

`WorkingMemory`（工作记忆）继续作为进程内、任务级临时状态，不纳入长期记忆体系。

### 5.2 SessionStore 与 Episode Store

会话对话历史由 `SessionStore` 直接管理；`BaseAgent` 通过 `SessionStore.get_context_messages()` 读取上下文，通过 `append_message()` / timeline 写入消息与 blocks。主对话历史不经过 Memory 模块。

`EpisodeMemoryStore`（`sebastian/memory/stores/episode_store.py`）是长期可检索回忆层，存储 `episode` / `summary` artifacts，并通过 FTS 与时间排序支撑 Episode Lane 检索。它建立在 session history 之上，不替代 `SessionStore`。

### 5.3 BaseAgent Memory 入口

BaseAgent 的长期记忆注入分为两个阶段，按固定顺序拼入 system prompt：

```
base system prompt
→ [resident] 常驻记忆快照（_resident_memory_section）
→ [dynamic]  动态检索记忆（_memory_section）
→ [todos]    当前待办
```

**常驻记忆快照**（`_resident_memory_section()`）：从预渲染的 Markdown 快照文件中读取高置信用户画像，每轮固定注入。快照由 `ResidentMemorySnapshotRefresher` 维护，在记忆沉淀完成后异步重建，gateway startup 时触发一次全量重建。优点：零 DB 查询延迟；缺点：最多落后一个沉淀周期。

**动态检索记忆**（`_memory_section()`）：通过 `MemoryRetrievalPlanner` + 四条 lane 按轮次检索，内容更及时但增加 DB IO。`MemorySectionAssembler` 在装配时会过滤掉已出现在常驻快照中的记录（通过 `RetrievalContext` 中的三个去重字段），避免重复注入。

两者均不感知对方内部实现；`BaseAgent._stream_inner()` 负责拼接顺序。短期不拆出独立的 BaseAgent planner hook 或 assembler hook，避免把 Memory 内部策略泄漏到 Agent 运行时。

后台沉淀也不由 BaseAgent 的 turn end / idle hook 直接触发。当前会话沉淀由 `SESSION_COMPLETED` 事件和 startup catch-up sweep 驱动；如果未来需要 `idle` / `stalled` 触发，应先补独立 spec，明确触发条件、幂等标记和与未完成 session 的边界。

显式 `memory_*` 能力不是新的 BaseAgent hook。它们是通过现有 Native Tool 注册系统暴露给 Agent 的普通工具，不经过 `_memory_section()`，也不绕过 `CapabilityRegistry`。

### 5.4 工具层

首期建议只提供两个 memory-facing（面向记忆系统的）Native Tool：

- `memory_save`
- `memory_search`

这两个工具与 `file_read`、`bash_execute` 等工具一样，放在 `sebastian/capabilities/tools/` 下，通过 `@tool(...)` 注册，并由现有 tools loader 自动扫描。它们的特殊性不在注册机制，而在工具背后调用的是 Memory 统一协议：

- `memory_save`：显式写入入口，仅在用户明确要求“记住这个”时使用，背后走 candidate artifact → resolve → persist → decision log。
- `memory_search`：显式检索入口，供 Agent 主动查询长期记忆，背后走 memory retrieval / store。

工具层只触发统一写入/读取协议，不直接绕过 Memory 模块操作底层表。

`memory_list` / `memory_delete` 不作为首期 agent 工具。它们更适合作为后续 owner-only（仅主人可用）的管理 API 或记忆管理 UI 能力，用于用户核查、纠错、删除敏感记忆。原因：

- 常规对话中，Agent 需要的是按需检索，而不是枚举全部记忆
- 删除记忆属于高影响操作，应该有更明确的用户确认和审计
- 过早暴露给 Agent 会增加误删、越权查看或 prompt injection（提示词注入）风险

---

## 6. 分阶段实现与当前进度

| Phase | 当前状态 | 目标 | 内容 / 边界 |
|-------|----------|------|-------------|
| A | 已实现 | 协议先行 | artifact schema（记忆产物结构）、slot registry（语义槽位注册表）、resolution policy（冲突解决策略）、retrieval planner / assembler、decision log schema（决策日志结构）已落地 |
| B | 已实现，审查修复中 | Profile + Episode 可用版 | fact/preference（事实/偏好）写入更新注入、episode/summary（经历/摘要）存储检索、基础 lane、decision log（决策日志）落盘已可用；当前修复聚焦 current truth 过滤、Episode Lane summary-first、审计字段补齐 |
| C | 部分实现 | Consolidation 成熟版 | session consolidation（会话沉淀）、startup catch-up sweep 与 EXPIRE 生命周期处理已实现；cross-session preference strengthening（跨会话偏好强化）、maintenance worker（维护任务）、降权、重复压缩、索引修复需单独 spec |
| D | 部分实现 | Relation / Graph 增强 | entity normalization（实体规范化）、relation candidate 入库、relation lane（关系检索通道）与时间区间检索已实现；exclusive relation 边界覆盖、正式 relation facts / graph 查询语义需单独 spec |
| E | 已实现 | 常驻记忆快照 | `ResidentMemorySnapshotRefresher` + `resident_dedupe.py` 已实现；快照文件按高置信画像预渲染，每轮固定注入，动态检索去重；详见 [设计文档](../../../../superpowers/specs/2026-04-26-resident-memory-snapshot-design.md) |

需要单独讨论 spec 的事项：

- summary 默认替换策略：何时替换、何时追加、如何保留历史 evidence。
- exclusive relation 时间边界覆盖：新关系如何关闭旧关系，是否只基于同一 subject / predicate / object set。
- Cross-Session Consolidation：触发频率、证据合并、幂等 key、人工审核边界。
- Memory Maintenance：降权、重复压缩、索引修复、周期性 sweep 的触发与审计。
- Relation facts / graph：`relation_candidates` 何时晋升为正式事实，以及 Relation Lane 是否需要多跳查询。

---

*← 返回 [Memory 索引](INDEX.md)*
