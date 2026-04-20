---
version: "1.0"
last_updated: 2026-04-19
status: planned
---

# Memory Artifact（记忆产物）与冲突模型

> 模块索引：[INDEX.md](INDEX.md)

---

## 1. 核心原则

Sebastian 不直接把原始输入写入某个固定 memory 表，而是先把输入转成标准化 `MemoryArtifact`，再由路由层分发到不同记忆后端。

`artifact`（记忆产物）是统一逻辑协议，不等于数据库表。

---

## 2. Artifact 类型

| 类型 | 说明 |
|------|------|
| `fact`（事实） | 可被后续事实覆盖、失效或并存的结构化陈述 |
| `preference`（偏好） | 用户偏好；本质属于 fact，但注入优先级和更新策略特殊 |
| `episode`（经历） | 实际发生过的事件、对话、任务、决策或经历 |
| `summary`（摘要） | 对一个或一组 episode 的压缩表述 |
| `entity`（实体） | 需要长期识别和跟踪的对象 |
| `relation`（关系） | 实体之间的语义关系，可带时间区间和排他规则 |

---

## 3. MemoryArtifact 字段

```python
class MemoryArtifact(TypedDict):
    id: str
    kind: Literal["fact", "preference", "episode", "summary", "entity", "relation"]
    scope: str
    subject_id: str
    slot_id: str | None
    cardinality: Literal["single", "multi"] | None
    resolution_policy: Literal["supersede", "merge", "append_only", "time_bound"] | None
    content: str
    structured_payload: dict[str, Any]
    source: Literal["explicit", "inferred", "observed", "imported", "system_derived"]
    confidence: float
    status: Literal["active", "superseded", "expired", "deleted"]
    valid_from: datetime | None
    valid_until: datetime | None
    recorded_at: datetime
    last_accessed_at: datetime | None
    access_count: int
    provenance: dict[str, Any]
    links: list[str]
    embedding_ref: str | None
    dedupe_key: str | None
    policy_tags: list[str]
```

首期不实现 embedding 时，`embedding_ref` 保留为空即可。

---

## 4. 必须从 Day 1 保留的语义

- `scope`（作用域）
  - 限定记忆归属范围，例如 `user` / `session` / `project` / `agent`
- `subject_id`（主体 ID）
  - 限定记忆主体，防止未来多用户、多项目、多 agent 情况下串数据
- `slot_id`（语义槽位）+ `cardinality`（单值/多值）+ `resolution_policy`（冲突解决策略）
  - 让冲突消解成为显式协议，而不是在 resolver 中临时猜测
- `source`（来源）+ `confidence`（置信度）+ `provenance`（来源证据）
  - 用于冲突判断、审计回溯和后续人工核查
- `status`（状态）+ `valid_from`（生效时间）+ `valid_until`（失效时间）
  - 表达动态状态，避免未来为“当前值”和“历史值”做破坏性迁移
- `structured_payload`（结构化载荷）
  - 让记忆不仅是可读文本，也能被程序化处理
- `links`（关联）
  - 作为关系层和摘要层的桥接字段

---

## 5. Slot Registry（语义槽位注册表）

`slot_id`（语义槽位 ID）不应是自由文本，而应关联到稳定的 slot registry（语义槽位注册表）。

registry 至少维护：

- `slot_id`
- `scope`
- `subject_kind`
- `cardinality`
- `resolution_policy`
- `kind_constraints`
- `description`

规则：

- `fact` / `preference` 默认必须带 `slot_id`
- `relation` 默认必须带稳定的关系谓词标识
- `episode` / `summary` 可为空，因为它们通常不是槽位覆盖模型
- 如果上游只能产出模糊候选，必须在 Normalize 阶段显式落成 `slot_id` 或标记为“未归槽”

---

## 6. 生命周期模型

| 状态 | 说明 |
|------|------|
| `active`（有效） | 当前有效，可参与检索与自动注入 |
| `superseded`（被取代） | 被更新事实取代，但保留历史 |
| `expired`（已过期） | 因时间条件自然失效 |
| `deleted`（已删除） | 被用户或系统显式删除，不再参与正常召回 |

记忆不是 KV 配置项。事实更新默认应保留历史轨迹，而不是直接覆盖旧行。

---

## 7. 冲突决策流程

每条新 artifact 统一走三段式：

1. `Resolve`（解析冲突）
   - 在同 subject、同 scope、同 slot 下找候选冲突对象
2. `Decide`（做出决策）
   - 只允许输出 `ADD / SUPERSEDE / MERGE / EXPIRE / DISCARD`
3. `Apply`（应用决策）
   - 按决策落库、写日志、更新索引

文本相似度最多只能用于召回候选，不允许直接决定覆盖关系。

---

