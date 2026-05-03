---
version: "1.4"
last_updated: 2026-05-03
status: in-progress
---

# Memory（记忆）实现策略与 LLM（大语言模型）协议

> 模块索引：[INDEX.md](INDEX.md)

---

## 1. 首版技术边界

首版记忆系统明确采用：

- 关系型数据库
- LLM

首版明确不作为前置依赖：

- 独立向量数据库
- embedding（向量嵌入）模型
- hybrid retrieval（混合检索）

原因：

- `ProfileMemory` 的主逻辑依赖 `slot + subject + status + validity`
- `EpisodicMemory` 首版可通过 summary、全文检索、时间排序、entity 命中和当前 session 主题得到足够好的效果
- 当前关键问题是“记忆是否被正确提取、更新和使用”，而不是“语义召回是否做到最强”

---

## 2. 向量能力的设计态度

虽然首版不实现向量能力，但架构上不阻止后续扩展。

后续如果需要增强 episode / summary / relation 的语义召回，可以新增：

- `EmbeddingProvider`（向量嵌入提供器）
- `VectorIndex`（向量索引）

两者都应是增强层，而不是首版主路径依赖。

---

## 3. LLM Provider（模型提供方）策略

记忆系统的模型来源不限定本地部署，可使用云 API，也可使用本地 provider。

引入两个 provider binding 常量（`sebastian/memory/consolidation/provider_bindings.py`）：

- `MEMORY_EXTRACTOR_BINDING = "memory_extractor"`
- `MEMORY_CONSOLIDATOR_BINDING = "memory_consolidator"`

**实现方式**：复用现有 `AgentLLMBindingRecord.agent_type` 字段作为组件 key，**不新建表**。两者可绑定到相同模型，也可分开绑定。

### 调度器集成

`MemoryConsolidationScheduler` 在 `sebastian/gateway/app.py` 的 lifespan startup 中创建并订阅 `SESSION_COMPLETED` 事件，shutdown 时调用 `aclose()` 清理 pending task。调度器收到事件后先检查 `memory_enabled` 标志，启用时才通过 `asyncio.create_task` 派发 `SessionConsolidationWorker`。

### Temperature 边界

Extractor / Consolidator 的理想运行方式是稳定、低随机性、严格 schema 输出。但短期不为 Memory 单独扩展 `LLMProvider` temperature 接口，也不把低 temperature 作为实现通过条件。

当前策略：

- 复用 provider 默认推理参数。
- 依靠固定 task、固定 schema、固定枚举和 schema validation 控制输出稳定性。
- 只有当真实效果显示默认参数导致不可接受的结构化输出波动时，再讨论是否扩展 provider 抽象。

### 3.1 Memory Component LLM Binding 路由

记忆组件（Extractor / Consolidator）的 LLM Provider 绑定通过**独立路由** `/memory/components` 管理，不复用 `/agents` 路由，不修改 `agents.py` 的 agent_type 校验逻辑。存储层仍复用 `AgentLLMBindingRecord` 表（不加新表），`agent_type` 字段的值即 `component_type`。

#### 白名单与元数据

```python
# sebastian/memory/consolidation/provider_bindings.py
MEMORY_COMPONENT_TYPES: frozenset[str] = frozenset({
    MEMORY_EXTRACTOR_BINDING,
    MEMORY_CONSOLIDATOR_BINDING,
})

MEMORY_COMPONENT_META: dict[str, dict[str, str]] = {
    MEMORY_EXTRACTOR_BINDING: {
        "display_name": "记忆提取器",
        "description": "从会话片段中提取候选 memory artifact",
    },
    MEMORY_CONSOLIDATOR_BINDING: {
        "display_name": "记忆沉淀器",
        "description": "会话结束后归纳 session summary 和推断偏好",
    },
}
```

路由层通过 `MEMORY_COMPONENT_TYPES` 校验 `component_type` 参数，通过 `MEMORY_COMPONENT_META` 获取 display name 和 description，不写死在路由文件中。

