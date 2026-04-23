---
version: "1.2"
last_updated: 2026-04-23
status: in-progress
---

# Memory（记忆）系统 Spec 索引

> 上级索引：[../INDEX.md](../INDEX.md)
> 架构图入口：[../../diagrams/memory/index.html](../../diagrams/memory/index.html)

Sebastian 记忆系统采用“**三层逻辑模型 + 两套首期主存储 + 关系层预留**”的设计：

- `ProfileMemory`（画像记忆）：用户画像、偏好、长期事实、当前状态
- `EpisodicMemory`（情景/经历记忆）：事件、经历、任务过程、会话回忆、阶段摘要
- `RelationalMemory`（关系记忆）：实体、关系、时间区间、多实体语义连接

首版只依赖 **数据库 + LLM（大语言模型）**，不引入向量数据库或 embedding（向量嵌入）作为前置依赖。

---

## 当前实施状态

截至 2026-04-21，Memory 系统已完成 Phase A / B 的主体实现，并完成 Phase C / D 与 Dynamic Slot / Retrieval Fixes 的部分能力：

| Phase | 当前状态 | 说明 |
|-------|----------|------|
| A 协议先行 | 已实现 | `MemoryArtifact`、Slot Registry、Resolver、Retrieval Plan、Assembler、Decision Log 主协议已落地；slot 定义已支持 DB 持久化与运行时动态注册 |
| B Profile + Episode 可用版 | 已实现，持续修正中 | Profile / Episode 存储、写入、检索、注入与基础工具已可用；retrieval depth guard、confidence 双阈值与 planner 词库升级已落地 |
| C Consolidation 成熟版 | 部分实现 | Session Consolidation、startup catch-up sweep、EXPIRE 类生命周期处理与 proposed_slots 流程已实现；Cross-Session Consolidation、周期性 Maintenance、降权、重复压缩、索引修复仍需单独 spec |
| D Relation / Graph 增强 | 部分实现 | Entity Registry、`relation_candidates`、Relation Lane 与实体名动态触发词缓存已实现；exclusive relation 时间边界、正式 relation facts / graph 查询语义仍需单独 spec |

已明确短期不做的设计拆分：

- 不为 Memory 单独扩展 LLM provider temperature 接口；Extractor / Consolidator 暂用 provider 默认参数，后续基于真实效果再决定是否改 provider 抽象。
- 不拆分 BaseAgent 的 memory planner / assembler hook；`_memory_section()` 是 BaseAgent 内唯一长期记忆注入入口，内部完成 plan → fetch → assemble。
- 不把 turn end / idle 当作 BaseAgent 内部 consolidation hook；当前由 `SESSION_COMPLETED` 事件和启动 catch-up sweep 驱动，会话 idle / stalled 触发需要另开 spec 讨论。

## 阅读顺序

| 顺序 | Spec | 重点 |
|------|------|------|
| 1 | [overview.md](overview.md) | 总体目标、逻辑/物理架构、与现有系统集成、分阶段落地 |
| 2 | [artifact-model.md](artifact-model.md) | MemoryArtifact（记忆产物）、Slot Registry（语义槽位注册表）、动态 ProposedSlot、生命周期、冲突决策 |
| 3 | [storage.md](storage.md) | Profile（画像）/ Episode（经历）/ Entity（实体）/ Relation（关系）/ Slot Definition / Decision Log（决策日志）存储边界 |
| 4 | [write-pipeline.md](write-pipeline.md) | Capture → Extract → Normalize → Resolve → Persist 统一写入链路、动态 slot 注册、同步 `memory_save` 契约 |
| 5 | [retrieval.md](retrieval.md) | Intent（意图）→ Retrieval Plan（检索计划）→ Assemble（装配），四条 retrieval lane、depth guard、confidence 双阈值 |
| 6 | [consolidation.md](consolidation.md) | Session（会话）/ Cross-Session（跨会话）/ Maintenance（维护）三类后台沉淀与审计 |
| 7 | [implementation.md](implementation.md) | DB（数据库）+ LLM 技术取舍、provider binding（模型绑定）与 REST 路由、Extractor / Consolidator schema、ProposedSlot 重试协议、记忆功能设置持久化、Extractor 置信度评分规则 |

---

## 常用术语

| 术语 | 中文 | 说明 |
|------|------|------|
| Memory | 记忆 | Sebastian 长期可复用的信息体系 |
| Artifact | 记忆产物 | 从输入中提炼出的标准化记忆对象 |
| CandidateArtifact | 候选记忆产物 | LLM 提取出的候选对象，尚未最终写库 |
| Slot | 语义槽位 | 用于判断事实是否冲突的稳定归属，如 `user.preference.response_style` |
| Scope | 作用域 | 记忆归属范围，如 user、session、project、agent |
| Subject | 主体 | 记忆属于谁，如 owner、某个 project、某个 agent |
| Provenance | 来源证据 | 记忆从哪里来、证据是什么 |
| Policy Tags | 策略标签 | 控制敏感性、权限、是否自动注入等策略 |
| Retrieval | 检索 | 回答前从记忆中取相关内容 |
| Lane | 检索通道 | Profile / Context / Episode / Relation 四类并行检索路径 |
| Assembler | 上下文装配器 | 把检索结果过滤、分区并注入 prompt |
| Consolidation | 后台沉淀 | 会话结束后或跨会话归纳记忆 |
| Decision Log | 决策日志 | 记录每次写入、覆盖、合并、丢弃的原因 |

---

## 关键设计约束

- 所有写入路径统一产出 `MemoryArtifact`（记忆产物）或 `CandidateArtifact`（候选记忆产物）
- 所有冲突判断基于 `slot_id`（语义槽位）+ `cardinality`（单值/多值）+ `resolution_policy`（冲突解决策略），不基于纯文本相似度
- 所有自动注入都必须区分 `current truth` 与 `historical evidence`
- 所有重要写入、覆盖、合并、过期、丢弃决策都必须进入 `memory_decision_log`（记忆决策日志）
- LLM（大语言模型）只负责语义提炼和归纳，不直接控制数据库状态迁移

---

*← 返回 [Spec 根索引](../INDEX.md)*
