---
version: "1.0"
last_updated: 2026-04-20
status: in-progress
---

# Memory（记忆）读取与注入

> 模块索引：[INDEX.md](INDEX.md)
> 架构图：[../../diagrams/memory/retrieval.html](../../diagrams/memory/retrieval.html)

---

## 1. 总原则

Sebastian 不做“统一 search top-k 然后塞进 prompt”，而做：

`Intent（意图） -> Retrieval Plan（检索计划） -> Assemble（装配）`

---

## 2. Intent 判定

每轮用户输入先做轻量记忆意图判断，至少识别：

- 是否在问长期偏好
- 是否在追问近期经历
- 是否在问当前状态
- 是否涉及实体关系
- 是否只是普通闲聊，不值得高成本检索

---

## 3. Retrieval Planner（检索规划器）

Planner 输入：

| 字段 | 说明 |
|------|------|
| `user_message` | 当前用户消息 |
| `session_context` | 当前 session 主题、近期消息摘要 |
| `subject_id` | 当前记忆主体（通常为 owner entity id） |
| `active_project_or_agent_context` | 当前激活的项目或 agent 上下文 |
| `reader_agent_type` | 调用方 agent 类型；用于 policy_tags 中 `owner_only` 等访问控制过滤 |
| `reader_session_id` | 调用方 session id；用于 scope=session 的记忆隔离 |
| `access_purpose` | 本次检索目的，枚举值：`auto_inject`（自动注入）/ `explicit_search`（工具显式检索）/ `consolidation`（后台沉淀读取） |

**Agent 层级前置检查**：`_memory_section()` 在构造 Planner 输入之前，必须先确认调用方 depth=1。depth >= 2 的 agent 不进入检索流程，直接返回空记忆注入。详见 [artifact-model.md §10.4](artifact-model.md)。

Planner 输出：

- 应启用哪些检索 lane
- 每条 lane 的预算
- 是否优先当前事实还是历史回忆
- 是否允许深挖原始 episode
- 基于 `policy_tags` 的过滤条件

---

## 4. 四条检索通道（Retrieval Lane）

### 4.1 Profile Lane（画像检索通道）

提供高价值、稳定、当前有效的画像与偏好。

特点：

- 条数小
- 高置信
- 即使不依赖当前 query 也可能注入

### 4.2 Context Lane（上下文检索通道）

提供与当前用户消息强相关的动态事实与状态。

特点：

- 强 query-aware
- 可结合当前 session 主题
- 侧重“当前正在做什么”

### 4.3 Episode Lane（经历检索通道）

提供过去发生过什么、怎么决定的、上次讨论到哪里。

策略：

- 默认先查 `summary`
- 需要细节时再下钻原始 `episode`

### 4.4 Relation Lane（关系检索通道）

提供实体间关系与时间性状态。

首期允许接口存在但数据量较少，后续随着 relation 层成熟逐步增强。

---

## 5. FTS5 中文检索策略

首版如果使用 SQLite FTS5（全文检索），不能直接使用默认 `unicode61` tokenizer（分词器）处理中文原文。

本地验证环境：

- SQLite `3.51.0`
- FTS5 enabled
- jieba `0.42.1`

验证结论：

| 方案 | 结果 | 结论 |
|------|------|------|
| `unicode61` 直接索引中文原文 | `用户` / `偏好` / `中文` 等短词无法命中 | 不适合作为中文主检索方案 |
| `trigram` 三元分词 | 能命中 3 字以上片段，但 `用户` / `偏好` / `小橘` 等 2 字词无法命中 | 召回不稳定，不适合作为主方案 |
| jieba 预分词 + `unicode61` | 测试语料 15/15 命中 | 首版采用 |

首版实现方案：

```text
原文字段: content
索引字段: content_segmented
写入: content -> jieba.cut_for_search(content) -> 空格拼接 -> content_segmented
FTS5: 对 content_segmented 建 unicode61 索引
查询: query -> jieba.cut_for_search(query) -> 逐词 MATCH -> 合并去重排序
```

示例：

```text
content:
用户偏好简洁中文回复

content_segmented:
用户 偏好 简洁 中文 回复
```

查询策略：

- 默认使用 `jieba.cut_for_search()`，比普通 `jieba.cut()` 更适合检索召回
- 默认过滤单字词，降低噪声
- 单字实体或特殊名称不依赖 FTS，优先走 `Entity Registry`（实体注册表）的 entity lookup（实体查找）
- 从 `Entity Registry` 同步项目名、Agent 名、家庭成员名、宠物名等到 jieba 用户词典，提升实体分词稳定性

---

## 6. Assembler（上下文装配器）

最终注入不做平铺列表，而按语义分区装配：

- `What I know about the user`
- `Relevant current context`
- `Relevant past episodes`
- `Important relationships`