## 8. structured_payload Schema（各 kind 结构化载荷）

`structured_payload: dict[str, Any]` 在每种 kind 下有固定 schema，Normalize 阶段校验。`content` 保留人类可读的自然语言描述，`structured_payload` 提供程序可消费的结构化字段。

### 8.1 `fact`

```python
{
    "attribute": str,                              # 属性名，e.g. "current_city", "job_title"
    "value": str | int | float | bool | list[str], # 当前值（扁平，不允许嵌套 dict）
    "unit": str | None,                            # 单位或类别描述，e.g. "city", "language"
    "previous_value": str | None,                  # SUPERSEDE 时记录旧值；ADD 时为 None
}
```

`value` 保持扁平类型，复杂结构用 `content` 自然语言描述，或建模为 `entity` + `relation`。

### 8.2 `preference`

```python
{
    "dimension": str,   # 偏好维度，e.g. "response_style", "reply_language", "food"
    "value": str,       # 偏好值，e.g. "concise", "Chinese", "西瓜"
    "context": str | None,  # 适用场景限定，e.g. "when coding"；无限定时为 None
}
```

偏好条目默认多值并存（同一 `dimension` 下"喜欢西瓜"和"喜欢芒果"共存），不做相互排序。相对强弱（"我更喜欢苹果"）由 `content` 字段直接携带，不另设 `strength` 字段；`confidence` 反映的是这条记忆的可信度（是用户直接说的还是模型推断的），与偏好强弱无关。

### 8.3 `episode`

```python
{
    "session_id": str,
    "task_id": str | None,
    "topic": str,                        # 一行概括这个经历是关于什么
    "outcome": str | None,               # 决策结果或任务结论
    "participant_entity_ids": list[str], # 涉及的实体 entity ID 列表
}
```

### 8.4 `summary`

```python
{
    "source_session_ids": list[str],
    "source_episode_ids": list[str],
    "time_range_from": str | None,  # ISO 8601
    "time_range_to": str | None,
    "topics": list[str],
    "key_decisions": list[str],
}
```

### 8.5 `entity`

```python
{
    "entity_type": str,           # 自由字符串；建议值：person / project / organization /
                                  # place / tool / concept / pet，但不做枚举硬约束
    "canonical_name": str,        # 规范化名称，用于去重和 lookup
    "aliases": list[str],         # 别名列表
    "attributes": dict[str, Any], # 类型相关的自由属性，e.g. {"role": "owner's cat"}
}
```

`entity` 是世界中可被引用的命名对象（关系图的节点），和 `fact` 的区别：`fact` 存储某主体的标量属性（bound to slot，有 cardinality / conflict resolution）；`entity` 是独立的命名实体，可被 `relation` 链接，可通过别名 lookup，可注入 jieba 词典。`entity_type` 不做枚举硬约束，以便无需改代码即可新增类型。

### 8.6 `relation`

```python
{
    "subject_entity_id": str,      # 主体实体 ID
    "predicate": str,              # 关系谓词，e.g. "works_on", "lives_in", "owns", "member_of"
    "object_entity_id": str,       # 客体实体 ID
    "is_exclusive": bool,          # 同一 (subject, predicate) 下是否排他
    "attributes": dict[str, Any],  # 关系附加属性，e.g. {"role": "lead", "since": "2024-01"}
}
```

---

## 9. 默认策略

| Artifact | 默认规则 |
|----------|----------|
| `preference` | 单槽位、单活跃记录、默认 `SUPERSEDE` |
| `fact(single)` | 单槽位、单活跃记录、默认 `SUPERSEDE` |
| `fact(multi)` | 多值并存，去重后 `ADD` 或 `MERGE` |
| `episode` | append-only，仅做精确去重 |
| `summary` | 可替代默认摘要，但保留历史摘要 |
| `relation(exclusive)` | 时间边界覆盖，旧关系写 `valid_until` |
| `relation(non_exclusive)` | 并存 |

---

## 9. Confidence（置信度）

### 9.1 量纲

`confidence: float`，取值 `[0.0, 1.0]`，已在 `CandidateArtifact` 和 `MemoryArtifact` 上以 `Field(ge=0.0, le=1.0)` 约束。

`confidence` 表示这条记忆**本身的可信程度**（epistemic certainty）：它是否真实、是用户直接说的还是模型推断的。它**不表示**偏好强弱、重要程度或注入优先级（这些由 lane 排序和 `policy_tags` 控制）。

### 9.2 按 source 的初始值基线

| source | 初始 confidence | 说明 |
|--------|----------------|------|
| `explicit` | **0.95** | 用户直接说的；预留 0.05 降权空间，覆盖随口一说或反话的情况 |
| `system_derived` | **0.90** | 系统规则确定生成，如时区、session_id 等 |
| `imported` | **0.80** | 外部导入，来源质量未经验证 |
| `observed` | **0.65** | 行为观察，存在噪声 |
| `inferred`（单次） | **0.60** | 单次会话 LLM 推断 |
| `inferred`（多次印证） | **0.75** | Cross-Session Consolidation 强化后提升至此 |

