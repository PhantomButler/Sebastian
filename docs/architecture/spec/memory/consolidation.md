---
version: "1.1"
last_updated: 2026-05-03
status: partially-implemented
---

# Memory（记忆）后台沉淀与审计

> 模块索引：[INDEX.md](INDEX.md)
> 架构图：[../../diagrams/memory/consolidation.html](../../diagrams/memory/consolidation.html)

---

## 实现状态速览

| 模块 | 状态 | 备注 |
|------|------|------|
| Session Consolidation | **implemented** | `SessionConsolidationWorker` + startup catch-up sweep 已实现 |
| Cross-Session Consolidation | **planned** | 需单独 spec 设计触发频率、扫描窗口、证据合并规则、幂等 key |
| Memory Maintenance（过期扫描） | **partial** | EXPIRE 动作和 catch-up sweep 已有；降权、重复压缩、索引修复 planned |

---

## 1. Consolidation（后台沉淀）不是单一 Worker（后台任务）

后台沉淀至少分三类职责：

### 1.1 Session Consolidation（会话沉淀）

针对单次 session 在 `completed` 后做：

- 生成阶段摘要
- 提取候选事实、偏好、关系
- 产生新的 artifacts
- 对已有记忆提出生命周期操作（如 EXPIRE）

#### ConsolidationResult 三个输出字段的语义分工

| 字段 | 操作对象 | 是否经过 Resolver | 说明 |
|------|----------|-------------------|------|
| `summaries` | 不存在的新摘要 | 是（走 resolve_candidate） | Consolidator 生成的会话摘要，经 resolver 判断是否 ADD/DISCARD |
| `proposed_artifacts` | 不存在的新候选记忆 | 是（走 resolve_candidate） | Consolidator 提议的新 fact/preference/episode/entity/relation，最终 ADD/SUPERSEDE/MERGE/DISCARD 由 resolver 决定，LLM 不直接控制 |
| `proposed_actions` | 数据库中已存在的记忆（by memory_id） | 否（直接执行） | Consolidator 对已有记忆提出生命周期操作，唯一合法值为 `EXPIRE` |

#### proposed_actions 的定位与边界

`proposed_actions` 解决的是 `proposed_artifacts → resolver` 路径**无法覆盖的场景**：

- `proposed_artifacts` + resolver 处理"新候选 vs 现有记录的冲突"，resolver 产出 SUPERSEDE 时同时有 old_id 和 new_memory
- 但有一类场景是"**不需要新记忆、只需要让旧记忆失效**"：某条 active 事实没有设置 `valid_until`，但 Consolidator 从本次会话语义中判断它已经不再成立

典型例子：上次记录了 `user.current_project_focus = "项目 A"`（无截止时间），本次会话用户说"已把项目 A 交给别人了"。Consolidator 通过 `proposed_actions EXPIRE + memory_id` 把该记录显式标为 `expired`，无需产生替代记忆。

这与 `valid_until` 自动失效的区别：

| | `valid_until` 到期 | `proposed_actions EXPIRE` |
|---|---|---|
| 触发方式 | 写入时设定，检索层过滤 | Consolidator 从会话语义主动判断 |
| 适用场景 | 已知时效性的事实 | 无截止时间但被新对话语义推翻的事实 |
| DB status 变化 | 无需改变（过滤层排除） | 显式从 active 改为 expired |
| 需要 memory_id | 否 | 是 |

**约束：**

- `proposed_actions.action` 只允许 `"EXPIRE"`；ADD/SUPERSEDE 的语义由 `proposed_artifacts → resolver` 路径承担，不在此处执行
- `memory_id` 必须非空且指向 active 的 profile memory 记录；0 命中时记录 `failed_expire` decision log，不写成功状态
- 所有 EXPIRE 操作必须进入 `memory_decision_log`

**Phase C 实现状态**：`SessionConsolidationWorker`（`sebastian/memory/consolidation/consolidation.py`）已实现，由 `MemoryConsolidationScheduler` 订阅 `SESSION_COMPLETED` 事件触发。幂等性通过 `SessionConsolidationRecord(session_id, agent_type)` DB 标记保证；写入原子性通过单事务实现。启动时的 catch-up sweep 会补处理未沉淀的 completed session。候选 artifacts 写入通过注入的 `MemoryService.write_candidates_in_session()` 完成，consolidation 继续拥有事务和幂等 marker，不在内部读取 gateway global state。

`consolidation/` 子包边界：

| 文件 | 职责 |
|------|------|
| `consolidation.py` | `MemoryConsolidator`、`SessionConsolidationWorker`、`MemoryConsolidationScheduler`、startup catch-up sweep |
| `extraction.py` | `MemoryExtractor` 与 slot 拒绝重试 |
| `prompts.py` | Extractor / Consolidator 共享 prompt 模板 |
| `provider_bindings.py` | `memory_extractor` / `memory_consolidator` binding 常量与 component metadata |