Assembler 不允许把不同来源的记忆压成无类型自然语言摘要。自动注入内容必须保留语义分区和 memory kind（记忆类型）标识，让 Agent 能区分：

- `preference`：用户偏好，通常比普通事实有更高注入优先级
- `fact`：当前有效事实或状态
- `episode` / `summary`：历史经历与历史证据
- `relation`：实体关系及其时间性状态

例如 Profile Lane 中的条目应显式保留 `[preference]` / `[fact]` 标记；Episode Lane 中的条目应显式保留 `[episode]` / `[summary]` 标记。这样可以避免 Agent 把“历史上发生过的事”误当成“当前偏好”，也避免 profile、preference、episode 和 relation 在 prompt 中混成同一种记忆。

Assembler 在最终注入前，必须统一执行以下过滤：

- `status`
- `valid_from / valid_until`
- `scope / subject_id`
- `policy_tags`
- `confidence threshold`
- `reader_agent_type / access_purpose`

---

## 7. Retrieval Budget（检索预算）

### 7.1 预算单位：条数，非 token 数

当前实现以**条数（items）**为预算单位，不做 token 计数。每条 lane 独立上限，不共享抢占——否则 episode 会抢光 profile 名额，或 relation 饿死 context lane。

### 7.2 默认 per-lane limit（`RetrievalPlan` 默认值）

| Lane | 默认条数上限 | 代码常量位置 |
|------|------------|-------------|
| Profile Lane | **5** | `RetrievalPlan.profile_limit = 5` |
| Context Lane | **3** | `RetrievalPlan.context_limit = 3` |
| Episode Lane | **3** | `RetrievalPlan.episode_limit = 3`（summary 优先，不足时补 detail） |
| Relation Lane | **3** | `RetrievalPlan.relation_limit = 3` |

修改默认值只需改 `RetrievalPlan` 字段默认值，无需改 planner 或 assembler 逻辑。

### 7.3 最小置信度过滤线

`MIN_CONFIDENCE = 0.3`：低于此值的记录在 Assembler 过滤阶段丢弃，不计入 lane 条数配额。

此值与 confidence spec（artifact-model.md §9.3）中的"不自动注入阈值 0.5"不同——`MIN_CONFIDENCE` 是**绝对过滤线**（低于它的记录连候选都不是），0.5 是**注入优先级线**（低于 0.5 但高于 0.3 的记录不自动注入，但 `memory_search` 仍可返回）。

> **当前实现状态**：`memory_search` 工具路径使用 `MIN_CONFIDENCE = 0.3` 作为过滤线，与自动注入路径一致。如需让 `memory_search` 返回更低置信度的候选，应在工具层单独传入 `min_confidence` 参数，不修改全局常量。

### 7.4 `pinned` tag 的 budget 豁免

标有 `pinned` 的记录不受 per-lane limit 剪裁，强制进入注入结果。

**实现状态**：`pinned` 豁免逻辑当前尚未在 `MemorySectionAssembler` 中实现，为待补功能。实现时应在 assembler 中先单独收集 `pinned` 记录，再对剩余记录应用 limit，最后合并输出；`pinned` 总数上限为 10 条，超出时按 confidence 降序截断（见 artifact-model.md §10.1）。

### 7.5 `memory_search` 工具的 effective limit

`memory_search(query, limit)` 是显式工具检索入口，和自动注入路径共享 Retrieval Planner 与 lane 语义，但 `limit` 是工具调用方请求的总结果目标值，不应直接覆盖每条 lane 的独立预算。

工具路径采用 lane-aware budget（按通道分配预算）：

- 先根据 Retrieval Planner 得到已激活 lane。
- `requested_limit = max(1, limit)`。
- `effective_limit = max(requested_limit, active_lane_count)`。
- 当 `requested_limit < active_lane_count` 时，提高 effective limit，确保每条已激活 lane 至少有 1 个候选名额。
- 当 `requested_limit >= active_lane_count` 时，在不超过 `effective_limit` 的前提下，按 lane 顺序分配余数；较早 lane 拿到额外预算。
- 不允许先拼接所有 lane 再做全局截断，因为这会让 Profile Lane 等高召回通道饿死 Episode / Context / Relation Lane。

因此 `memory_search` 的 `limit` 是“请求的目标总数”，实际返回上限是 `effective_limit`。这个规则只适用于显式工具检索；自动注入路径仍由 `MemorySectionAssembler` 对各 lane 独立应用 `plan.xxx_limit`。

---

## 8. 当前真值与历史证据分离

注入语义必须区分：

- `current truth`（当前真值）
  - 仅来自 `active` 且在时间上有效的事实和关系
- `historical evidence`（历史证据）
  - 来自 episode、旧事实、旧关系和摘要

---

*← 返回 [Memory 索引](INDEX.md)*
