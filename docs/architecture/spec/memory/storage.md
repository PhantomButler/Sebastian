---
version: "1.0"
last_updated: 2026-04-19
status: planned
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
- `memory_decision_log`（记忆决策日志）

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

与现有 `sebastian/memory/episodic_memory.py` 的关系：

- 现有 `EpisodicMemory` 实际是 session history compatibility layer（会话历史兼容层）
- 它负责当前 session 消息读写，不负责跨 session 回忆、summary（摘要）或 episode artifact（经历记忆产物）
- 新的 `Episode Store` 应新增实现，不应直接替换现有类，以免影响 BaseAgent 的主对话上下文链路

建议拆成两类逻辑对象：

- 原始 episode
- 派生 summary

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

首期建议物化方式：

- `relation_candidates`（关系候选表）
  - 保存抽取得到但尚未进入主关系索引的 relation artifacts
- `relation_facts`（确认关系表）
  - 保存已确认、可供当前读取链路使用的轻量关系记录

如果首期不启用 `relation_facts` 做主注入，至少也要把 relation artifacts 持久化到 `relation_candidates` 和 `memory_decision_log`。

---

## 6. Decision Log（决策日志）

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

## 7. 首期检索能力来源

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
