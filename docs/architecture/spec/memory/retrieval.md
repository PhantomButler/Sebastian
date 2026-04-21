---
version: "1.1"
last_updated: 2026-04-21
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

### 3.1 Planner 当前实现

当前 `MemoryRetrievalPlanner` 位于 `sebastian/memory/retrieval.py`，使用 `jieba.lcut()` 精确分词 + `frozenset` 词库交集判断 lane 激活。静态词库拆到 `sebastian/memory/retrieval_lexicon.py`：

| 词库 | 作用 |
|------|------|
| `PROFILE_LANE_WORDS` | 画像、偏好、身份与推荐/建议类触发词 |
| `CONTEXT_LANE_WORDS` | 当前时间、近期状态、进展询问 |
| `EPISODE_LANE_WORDS` | 历史回忆、上次/之前/说过等触发词 |
| `RELATION_LANE_STATIC_WORDS` | 家庭、工作、社交、宠物等通用实体称谓 |
| `SMALL_TALK_WORDS` | 短问候 / 致谢 / 确认短路词 |

Relation Lane 还维护动态触发词集合：gateway 启动时调用 `DEFAULT_RETRIEVAL_PLANNER.bootstrap_entity_triggers(EntityRegistry(...))`，把 Entity Registry 中所有 `canonical_name` 与 `aliases` 合并进 relation 触发词；`EntityRegistry.upsert_entity()` 在 flush 后通过可选 planner 注入调用 `reload_entity_triggers()`，让新实体下一轮对话即可命中。

> **实现增强**：`bootstrap_entity_triggers()` 同时调用 `segmentation.add_entity_terms()`，把实体名注册到 jieba 用户词典，降低私有实体被拆词导致 relation lane 不触发的概率。

> **Planner 的适用路径**：Planner 的 lane 激活判断**只对 `context_injection` 自动注入路径生效**。`memory_search` 工具作为显式检索入口，**跳过 planner 的意图分类**，始终激活全部四条 lane——调用方已经明确要"尽量查到"，再套一层意图过滤反而会漏召。详见 §7.5。

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

### 4.5 Profile Lane 与 Context Lane 的分工与权衡

Profile Lane 与 Context Lane **物理上共用同一张表**（`profile_memories`），但语义角色和查询方式完全不同。本节解释两者如何配合以及为什么 Profile Lane 不做 query 匹配。

#### 4.5.1 两层独立门控

每个 lane 都经过两层独立判断：

```
第 1 层：Planner 层 —— 这条 lane 要不要激活？
           │
           │  激活
           ▼
第 2 层：Store 层 —— 激活后，按什么规则召回？
```

第 1 层基于用户消息的意图判断（关键词分词 + Entity Registry 合并，见 §3），决定**是否调用** lane 的 Store 方法；第 2 层是各 lane Store 层的具体查询规则，**独立于** Planner。

#### 4.5.2 Profile Lane 与 Context Lane 的职责对比

| 维度 | Profile Lane | Context Lane |
|------|------------|------------|
| 物理存储 | `profile_memories` | `profile_memories`（同一张表） |
| 语义角色 | "这个人长期是什么样"（身份基础认知） | "这个人最近 7 天里和当前话题有关的动态" |
| 时间窗 | 无（所有 active 记录） | `created_at >= now - 7 days` |
| query 相关性 | **不使用 query**——按 confidence + recency 排 | **query-aware**——jieba + FTS 按命中度排 |
| 默认 limit | 5 | 3 |
| FTS 无命中时行为 | N/A（不使用 FTS） | 降级为 confidence + recency（仍限 7 天窗口） |

#### 4.5.3 为什么 Profile Lane 不做 query 匹配

核心原因是 **Profile 记忆的抽象度使字面 FTS 召回率过低**，而这些记忆又是 agent 回答任何问题都需要的"身份基础认知"。

典型场景举例：

| Profile 记忆 | 用户消息 | 字面 FTS 命中？ | 应不应该注入？ |
|---|---|---|---|
| "用户偏好简洁中文回复" | "帮我查今天天气" | ❌ 零交集 | ✅ 应该——agent 回复风格依赖此偏好 |
| "用户对花生过敏" | "推荐个午饭" | ❌ 零交集 | ✅ 应该——推荐食物必须考虑过敏 |
| "用户是 Python 工程师" | "帮我写段代码" | ❌ 字面不命中 | ✅ 应该——代码风格/库选择依赖此 |