#### REST API

路由前缀：`/api/v1/memory/components`（注册在 `gateway/app.py` 中）。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/memory/components` | 列出所有 memory 组件及其当前绑定 |
| `GET` | `/memory/components/{component_type}/llm-binding` | 获取单个组件的绑定（无绑定时返回 `provider_id: null`） |
| `PUT` | `/memory/components/{component_type}/llm-binding` | 设置绑定（`provider_id: null` 清除，provider 不存在返回 400） |
| `DELETE` | `/memory/components/{component_type}/llm-binding` | 清除绑定（204 No Content） |

GET `/memory/components` 响应示例：

```json
{
  "components": [
    {
      "component_type": "memory_extractor",
      "display_name": "记忆提取器",
      "description": "从会话片段中提取候选 memory artifact",
      "binding": {
        "provider_id": "abc123",
        "thinking_effort": null
      }
    },
    {
      "component_type": "memory_consolidator",
      "display_name": "记忆沉淀器",
      "description": "会话结束后归纳 session summary 和推断偏好",
      "binding": null
    }
  ]
}
```

PUT 行为与 `/agents/{agent_type}/llm-binding` 一致：
- provider 的 `thinking_capability` 为 `"none"` 或 `"always_on"` → 强制清空 `thinking_effort`
- provider 切换时 `thinking_effort` 重置为 `null`

> **实现差异**：`LLMProviderRegistry.get_provider()` 的参数名为 `agent_type`（非 `binding_key`），返回类型为 `ResolvedProvider` dataclass（包含 `provider`、`model`、`thinking_effort`、`capability`），而非原始 `LLMProvider`。

#### Android 集成

在 `AgentBindingsPage` 中插入第二个 section "Memory Components"（位于 Orchestrator 之后、Sub-Agents 之前）：

- `MemoryComponentRow` 外观与 `AgentRow` 一致，icon 使用 `Icons.Outlined.Psychology`
- 点击行复用现有 `AgentBindingEditorPage`，通过 `isMemoryComponent: Boolean` 标志切换调用端点
- `AgentBindingsViewModel.load()` 并发请求 `GET /agents` + `GET /memory/components` + `GET /llm-providers`
- `AgentBindingEditorViewModel` 根据 `isMemoryComponent` 选择 `/agents/` 或 `/memory/components/` 端点

数据层：
- DTO：`MemoryComponentDto`（component_type / display_name / description / binding）
- Domain model：`MemoryComponentInfo`（与 `AgentInfo` 平行，不复用同一 data class）
- API：`ApiService` 新增 `listMemoryComponents()` 等 4 个方法

#### 存储说明

两个 memory component 的绑定存储在 `AgentLLMBindingRecord` 表中，`agent_type` 字段值分别为 `"memory_extractor"` 和 `"memory_consolidator"`，与 agent binding 行共存于同一表。Memory component 路由通过 `MEMORY_COMPONENT_TYPES` 白名单管理自己的键空间，agent 路由通过 `agent_registry` 管理自己的键空间，两者互不干扰。

---

## 3.2 MemoryService 运行时接线

`MemoryService` 是 memory 模块的运行时 composition root。Gateway lifespan 在 DB、slot registry、resident snapshot 初始化后创建：

```python
state.memory_service = MemoryService(
    db_factory=db_factory,
    resident_snapshot_refresher=resident_refresher,
    memory_settings_fn=lambda: state.memory_settings.enabled,
)
```

服务边界 contracts：

| Contract | 字段/语义 |
|----------|-----------|
| `PromptMemoryRequest` | `session_id`、`agent_type`、`user_message`、`subject_id`、`active_project_or_agent_context`、resident dedupe sets |
| `PromptMemoryResult` | `section: str`，保持现有 Markdown 注入格式 |
| `ExplicitMemorySearchRequest` | `query`、`session_id`、`agent_type`、`subject_id`、`limit=5` |
| `ExplicitMemorySearchResult` | `items: list[dict[str, Any]]`，兼容工具输出结构 |
| `MemoryWriteRequest` | `candidates`、`proposed_slots`、`session_id`、`agent_type`、`worker_id`、`model_name`、`rule_version`、`input_source`、`proposed_by` |
| `MemoryWriteResult` | dataclass，包含 `decisions`、slot 注册/拒绝列表，以及 `saved_count` / `discarded_count` 统计 |

降级行为集中在 `MemoryService`：

- memory disabled → prompt/search 返回空，write 返回空结果
- `db_factory is None` → prompt/search 返回空
- prompt/search 异常 → warning log + 空结果，不中断主对话
- `write_candidates()` 在有 resident refresher 时，使用 `mutation_scope()` 包住 DB commit 与 `mark_dirty_locked()`，避免快照读到 stale 状态

`write_candidates_in_session()` 是 caller-owned transaction 入口，供 `SessionConsolidationWorker` 在自己的事务内复用统一写入 pipeline；该方法不提交事务。

---

## 4. 两类模型职责

### 4.1 Memory Extractor（记忆提取器）

职责：

- 从用户消息、assistant 回复、tool 结果或会话片段中提取候选 artifacts
- 输出严格结构化 JSON
- 可用于显式写入辅助或后台沉淀输入整理；首期不在每轮对话结束后自动调用

要求：

- 快
- 稳
- 结构化输出一致
- 中文与中英混合语料理解可靠

#### 置信度评分规则

Extractor system prompt（`sebastian/memory/consolidation/prompts.py`）包含「置信度评分指南」，约束模型对 `confidence` 字段的评分行为：

| 分值区间 | 适用场景 |
|----------|---------|
| 0.9 – 1.0 | 用户明确陈述的事实（"我喜欢X"、"我叫X"、"我在X工作"） |
| 0.7 – 0.9 | 对话中直接体现但非明确声明（"每次都选X"、重复提及同一偏好） |
| 0.5 – 0.7 | 从行为或上下文推断的偏好，有一定根据但非直述 |
| 0.3 – 0.5 | 模糊线索或单次偶然提及，可信度较低 |
| < 0.3    | 高度不确定的推断，几乎只有间接证据（建议直接不提取） |

附加约束：
- `source` 为 `explicit` 时，confidence 不应低于 0.8
- `source` 为 `inferred` 时，confidence 上限建议不超过 0.75
- 若不确定是否值得提取，优先提高 confidence 阈值要求而非强行提取低质量记忆

### 4.2 Memory Consolidator（记忆沉淀器）

职责：

- 生成 session summary
- 执行 cross-session consolidation
- 对低置信候选做重判或归纳
- 提出偏好强化、关系沉淀、模式归纳建议

要求：

- 可比 extractor 稍慢
- 输出稳定性和一致性要求更高
- 运行在异步、后台路径

---

## 5. LLM 边界

应 deterministic 的能力：

- 显式 `memory_save`
- slot registry 查询
- 单槽位冲突覆盖
- 生命周期更新
- `status / validity / policy_tags` 过滤
- retrieval lane 预算与过滤框架
- decision log 落盘

适合交给 LLM 的能力：

- artifact extraction
- session summary
- cross-session consolidation
- 低置信候选的语义重判

约束：

- LLM 永远不直接改数据库状态
- LLM 永远不直接决定最终 `ADD / SUPERSEDE / MERGE / EXPIRE`
- 最终写入前必须经过 Normalize 和 Resolve

首期实现边界：

- `memory_save`（显式记忆保存）可走确定性 Normalize / Resolve，不要求 LLM 参与
- 会话结束后的 inferred memory（推断记忆）由后台 consolidation（沉淀）路径处理
- per-turn（逐轮）LLM extraction hook（提取钩子）暂不实现，避免主对话路径增加延迟和噪声写入

---

## 6. ExtractorInput / ExtractorOutput

```python
class ExtractorInput(TypedDict):
    task: Literal["extract_memory_artifacts"]
    subject_context: dict[str, Any]
    conversation_window: list[dict[str, Any]]
    known_slots: list[dict[str, Any]]

