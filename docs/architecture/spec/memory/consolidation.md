---
version: "1.0"
last_updated: 2026-04-19
status: partially-implemented
---

# Memory（记忆）后台沉淀与审计

> 模块索引：[INDEX.md](INDEX.md)
> 架构图：[../../diagrams/memory/consolidation.html](../../diagrams/memory/consolidation.html)

---

## 1. Consolidation（后台沉淀）不是单一 Worker（后台任务）

后台沉淀至少分三类职责：

### 1.1 Session Consolidation（会话沉淀）

针对单次 session 在 `idle` / `stalled` / `completed` 后做：

- 生成阶段摘要
- 提取候选事实、偏好、关系
- 产生新的 artifacts

**Phase C 实现状态**：`SessionConsolidationWorker`（`sebastian/memory/consolidation.py`）已实现，由 `MemoryConsolidationScheduler` 订阅 `SESSION_COMPLETED` 事件触发。幂等性通过 `SessionConsolidationRecord(session_id, agent_type)` DB 标记保证；写入原子性通过单事务实现。

### 1.2 Cross-Session Consolidation（跨会话沉淀）

针对多个 session 做：

- 偏好强化
- 模式归纳
- 长期主题聚合
- 多来源证据合并

### 1.3 Memory Maintenance（记忆维护）

负责：

- 过期
- 降权
- 重复压缩
- 摘要替换
- 索引修复

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