如果 Profile Lane 也做 query FTS 匹配，**这些身份类基础认知永远进不来**——它们和任何具体 query 都无字面交集。真正有效的召回需要**语义匹配**（embedding），而当前架构明确不引入 embedding（见 §INDEX "首版只依赖 DB + LLM"）。

现阶段的妥协：放弃检索阶段的语义匹配，直接把高 confidence 的画像**全量**扔进 prompt（limit=5 控制 token），让 LLM 的注意力机制自己决定哪些相关。

Context Lane 不受此约束，因为它的记忆形态是**具体的动态事实**（"最近在做 Q3 季度汇报"/"这周在调 memory 模块"），字面 FTS 命中率天然较高；且其 7 天时间窗本身已经是强筛选，不需要再用 confidence 降低 token 成本。

#### 4.5.4 Planner 激活规则对两者的意义

| Lane | Planner 激活词典含义 |
|---|---|
| Profile | "当前对话是否需要 agent 知道'这个人是谁'"——决定 5 条画像要不要每轮都塞 prompt |
| Context | "当前对话是否涉及'最近在做什么'"——决定要不要查最近 7 天相关事实 |

Profile Lane 激活词（"我/我喜欢/我是/prefer/推荐/觉得"等）不是为了**过滤召回结果**，而是为了**决定是否启动这条 lane**——用户说"hi"时不激活 Profile Lane 以省 token，用户说"我想推荐你一本书"时激活 Profile Lane 让画像进入上下文。

---

### 4.6 未来扩展：引入 Embedding 到 Profile Lane

§4.5.3 指出 Profile Lane 现阶段不做 query 匹配是**被迫妥协**，核心约束是 codebase 不引入 embedding。当数据规模或查询精度需求真正触发瓶颈时，Profile Lane 是全系统**最先受益于 embedding** 的位置。

#### 4.6.1 为什么 Profile Lane 是 embedding 的首选落地点

1. **精度痛点最明确**：Profile 记忆抽象度高（偏好 / 身份 / 长期事实），字面 FTS 匹配率天然接近零；embedding 语义匹配能把"用户对花生过敏"和"推荐午饭" 关联起来，价值立竿见影
2. **规模天然小**：单用户 Profile 记忆总量通常 10~100 条量级，向量化代价和索引开销远低于 Episode（可能上千条）
3. **不影响其他 lane**：Context / Episode / Relation 的字面 FTS 已工作良好，embedding 引入只在 Profile Lane 局部生效，不需要全系统改造
4. **降级路径清晰**：embedding 失败或超时可退化到现有"confidence + recency 全量注入"，无可用性风险

#### 4.6.2 优化空间量化（定性）

| 指标 | 现状 | 引入 embedding 后预期 |
|---|---|---|
| Profile Lane 注入条数 | 每轮必塞 5 条（limit=5） | 按 query 相关度排序，2~3 条即可覆盖主要语义 |
| 每轮 system prompt token 成本 | 固定 Profile 条数成本 | 下降 ~40%（假设精选 3 条替代盲塞 5 条） |
| 相关性 | LLM 注意力自己筛 | Retrieval 阶段预筛，LLM 注意力更聚焦 |
| 冷启动 | 新用户 Profile 记忆 <5 条时 limit 无效 | 仍可用——空召回时降级到全量 |

#### 4.6.3 触发该优化的信号

满足以下任一条件时，应开新 spec 设计 Profile Lane 的 embedding 召回：

- 单用户 Profile 记忆长期稳定超过 20 条，盲塞 limit=5 显著遗漏相关画像
- 用户反馈 agent "明明告诉过它我 XXX，它还是忘了"（语义召回盲区）
- Token 成本分析显示 Profile Lane 占 system prompt 比例过高
- Consolidation 输出的 preference/fact 越来越抽象，字面匹配完全无望

#### 4.6.4 设计约束（提前锁定）

未来实施时必须满足：