class ExtractorOutput(TypedDict):
    artifacts: list[CandidateArtifact]
    proposed_slots: list[ProposedSlot]
```

建议内容：

- `subject_context`
  - 默认主体、当前项目、当前 agent、session 主题
- `conversation_window`
  - 最近若干条消息或需提取的片段
- `known_slots`
  - 可供选择的 slot 定义，减少模型自由发挥

当前实现中 `MemoryExtractor.extract()` 返回 `ExtractorOutput`。`known_slots` 在 prompt 构造时按 `kind_constraints` 分组为 `known_slots_by_kind`，让模型先在当前 kind 对应的 slot 集合中复用，再考虑提议新 slot。

`MemoryExtractor.extract_with_slot_retry()` 支持动态 slot 失败反馈：调用方传入 `attempt_register` 回调，回调返回被拒的 `(slot_id, reason)` 列表；如非空，Extractor 追加上一轮 assistant JSON 和一条 user 反馈消息，最多再请求一次 LLM，并要求重新输出完整 JSON。

> **实现差异**：草案要求 `memory_save` 的预检和最终注册都走同一 `SlotProposalHandler.register_or_reuse()`；当前 `memory_save` 预检只调用 `validate_proposed_slot()`，真正写 DB 与热更新 registry 统一在 `process_candidates()` 中完成。这样避免预检阶段写入后又在 pipeline 重复注册。

---

## 7. CandidateArtifact

Extractor（提取器）的输出不应直接使用 `MemoryArtifact`（记忆产物），而应使用更保守的 `CandidateArtifact`（候选记忆产物）：

```python
class CandidateArtifact(TypedDict):
    kind: Literal["fact", "preference", "episode", "summary", "entity", "relation"]
    content: str
    structured_payload: dict[str, Any]
    subject_hint: str | None
    scope: str
    slot_id: str | None
    cardinality: Literal["single", "multi"] | None
    resolution_policy: Literal["supersede", "merge", "append_only", "time_bound"] | None
    confidence: float
    source: Literal["explicit", "inferred", "observed", "imported", "system_derived"]
    evidence: list[dict[str, Any]]
    valid_from: datetime | None
    valid_until: datetime | None
    policy_tags: list[str]
    needs_review: bool
