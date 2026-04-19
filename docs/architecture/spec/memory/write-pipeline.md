---
version: "1.0"
last_updated: 2026-04-19
status: planned
---

# Memory（记忆）写入流水线

> 模块索引：[INDEX.md](INDEX.md)
> 架构图：[../../diagrams/memory/write-pipeline.html](../../diagrams/memory/write-pipeline.html)

---

## 1. 总原则

所有记忆写入来源都必须走同一条管线：

`Capture（捕获） -> Extract（提取） -> Normalize（规范化） -> Resolve（冲突解析） -> Persist（持久化） -> Index（索引） -> Schedule Consolidation（安排后台沉淀）`

这样可以避免 `memory_save`、session consolidation、tool observation 各自写一套逻辑。

---

## 2. 流水线阶段

| 阶段 | 职责 |
|------|------|
| `Capture`（捕获） | 捕获原始输入与上下文 |
| `Extract`（提取） | 生成候选 artifacts（候选记忆产物） |
| `Normalize`（规范化） | 统一 slot（语义槽位）、scope（作用域）、subject（主体）、时间语义和 payload（载荷） |
| `Resolve`（冲突解析） | 执行冲突判断与决策 |
| `Persist`（持久化） | 路由到 Profile（画像）/ Episode（经历）/ Relation（关系）对应后端 |
| `Index`（索引） | 更新检索索引和辅助 lookup（查找表） |
| `Schedule Consolidation`（安排后台沉淀） | 决定是否触发后台沉淀任务 |

---

## 3. 写入来源分级

Sebastian 至少区分四类写入来源：

| 来源 | 说明 |
|------|------|
| `Explicit Write`（显式写入） | 用户明确要求记住 |
| `Conversational Inference`（对话推断） | 从普通对话中推断 |
| `Behavioral Observation`（行为观察） | 从用户长期行为、工具使用习惯中观察 |
| `Derived Consolidation`（沉淀派生） | 后台从会话或多条记忆归纳而来 |

这四类来源必须在 `source` 和 `provenance` 层面保留差异。

### 3.1 首期实现取舍：不做 per-turn（逐轮）LLM 推断写入

`Conversational Inference`（对话推断）是架构层面的写入来源分类，但首期实现不在每一轮对话结束后立即调用 LLM（大语言模型）提取并写入记忆。

首期边界：

- 即时路径只处理显式 `memory_save` 和规则可确定的高置信写入
- 普通对话里的隐含 fact（事实）/ preference（偏好）先进入会话上下文
- 会话结束后由 `SessionConsolidationWorker`（会话沉淀 Worker）统一提取、去重、冲突解析和持久化

原因：

- 避免在主对话路径增加额外延迟
- 避免每轮都调用 LLM 带来的成本和噪声写入
- 让显式记忆与后台沉淀先稳定，再单独评估实时推断是否值得引入

如果后续需要“用户刚说完就能被下一轮检索到”的强实时能力，应作为独立阶段设计 per-turn inference（逐轮推断）hook（钩子）、debounce（防抖）、置信阈值和撤销/审计策略。

---

## 4. 即时写入与后台沉淀分工

即时写入负责：

- 显式 `memory_save`
- 规则可确定的高置信 `fact` / `preference`
- 原始 `episode`
- 关键 `entity` 注册

后台沉淀负责：

- `summary`
- 跨多轮稳定偏好
- `relation`
- 习惯模式与阶段性结论
- 去重、压缩、置信度提升

---

## 5. Entity / Relation 首期落盘原则

即使 Phase B 尚未让 Relation Lane 成为主检索依赖，`entity` / `relation` artifacts 也不能在 Extract 或 Normalize 之后被直接忽略。

首期必须满足：

- `entity` 至少进入 `Entity Registry`
- `relation` 至少进入 `relation_candidates`
- 相关决策全部进入 `memory_decision_log`

这样后续 Phase D 才能基于已积累的 artifacts 做回填和重建。

---

## 6. LLM 边界

LLM（大语言模型）只负责语义提炼，不负责数据库状态控制。

Extractor（提取器）可以产出 `CandidateArtifact`（候选记忆产物），但最终写入动作必须由 Normalize（规范化）/ Resolve（冲突解析）决定。

---

*← 返回 [Memory 索引](INDEX.md)*