以上为基线，Extractor / Consolidator 可在基线附近微调，但不得超出对应 source 的合理范围。

### 9.3 阈值规则

| 阈值 | 行为 |
|------|------|
| `>= 0.5` | 可自动注入（默认 Assembler 过滤线） |
| `< 0.5` | 不自动注入；仍可被 `memory_search` 工具显式检索 |
| `< 0.3` | Maintenance worker 降权候选：在满足"`access_count = 0` 且超过 N 天未访问"时，标记为 `needs_review` 或进入过期流程 |

### 9.4 可信度优先级（冲突决策）

1. `explicit` 高于 `inferred`
2. 新的明确表达高于旧的明确表达
3. 高置信度高于低置信度
4. 更具体的结构化陈述高于模糊概括

---

## 10. Policy Tags（策略标签）

`policy_tags: list[str]` 是 MemoryArtifact 上的策略控制字段，每个元素必须是以下枚举值之一。

### 10.1 合法值与语义

| Tag | 类别 | 语义 |
|-----|------|------|
| `pinned` | 注入控制 | 强制进入每次 system prompt，不受 lane budget 剪裁。上限 10 条；超出时按 confidence 降序截断，被截掉的降为普通 Profile Lane 候选。 |
| `do_not_auto_inject` | 注入控制 | 禁止自动注入路径（`_memory_section()`），仅 `memory_search` 工具显式检索可返回。 |
| `sensitive` | 访问控制 | 敏感信息；读写均额外写入审计日志。数据脱敏能力纳入未来专项 spec，当前阶段不做技术硬拦截。 |
| `owner_only` | 访问控制 | 仅 owner 身份可访问。首期单用户场景下为标注性字段，不产生实际过滤效果；多用户阶段（访客 / 家人以 depth=1 身份接入时）将正式启用过滤。 |
| `needs_review` | 生命周期 | 待人工核查，Assembler 不自动注入，仅记忆管理 UI 可见。 |
| `do_not_expire` | 生命周期 | Maintenance worker 不得自动过期或降权此条记忆（适用于用户明确要求"永远记住"的场景）。 |

不在上表中的任何字符串，在 Normalize 阶段报错并丢弃，同时在 decision log 中记录 `invalid_policy_tag` 警告。

### 10.2 各角色的设置权限

| Tag | LLM Extractor 可提议 | System 代码可设置 | 用户（未来 UI）可设置 |
|-----|:-------------------:|:-----------------:|:--------------------:|
| `pinned` | 否 | 否 | 是 |
| `do_not_auto_inject` | 否 | 是 | 是 |
| `sensitive` | 是（提议） | 是 | 是 |
| `owner_only` | 否 | 是 | 是 |
| `needs_review` | 是（提议） | 是 | 是（可清除） |
| `do_not_expire` | 否 | 否 | 是 |

"LLM 提议"的含义：tag 进入 `CandidateArtifact.policy_tags`，Normalize 阶段校验后保留。其余 tag 若出现在 Extractor 输出中，Normalize 直接丢弃并写 decision log 警告。

### 10.3 Assembler 过滤规则（按顺序执行）

1. 有 `needs_review` → **跳过**，不注入
2. 有 `do_not_auto_inject` → **跳过**自动注入路径（`memory_search` 工具仍可返回）
3. 有 `sensitive` 且 reader 不具备审计权限 → **跳过**（首期单用户下不触发）
4. 有 `owner_only` 且 reader 不是 owner 身份 → **跳过**（首期不触发，多用户阶段生效）
5. 有 `pinned` → **豁免** lane budget 剪裁，但仍受 `status` / `valid_from` / `valid_until` 过滤；`pinned` 条目总数超过 10 时，按 confidence 降序保留前 10 条

### 10.4 Agent 层级访问边界

长期记忆注入（`_memory_section()`）**只对 depth=1 的 Sebastian 本体开放**。

- depth >= 2 的 agent（组长、组员）不调用 `_memory_section()`，系统 prompt 中不注入长期记忆
- `memory_search` 工具的显式检索路径同样不向 depth >= 2 的 agent 暴露
- 规则记录于此处，不在 BaseAgent 主链路中逐层判断；由 agent 注册 / tool 白名单机制在源头隔离

此边界是首期设计决策，而非临时限制。如未来有明确场景需要组长读取特定记忆，应单独补 spec 并走权限评审，不得直接修改 depth 判断阈值。

---

*← 返回 [Memory 索引](INDEX.md)*