```

Extractor 不负责：

- 生成最终 `subject_id`
- 决定最终冲突动作
- 直接写数据库
- 直接让旧记录失效

---

## 8. ConsolidatorInput

```python
class ConsolidatorInput(TypedDict):
    task: Literal["consolidate_memory"]
    session_messages: list[dict[str, Any]]
    candidate_artifacts: list[CandidateArtifact]
    active_memories_for_subject: list[dict[str, Any]]
    recent_summaries: list[dict[str, Any]]
    slot_definitions: list[dict[str, Any]]
    entity_registry_snapshot: list[dict[str, Any]]
```

核心要求：

- 必须看到当前已有 active memories
- 必须看到 slot 定义
- 必须看到本次会话的候选 artifacts

---

## 9. LLM 输出结果与 ProposedSlot

```python
class ConsolidationResult(TypedDict):
    summaries: list[dict[str, Any]]
    proposed_artifacts: list[CandidateArtifact]
    proposed_actions: list[dict[str, Any]]
    proposed_slots: list[ProposedSlot]
```

Consolidator 的职责是提出建议，而不是最终执行状态迁移。

四个字段的语义分工：

- `summaries`：Consolidator 生成的会话摘要，经 `resolve_candidate` 判断后写入 Episode Store
- `proposed_artifacts`：Consolidator 提议的新候选记忆；最终 ADD / SUPERSEDE / MERGE / DISCARD 由 Resolver 决定，LLM 不直接控制写入结果
- `proposed_actions`：对数据库中**已存在**记忆的生命周期操作建议，`action` 只允许 `"EXPIRE"`
- `proposed_slots`：LLM 提议注册的新 slot；Worker / pipeline 校验格式后自动注册，校验失败时触发一次重试或把相关 candidate 降级后交给 validate 处理（详见 §9.1）

`ProposedSlot` schema：

```python
class ProposedSlot(TypedDict):
    slot_id: str                # 必须符合 {scope}.{category}.{attribute} 格式
    scope: str                  # "user" | "session" | "project" | "agent"
    subject_kind: str           # e.g. "user", "project"
    cardinality: str            # "single" | "multi"
    resolution_policy: str      # "supersede" | "merge" | "append_only" | "time_bound"
    kind_constraints: list[str] # e.g. ["fact"] 或 ["preference"]
    description: str            # 人类可读描述