`idle` / `stalled` 触发当前不属于已实现契约。未来如果需要支持，应先补独立 spec，明确：

- 什么状态算 session idle / stalled。
- 是否允许对仍可能继续追加消息的 session 做沉淀。
- 幂等标记如何区分部分沉淀与最终沉淀。
- 后续 `SESSION_COMPLETED` 到来时如何避免重复摘要和重复写入。

### 1.2 Cross-Session Consolidation（跨会话沉淀）

针对多个已沉淀 session 做偏好强化、模式归纳、多来源证据合并。

**实现状态**：未实现，本节为完整 spec。

#### 职责边界

Cross-Session Consolidation **不重复处理原始 session 消息**，只看已经 session-consolidated 过的结果：

- 现有 `active` profile 记忆（含 `inferred` / `observed` 来源）
- 近期 summaries
- 低置信候选 artifacts（`confidence < 0.75`）

目标是识别跨多个 session 稳定出现的模式，将多次印证的 `inferred` 事实提升置信度，将长期稳定偏好固化为更高可信的记忆。

#### 触发机制

**计数触发**：每当累计新增 **10 个** session-consolidated session 后，触发一次 Cross-Session Consolidation。

触发判断逻辑：
1. 读取 `CrossSessionConsolidationRecord` 中最近一次运行的 `processed_through` 时间戳
2. 查询 `SessionConsolidationRecord` 中 `completed_at > processed_through` 的记录数
3. 达到 10 条时，调度一次 `CrossSessionConsolidationWorker`
4. 此检查在每次 `SESSION_COMPLETED` 处理后触发（piggyback on existing scheduler）

**Startup 补偿**：启动时如距上次 cross-session 运行超过 7 天，且有未处理的 session，自动补运行一次，不等待凑满 10 条。

#### 幂等 key

新建 DB 表 `cross_session_consolidation_records`：

```
run_id            TEXT PRIMARY KEY   -- uuid
processed_through DATETIME           -- 扫描到哪个时间点的 session
session_count     INTEGER            -- 本次处理了多少个 session
completed_at      DATETIME
worker_version    TEXT
```

下次运行从上一次 `processed_through` 往后扫，不重复处理同一批 session。并发安全：`run_id` 唯一约束 + `IntegrityError` 回滚（与 Session Consolidation 相同模式）。

#### 证据合并规则（confidence 提升）

同一 `(slot_id, value)` 在 **N 个不同 session** 的 summaries 或 `inferred` artifacts 中出现，视为多次印证：

| 出现次数 | confidence 提升目标 |
|---------|-------------------|
| 2 个 session | `inferred 0.60 → 0.75` |
| 3 个及以上 session | 上限 `0.85`，不超过 `explicit` 基线 0.95 |

提升方式：生成一条新 `CandidateArtifact`（`source=inferred`，提升后 confidence），走标准 Resolve 路径（SUPERSEDE 旧记录，写 decision log）。

#### 与 explicit 来源的冲突规则

Cross-Session Consolidation **不得覆盖 `source=explicit` 的记忆**：

- 若归纳结论与现有 `explicit` 记录冲突 → 新候选打 `needs_review` tag，进入待审核队列，不执行 SUPERSEDE
- 若无冲突，或现有记录为 `inferred`/`observed` → 正常走 Resolve

这条规则确保用户明确说过的事情不会被模型归纳静默覆盖。

#### Decision Log

每次 Cross-Session Consolidation 的写入、提升、丢弃，全部进入 `memory_decision_log`，`input_source` 标记为：

```python
{"type": "cross_session_consolidation", "run_id": "...", "session_count": N}
```

### 1.3 Summary 替换策略

#### 核心规则：一个 session 最多一条 active summary

Session Consolidation 每次运行只生成一条 summary，key 是 `session_id`（来自 `structured_payload.source_session_ids` 或 `provenance.session_id`）。

Resolver 对 `summary` kind 的处理：

| 场景 | 决策 |
|------|------|
| 相同 content（精确匹配） | `DISCARD`（已有 `find_active_exact` 实现） |
| 相同 `session_id`，content 不同 | `SUPERSEDE`：新 summary 替换旧 summary，旧记录 status → `superseded` |
| 不同 `session_id` | `ADD`：追加，不影响其他 session 的 summary |

**"相同 session_id" 的判断来源**（优先级从高到低）：
1. `structured_payload.source_session_ids` 包含该 session_id
2. `provenance.session_id` 等于该 session_id

#### 历史 summary 保留规则

- `superseded` 状态的旧 summary **保留在 DB**，不物理删除
- 检索路径（`search_summaries_by_query`、`search_summaries`）只查 `status=active`，历史 summary 不参与自动注入
- `memory_search` 工具可通过加 `status` 过滤参数查到历史 summary（审计、回溯用途）

#### Active summary 总量上限