1. **不破坏现有 Profile Lane 的语义角色**——embedding 只改"第 2 层 Store 召回"，**不改** Planner 激活规则（§4.5.1 的两层门控结构保持）
2. **embedding provider 抽象独立**——不能硬绑到某个 LLM 厂商或本地模型，保留 provider binding 模式（见 `architecture/spec/memory/implementation.md`）
3. **全量降级路径必保**——embedding 不可用时退化到现有行为
4. **和其他 lane 的 FTS 共存**——不强制替换 Context / Episode 的字面 FTS 检索路径
5. **索引更新策略先明确**：写入侧（Extractor / Consolidator 产出新 Profile artifact）同步生成 embedding，还是异步后台批处理，决定写延迟容忍度

本节作为**设计约束记录**，不构成当前阶段的实施计划。

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

### 7.3 置信度双阈值

当前实现拆为两级常量：

| 常量 | 值 | 作用 |
|------|----|------|
| `MIN_CONFIDENCE_HARD` | `0.3` | 绝对硬过滤线，任何路径低于此值都丢弃 |
| `MIN_CONFIDENCE_AUTO_INJECT` | `0.5` | 自动注入门槛，仅 `access_purpose == "context_injection"` 时额外应用 |

`_keep_record()` 只应用硬过滤线，让 `memory_search` / `tool_search` 路径可以返回 `[0.3, 0.5)` 的弱线索；`MemorySectionAssembler.assemble()` 在 context injection 路径上额外应用 0.5 门槛，避免低置信推断自动进入 system prompt。

> **实现差异**：旧常量 `MIN_CONFIDENCE` 已删除；代码中只保留 `MIN_CONFIDENCE_HARD` 和 `MIN_CONFIDENCE_AUTO_INJECT`。

### 7.4 `pinned` tag 的 budget 豁免

标有 `pinned` 的记录不受 per-lane limit 剪裁，强制进入注入结果。

**实现状态**：`pinned` 豁免逻辑为**独立未来 spec** 范围，当前 Retrieval Fixes spec（[docs/superpowers/specs/2026-04-20-memory-retrieval-fixes-design.md](../../../superpowers/specs/2026-04-20-memory-retrieval-fixes-design.md)）明确**不实现**。任何 pinned 相关代码改动必须等独立 spec 批准；原因与触发条件见该 spec §13.1。

### 7.5 `memory_search` 工具的 effective limit

`memory_search(query, limit)` 是显式工具检索入口。**与自动注入路径的关键差异：memory_search 绕过 `MemoryRetrievalPlanner` 的意图分类，四条 lane（profile / context / episode / relation）强制全部激活。** Planner 的词表路由专为 `context_injection` 路径设计——系统代替用户决定“本轮是否注入哪种记忆”；在工具检索路径上，调用方（用户或 agent）已经明确要查所有相关记忆，再套一层意图过滤会导致漏召。

典型误伤场景：query `"项目 project"` 在词表里只对应 relation lane；若走 planner，画像里 `slot=user.current_project_focus` 的 FACT 永远匹配不到。因此 tool search 必须跳过门控。

`limit` 是工具调用方请求的总结果目标值，不应直接覆盖每条 lane 的独立预算。工具路径采用 lane-aware budget（按通道分配预算）：

- 四条 lane 全部视为已激活（`active_lane_count = 4`）。
- `requested_limit = max(1, limit)`。
- `effective_limit = max(requested_limit, active_lane_count)`。
- 当 `requested_limit < active_lane_count` 时，提高 effective limit，确保每条 lane 至少有 1 个候选名额。
- 当 `requested_limit >= active_lane_count` 时，在不超过 `effective_limit` 的前提下，按 lane 顺序分配余数；较早 lane（profile → context → episode → relation）拿到额外预算。
- 不允许先拼接所有 lane 再做全局截断，因为这会让 Profile Lane 等高召回通道饿死 Episode / Context / Relation Lane。

因此 `memory_search` 的 `limit` 是“请求的目标总数”，实际返回上限是 `effective_limit`。这个规则只适用于显式工具检索；自动注入路径仍由 `MemoryRetrievalPlanner` 决定 lane 激活，由 `MemorySectionAssembler` 对各 lane 独立应用 `plan.xxx_limit`。

---

## 8. 当前真值与历史证据分离

注入语义必须区分：

- `current truth`（当前真值）
  - 仅来自 `active` 且在时间上有效的事实和关系
- `historical evidence`（历史证据）
  - 来自 episode、旧事实、旧关系和摘要

---

*← 返回 [Memory 索引](INDEX.md)*