```

### 9.1 Slot 动态注册与重试机制

#### 触发条件

LLM 在 `artifacts` / `proposed_artifacts` 中提议一个 `fact` 或 `preference` 候选，但其 `slot_id` 未在当前 `SlotRegistry` 中注册时，必须同时在 `proposed_slots` 中提议注册该 slot。

调用方处理输出时：

1. **先处理 `proposed_slots`**，再处理 artifact candidates
2. 对每个 `ProposedSlot` 执行格式校验（见下方规则）
3. 校验通过 → `SlotProposalHandler.register_or_reuse()` 写入 `memory_slots`，并热更新 `SlotRegistry`
4. 校验失败 → 收集所有失败的 slot_id 和原因，Extractor 路径触发一次完整 JSON 重试；pipeline 路径把对应 candidate 的 `slot_id` 降级为 `None` 后继续统一 validate

#### Slot 命名规范（系统层强制校验）

```
格式：{scope}.{category}.{attribute}
示例：user.profile.name / user.preference.food / project.meta.priority

规则：
- 全小写，只允许字母、下划线和点
- 必须恰好包含 2 个点（三段式）
- scope 段必须是 "user" | "session" | "project" | "agent" 之一
- 总长不超过 64 字符
- `scope` 字段必须与 slot_id 首段一致
```

字段组合规则：

- `kind_constraints` 至少 1 项。
- 禁止 `cardinality=single + resolution_policy=append_only`。
- `resolution_policy=time_bound` 要求 `kind_constraints` 至少包含 `fact` 或 `preference`。

#### 重试机制

校验失败时，Extractor 构造一次补充提示，把失败原因反馈给 LLM：

```python
{
    "task": "fix_slot_proposals",
    "failed_slots": [
        {"slot_id": "user.name", "error": "格式不符：必须为三段式 {scope}.{category}.{attribute}"},
        {"slot_id": "user.pref.language", "error": "与已注册 slot 'user.preference.language' 完全重复"},
    ],
    "valid_slots_registered": ["user.profile.dietary_preference"],
    "instruction": "请重新输出完整 JSON（artifacts + proposed_slots），并同步修正相关 artifact.slot_id。"
}
```

LLM 必须返回完整 `ExtractorOutput`，而不是只返回修正后的 `proposed_slots`。

**最多重试 1 次**。重试后仍校验失败的 slot → pipeline 把对应 artifact 的 `slot_id` 置为 `None` 并交给 `SlotRegistry.validate_candidate()`；`fact` / `preference` 会因此生成 `DISCARD` decision，其他 kind 可继续作为无 slot artifact 处理。

> **实现增强**：slot INSERT 位于 `session.begin_nested()` savepoint 内，`IntegrityError` 只回滚到 slot 层 savepoint，不污染外层候选写入事务；race loser 会重新读取 DB 赢家并注册到内存。

> **实现差异**：并发赢家/失败事件当前主要通过 `logger` 与 `PipelineResult` 暴露，尚未作为独立 `memory_decision_log` 事件类型落库。

`ProposedAction` schema：

```python
class ProposedAction(TypedDict):
    action: Literal["EXPIRE"]   # 唯一合法值；ADD/SUPERSEDE 由 proposed_artifacts + resolver 承担
    memory_id: str              # 必填，指向 active profile memory 记录
    reason: str