单个 subject 的 active summary 累积上限为 **50 条**。超出时，Maintenance Worker 将最旧（`recorded_at` 最早）且 `access_count=0` 的 summary 状态置为 `expired`，直到降至 50 条以内。

此规则由 Maintenance Worker（§1.4）执行，Session Consolidation 本身不做总量检查。

#### Cross-Session summary（未来）

Cross-Session Consolidation 生成的跨多个 session 的聚合 summary，`source_session_ids` 包含多个 session_id：
- 不触发单 session summary 的 SUPERSEDE 规则
- 作为独立 `ADD` 追加
- `structured_payload.source_session_ids` 长度 > 1 时，Resolver 识别为 cross-session summary

### 1.4 Memory Maintenance（记忆维护）

负责：过期、降权、重复压缩、摘要总量清理、索引修复。

**实现状态**：部分实现。当前已有 EXPIRE 类生命周期动作和 startup catch-up sweep，但还没有独立周期性 Maintenance Worker。规则如下：

**降权规则**：`confidence < 0.3` 且 `access_count = 0` 且距 `recorded_at` 超过 **30 天** → 标记 `needs_review`；再过 30 天仍未访问 → status 置为 `expired`（除非有 `do_not_expire` tag）。

**重复压缩规则**：同一 `(subject_id, slot_id, value)` 存在多条 `active` 记录时（正常流程不应出现，但可能因 bug 产生）→ 保留 confidence 最高且 `recorded_at` 最新的一条，其余置为 `superseded`，写 decision log。

**摘要总量清理**：单个 subject active summary 超过 **50 条**时，将最旧（`recorded_at` 最早）且 `access_count = 0` 的 summary 置为 `expired`，直到降至 50 条。

**触发时机**：启动时执行一次（catch-up），之后每 **24 小时**执行一次（scheduler 驱动）。

### 1.5 Relation 写入规则与 Exclusive 时间边界

`relation_candidates` 是唯一的 relation 存储，无独立 `relation_facts` 表。

#### 写入去重

新 relation artifact 写入前，检查是否已存在相同 `(subject_id, predicate, source_entity_id, target_entity_id)` 且 `status=active` 的记录：

- 完全匹配 → `DISCARD`，写 decision log
- 不匹配 → 继续走 exclusive 检查

#### Exclusive Relation 时间边界

`is_exclusive=True` 的 relation 表示：同一 `(subject_id, predicate)` 下**只能有一条 active 记录**（如"用户当前居住地"、"用户当前主用设备"）。

写入新 exclusive relation 时：

1. 查询 `relation_candidates` 中所有 `subject_id=X, predicate=P, status=active, is_exclusive=True` 的记录
2. 对每条旧记录：将 `valid_until` 设为新记录的 `valid_from`（或当前时间，如新记录无 `valid_from`）；`status` 保持 `active` 不变——`valid_until` 到期后检索层自然过滤
3. 写入新记录，`status=active`
4. 所有操作写 decision log，decision 类型为 `SUPERSEDE`，`old_memory_ids` 列旧记录 ID

**不支持 back-dated relation**：`valid_from` 只允许设为当前时间或未来时间，不允许回填过去时间（避免破坏已有 valid_until 链）。

#### Non-exclusive Relation

`is_exclusive=False`：直接 `ADD`，不影响同 predicate 下其他记录。

#### Relation Lane 过滤条件

Relation Lane 查询 `relation_candidates` 时应用以下过滤（与 `_keep_record` 通用过滤一致）：

```
status = active
confidence >= MIN_CONFIDENCE (0.3)
valid_from <= now  (或为 None)
valid_until > now  (或为 None)
subject_id = context.subject_id
```

---

## 2. Consolidation（后台沉淀）输入

后台沉淀不能只看原始对话，还应综合：

- session 消息
- 本次会话生成的 candidate artifacts
- 当前已有 active facts
- 最近相关 summaries
- 低置信、未决、待确认 artifacts

---

## 3. 为什么要分三类

- Session Consolidation 关注“这一段对话发生了什么”
- Cross-Session Consolidation 关注“用户长期稳定呈现出什么模式”
- Maintenance 关注“系统里的记忆是否仍干净可用”

---

## 4. Decision Log（决策日志）

`memory_decision_log` 从第一阶段就应落数据，即使 UI 暂时不做。

记录内容：

- 原始输入来源
- 候选 artifacts
- 命中的 slot / subject / scope
- 冲突候选列表
- 决策结果：`ADD / SUPERSEDE / MERGE / EXPIRE / DISCARD`
- 决策原因摘要
- 执行该决策的 worker / 模型 / 规则版本
- 关联的旧记录 ID 和新记录 ID
- 时间戳

价值：

- 调试“为什么记错了”
- 回答“为什么旧偏好被新偏好覆盖”
- 做人工审核 UI
- 做模型提示词和规则迭代对比
- 做自动回滚与补偿

---

*← 返回 [Memory 索引](INDEX.md)*
