---
version: "1.2"
last_updated: 2026-05-03
status: in-progress
---

# Memory（记忆）存储架构

> 模块索引：[INDEX.md](INDEX.md)

---

## 1. 存储边界

首期采用数据库为主，不引入向量数据库或 embedding（向量嵌入）前置依赖。

长期记忆物理层分为：

- `Profile Store`（画像存储）
- `Episode Store`（经历存储）
- `Entity Registry`（实体注册表）
- `Relation Layer`（关系层）
- `memory_slots`（slot 定义存储）
- `memory_decision_log`（记忆决策日志）

当前 store 实现统一位于 `sebastian/memory/stores/`：

| Store | 路径 | 说明 |
|-------|------|------|
| `ProfileMemoryStore` | `stores/profile_store.py` | 画像 CRUD、search_active、supersede |
| `EpisodeMemoryStore` | `stores/episode_store.py` | episode / summary 写入、FTS 检索、summary-first 检索 |
| `EntityRegistry` | `stores/entity_registry.py` | entity CRUD、alias lookup、planner trigger reload |
| `SlotDefinitionStore` | `stores/slot_definition_store.py` | `memory_slots` DB CRUD |

`stores/` 只负责 DB record 读写，不依赖 `services/`、`consolidation/` 或 gateway state。

---

## 2. Profile Store（画像存储）

职责：

- 存储 `fact` / `preference`
- 按 `subject_id + slot_id` 做更新和冲突消解
- 支持当前有效事实检索
- 支持历史状态回溯

建议包含的最小逻辑字段：

- `slot_id`
- `cardinality`
- `content`
- `structured_payload`
- `source`
- `confidence`
- `status`
- `valid_from`
- `valid_until`
- `provenance`
- `policy_tags`

---

## 3. Episode Store（经历存储）

职责：

- 存储 `episode`
- 存储 `summary`
- 维护最近回忆、阶段摘要、决策历史
- 为 query-aware 检索提供全文、时间和主题索引

与 session history 的关系：

- 当前 session 消息读写由 `SessionStore` 负责，不经过 Memory 模块
- `SessionStore` 支撑 BaseAgent 对话上下文、cancel partial flush 和 assistant blocks 持久化
- `EpisodeMemoryStore` 是在 session history 之上建立的可检索回忆层，不替代主对话上下文链路

建议拆成两类逻辑对象：

- 原始 episode
- 派生 summary

### Episode 边界定义

**一个 session 最多对应一个 episode artifact**，session_id 是唯一 key（与 summary 对齐）。

| 规则 | 说明 |
|------|------|
| 粒度 | session 级，不按 task 拆分 |
| 内容 | Consolidator 对"这段对话发生了什么"的提炼；必须有 `topic`，`outcome` 为空表示无明确结论 |
| 空会话 | 消息数 < 2 或无实质交流的 session 不生成 episode |
| 去重 key | `(subject_id, session_id)`：同一 session 已有 episode → SUPERSEDE（同 summary 替换规则） |
| task 细节 | session 内多个 task 的细节通过 `structured_payload.task_id` 和 `outcome` 在同一条 episode 里表达，不拆多条 |

---

## 4. Entity Registry（实体注册表）

职责：

- 稳定分配实体标识
- 维护实体别名、规范化名称、类型
- 为 relation 层和跨 session 主题聚合提供基础

首期最低要求：

- `entities` 或等价 registry 表
- 别名到规范实体 ID 的映射
- entity artifact 的持久化入口
- 可供 Retrieval Planner 做实体命中和 query expansion 的 lookup

---

## 5. Relation Layer（关系层）

职责：

- 表达实体关系及其时间区间
- 支持未来的多实体查询、责任归属、项目关联和家庭成员关系

首期要求：

- 有 artifact 协议
- 有写入挂点
- 有检索接口
- 有首期可落盘的候选层，不允许直接丢弃 relation artifacts

首期不要求：

- 图数据库依赖
- 多跳图遍历作为主检索路径

物化方式（已定型，不再引入 relation_facts 表）：

- **`relation_candidates`** 是唯一的 relation 存储表，同时承担候选层和事实层的职责
  - 写入时所有 relation artifacts 进入此表
  - 检索时以 `confidence >= 0.5 + status=active + valid_from/valid_until` 过滤作为"可用 relation"标准
  - 不再新建独立的 `relation_facts` 表——两张表内容高度重合，区别仅是"审查状态"，增加复杂度而无实质收益

relation 写入和检索规则详见 [consolidation.md §1.5](consolidation.md)（Exclusive Relation 时间边界）及本文 §5.1（字段扩展）。

### 5.1 relation_candidates 待补字段

当前 `RelationCandidateRecord` 缺少 `is_exclusive` 字段，需迁移补加：

```sql
ALTER TABLE relation_candidates ADD COLUMN is_exclusive INTEGER NOT NULL DEFAULT 0;
```

Python 侧对应 `Mapped[bool]`，默认 `False`。写入时由 `structured_payload.is_exclusive` 填充。

---

## 6. Slot Definition Store（Slot 定义存储）

`memory_slots` 表保存所有可用 slot 定义，包含 builtin seed 与 LLM proposed 两类来源。它是 `SlotRegistry` 的持久化来源，gateway 启动时先 seed builtin，再 bootstrap 到进程内 registry。

最小字段：

- `slot_id`：主键，三段式 `{scope}.{category}.{attribute}`
- `scope`
- `subject_kind`
- `cardinality`
- `resolution_policy`
- `kind_constraints`
- `description`
- `is_builtin`
- `proposed_by`
- `proposed_in_session`
- `created_at`
- `updated_at`

`SlotDefinitionStore` 只负责 CRUD；命名规则、字段组合校验、并发 race 处理由 `SlotProposalHandler` 负责。

---

## 7. Decision Log（决策日志）

`memory_decision_log`（记忆决策日志）从第一阶段就应落数据，即使 UI 暂时不做。

每次写入或维护动作至少记录：

- 原始输入来源
- 候选 artifacts
- 命中的 slot / subject / scope
- 冲突候选列表
- 决策结果：`ADD / SUPERSEDE / MERGE / EXPIRE / DISCARD`
- 决策原因摘要
- 执行该决策的 worker / 模型 / 规则版本
- 关联的旧记录 ID 和新记录 ID
- 时间戳

---

## 8. 首期检索能力来源

不使用 embedding 时，首版检索主要依赖：

- 结构化查询
- 全文检索：SQLite FTS5 + jieba 预分词 + `unicode61`
- 时间排序
- entity 命中
- 当前 session / 项目上下文
- summary 优先、episode 下钻

FTS5 中文检索约束：

- 不直接用 `unicode61` 索引中文原文，因为连续中文会被当成大 token，短词召回失败
- 不用 `trigram` 作为主方案，因为 2 字中文词无法命中
- 对需要全文检索的文本同时保存 `content` 和 `content_segmented`
- `content_segmented` 由 `jieba.cut_for_search()` 生成，并作为 FTS5 索引字段
- 单字实体优先走 `Entity Registry`，不依赖 FTS 单字匹配
- FTS5 virtual table（虚拟表）不由 SQLAlchemy `Base.metadata.create_all()` 创建，必须在 gateway startup（启动流程）中于 `init_db()` 之后显式调用初始化 helper

---

*← 返回 [Memory 索引](INDEX.md)*