```

`proposed_actions` 的存在意义是覆盖一类 resolver 无法单独处理的场景：某条 active 事实没有 `valid_until`，但 Consolidator 从本次会话语义判断它已过时，需要显式将其标为 `expired`，且不产生任何替代记忆。详见 `consolidation.md §1.1`。

---

## 10. ResolveDecision

```python
class ResolveDecision(TypedDict):
    decision: Literal["ADD", "SUPERSEDE", "MERGE", "EXPIRE", "DISCARD"]
    reason: str
    old_memory_ids: list[str]
    new_memory: dict[str, Any] | None
```

---

## 11. 结构化输出要求

无论 provider 来自云 API 还是本地模型，Extractor 和 Consolidator 都必须走严格结构化输出：

- 固定 schema
- 固定枚举
- 低随机性输出目标；当前使用 provider 默认参数，短期不新增 Memory 专用 temperature 接口
- schema validation

如模型输出不满足 schema：

- 允许有限重试
- 失败后进入保守降级路径
- 不允许因为 schema 错误而直接写入主存储

### 实现状态

- **schema validation**：已实现。`MemoryExtractor` 和 `MemoryConsolidator` 均在 LLM 输出后立即做 Pydantic schema 校验，失败时重试一次，重试后仍失败则返回空结果。
- **low temperature**：暂不通过 provider 抽象暴露。本轮使用 provider 默认值；仅当实测中出现不可接受的结构化输出波动时，再讨论是否扩展 provider 抽象以支持显式 temperature 设置。

---

## 12. 记忆系统降级行为

本节汇总各路径在**功能关闭、基础设施不可用或 LLM 失败**时的确定性降级行为，供实现者和测试者参考。

### 12.1 降级原则

- **记忆路径任何失败都不允许中断主对话流**：检索失败、存储失败、LLM 失败均降级为"无记忆上下文继续"，不抛出未捕获异常。
- **写入路径失败必须有可观测信号**：至少有 warning / error 日志和 trace；不允许静默吞掉写入失败（除非已记录 decision log）。
- **幂等标记写入时机决定重试窗口**（见 §12.4）。

### 12.2 功能开关降级（`memory_settings.enabled = false`）

| 路径 | 降级行为 |
|------|----------|
| `_memory_section()`（检索注入） | 立即返回 `""`，不进入检索流程 |
| `MemoryConsolidationScheduler._handle()` | 跳过任务调度，写 trace `consolidation.schedule_skip` |
| `SessionConsolidationWorker.consolidate_session()` | 立即返回，写 trace `consolidation.skip` |
| `sweep_unconsolidated()` | 立即返回，不处理任何 session |
| `memory_save` 工具 | 返回 `ToolResult(ok=False, error="记忆功能已关闭")` |

功能开关为运行时热切换（`PUT /api/v1/memory/settings`）；关闭后不影响已有数据，重新开启后下一轮会话正常触发沉淀。

### 12.3 基础设施不可用降级（DB 未就绪）

| 路径 | 降级行为 |
|------|----------|
| `_memory_section()`（`_db_factory is None`） | 立即返回 `""` |
| `memory_save` 工具 | 返回 `ToolResult(ok=False, error="记忆存储不可用")` |
| `SessionConsolidationWorker` | DB 操作抛出异常 → `MemoryConsolidationScheduler._log_exception()` 记录 error 日志，任务丢弃 |

DB 不可用时已触发的 consolidation task 失败后**不写幂等标记**，下次 startup sweep 会重试（见 §12.4）。

### 12.4 LLM 失败降级

#### Extractor 失败

`MemoryExtractor.extract()` 按指数退避（0.5s、1s、2s …）重试；用尽重试后返回 `[]`，**从不抛出异常**。

后果：consolidation 继续执行，但 `candidate_artifacts = []`；Consolidator 仍能根据原始 session 消息生成 summary，但 fact / preference 候选为空，本次会话的偏好提取可能缺失。

#### Consolidator 失败

`MemoryConsolidator.consolidate()` 同样指数退避重试；用尽后返回空 `ConsolidationResult`（`summaries=[], proposed_artifacts=[], proposed_actions=[]`），**从不抛出异常**。

> **已知数据丢失窗口**：当前实现中，Consolidator 返回空结果后，`SessionConsolidationWorker` 仍会写入 `SessionConsolidationRecord` 幂等标记（marker）并提交。这意味着：
> - 该 session 被标记为"已沉淀"
> - startup sweep 不会重试
> - **LLM 失败导致的空沉淀在数据库层面无法与正常空会话区分**

当前接受此行为，因为：
1. Consolidator 多次重试后仍失败属于极低概率事件
2. 主对话路径不受影响
3. 引入"失败标记"以支持重试会增加工作量，当前不做

**后续改进方向**（不在当前实现范围）：在 `SessionConsolidationRecord` 增加 `status` 字段（`success / failed_empty`），sweep 对 `failed_empty` 记录补重试一次。

### 12.5 检索路径异常降级

`_memory_section()` 内的所有异常均被 `except Exception` 捕获：

```python
except Exception:
    logger.warning("Memory section retrieval failed, continuing without memory context", exc_info=True)
    return ""
```

Agent 继续执行，本轮无记忆注入。`warning` 级日志包含完整 traceback，可由外层监控工具采集。

不记录 decision log（决策日志记录的是写入决策，不是检索失败）。

### 12.6 `memory_save` 工具错误响应

`memory_save` 是同步工具，前置检查、Extractor / pipeline 异常和 15s 超时都会同步返回 `ok=false`；成功时 `ToolResult.output` 是 `MemorySaveResult`，包含保存数量、丢弃数量、新注册 slot 与中文 summary。详见 [write-pipeline.md §9](write-pipeline.md#9-memory_save-工具调用契约)。

### 12.7 降级行为汇总表

| 场景 | 主对话影响 | 记忆数据影响 | 可观测信号 | 重试机制 |
|------|-----------|------------|-----------|---------|
| 功能关闭 | 无 | 不写入、不读取 | trace | N/A |
| DB 不可用（检索） | 无记忆注入 | 无 | — | 下次请求自动恢复 |
| DB 不可用（consolidation） | 无 | 不写入 | error log | startup sweep 重试 |
| Extractor LLM 失败 | `memory_save` 可返回“无可保存”结果；consolidation 继续 | fact/preference 候选丢失 | trace（候选数=0） | consolidation 继续执行 |
| Consolidator LLM 失败 | 无 | **整次沉淀静默丢失** | trace（count=0） + error log | **不重试（已知缺口）** |
| 检索抛出异常 | 无记忆注入 | 无 | warning log + traceback | 下次请求自动恢复 |
| Consolidation task 异常 | 无 | 不写入 | error log | startup sweep 重试 |

---

## 13. 常驻记忆快照（Resident Memory Snapshot）

### 13.0 实现状态

已实现。关键文件：

| 文件 | 职责 |
|------|------|
| `sebastian/memory/resident/resident_snapshot.py` | `ResidentMemorySnapshotRefresher`：快照读写、脏标记、重建触发 |
| `sebastian/memory/resident/resident_dedupe.py` | `canonical_bullet`、`slot_value_dedupe_key` 等去重纯函数 |
| `sebastian/memory/retrieval/retrieval.py` | `RetrievalContext` 新增 `resident_record_ids` / `resident_dedupe_keys` / `resident_canonical_bullets` 三字段；`MemorySectionAssembler` 在 `_keep()` 中过滤已注入记录 |
| `sebastian/memory/consolidation/consolidation.py` | `dirty scope` wrapping：会话沉淀 commit 后标记快照为脏，触发重建 |
| `sebastian/core/base_agent.py` | `_resident_memory_section()` 读取快照；`_memory_section()` 传入去重字段；`_stream_inner()` 按 base → resident → dynamic → todos 顺序拼接 system prompt |
| `sebastian/gateway/state.py` | `resident_snapshot_refresher` 单例 |
| `sebastian/gateway/app.py` | startup 调用 `rebuild()`，shutdown 调用 `cleanup()` |
| `sebastian/capabilities/tools/memory_save/__init__.py` | 工具 commit 后标记快照脏 |
| `sebastian/config/__init__.py` | `ensure_data_dir()` 中创建 `memory/` 子目录 |

快照文件路径：`settings.user_data_dir / "memory" / resident_snapshot.md`（内容）和 `resident_snapshot.meta.json`（元数据，含 `last_rebuilt_at`、`record_count` 等）。

详细设计见 [常驻记忆快照设计文档](../../../../superpowers/specs/2026-04-26-resident-memory-snapshot-design.md)。

---

## 14. 记忆功能设置持久化

### 14.1 `app_settings` KV 表

通用全局配置存储，不限于记忆功能。

```python
# sebastian/store/models.py
class AppSettingsRecord(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
```

已知常量（定义在 `store/app_settings_store.py`）：

```python
APP_SETTING_MEMORY_ENABLED = "memory_enabled"
```

### 14.2 `AppSettingsStore`

封装 KV 读写（`sebastian/store/app_settings_store.py`）：

```python
class AppSettingsStore:
    def __init__(self, session: AsyncSession) -> None: ...

    async def get(self, key: str, default: str | None = None) -> str | None:
        """查询指定 key，不存在返回 default。"""

    async def set(self, key: str, value: str) -> None:
        """Upsert：存在则更新 value + updated_at，不存在则插入。"""
```

### 14.3 Gateway 启动加载

`gateway/app.py` lifespan startup 中从 DB 加载记忆设置，覆盖环境变量默认值：

```python
async with db_factory() as session:
    app_settings_store = AppSettingsStore(session)
    mem_val = await app_settings_store.get(APP_SETTING_MEMORY_ENABLED)
    if mem_val is not None:
        mem_enabled = mem_val.lower() == "true"
    else:
        mem_enabled = settings.sebastian_memory_enabled  # 环境变量 fallback
state.memory_settings = MemoryRuntimeSettings(enabled=mem_enabled)
```

**优先级**：DB 有值 → 用 DB 值；DB 无值 → fallback 到环境变量 `SEBASTIAN_MEMORY_ENABLED`。

### 14.4 `PUT /api/v1/memory/settings` 持久化

`gateway/routes/memory_settings.py` 的 PUT 端点在更新内存状态的同时写入 DB：

```python
@router.put("/memory/settings", response_model=MemoryRuntimeSettings)
async def put_memory_settings(body: MemoryRuntimeSettings, ...) -> MemoryRuntimeSettings:
    async with state.db_factory() as session:
        store = AppSettingsStore(session)
        await store.set(APP_SETTING_MEMORY_ENABLED, str(body.enabled).lower())
        await session.commit()
    state.memory_settings = body
    return state.memory_settings
```

功能开关为运行时热切换；关闭后不影响已有数据，重新开启后下一轮会话正常触发沉淀。

### 14.5 Android 记忆设置页面

- **路由**：`Route.SettingsMemory`（`Route.kt` 中注册）
- **页面**：`MemorySettingsPage`（`ui/settings/`），使用 `SebastianSwitch` 组件
- **ViewModel**：`MemorySettingsViewModel`，乐观更新 → PUT → 失败回滚 + Snackbar 错误提示
- **DTO**：`MemorySettingsDto(enabled: Boolean)`
- **入口**：`SettingsScreen` 第一个分组 Card 中，`Agent LLM Bindings` 行下方，icon `Icons.Outlined.Psychology`，标题"记忆功能"，副标题"长期记忆开关"

### 14.6 数据库 Migration

项目使用 `Base.metadata.create_all` 自动建表，新增 `AppSettingsRecord` model 后在 `create_all` 前 import 即可，无需 Alembic migration。

---

*← 返回 [Memory 索引](INDEX.md)*
