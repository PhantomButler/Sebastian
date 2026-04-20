---
version: "1.0"
last_updated: 2026-04-19
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

引入两个 provider binding 常量（`sebastian/memory/provider_bindings.py`）：

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

## 6. ExtractorInput

```python
class ExtractorInput(TypedDict):
    task: Literal["extract_memory_artifacts"]
    subject_context: dict[str, Any]
    conversation_window: list[dict[str, Any]]
    known_slots: list[dict[str, Any]]
```

建议内容：

- `subject_context`
  - 默认主体、当前项目、当前 agent、session 主题
- `conversation_window`
  - 最近若干条消息或需提取的片段
- `known_slots`
  - 可供选择的 slot 定义，减少模型自由发挥

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

## 9. ConsolidationResult

```python
class ConsolidationResult(TypedDict):
    summaries: list[dict[str, Any]]
    proposed_artifacts: list[CandidateArtifact]
    proposed_actions: list[dict[str, Any]]
    proposed_slots: list[ProposedSlot]          # 新增：LLM 提议的新 slot 定义
```

Consolidator 的职责是提出建议，而不是最终执行状态迁移。

四个字段的语义分工：

- `summaries`：Consolidator 生成的会话摘要，经 `resolve_candidate` 判断后写入 Episode Store
- `proposed_artifacts`：Consolidator 提议的新候选记忆；最终 ADD / SUPERSEDE / MERGE / DISCARD 由 Resolver 决定，LLM 不直接控制写入结果
- `proposed_actions`：对数据库中**已存在**记忆的生命周期操作建议，`action` 只允许 `"EXPIRE"`
- `proposed_slots`：LLM 提议注册的新 slot；Worker 校验格式后自动注册，校验失败时触发一次重试（详见 §9.1）

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

### 9.1 Slot 动态注册与多轮重试机制

#### 触发条件

LLM 在 `proposed_artifacts` 中提议一个 `fact` 或 `preference` 候选，但其 `slot_id` 未在当前 `SlotRegistry` 中注册时，应同时在 `proposed_slots` 中提议注册该 slot。

Worker 在处理 `ConsolidationResult` 时：

1. **先处理 `proposed_slots`**，再处理 `proposed_artifacts`
2. 对每个 `ProposedSlot` 执行格式校验（见下方规则）
3. 校验通过 → 自动注册到 `SlotRegistry`，写 decision log（`input_source: "slot_proposal"`）
4. 校验失败 → 收集所有失败的 slot_id 和原因，触发一次重试

#### Slot 命名规范（系统层强制校验）

```
格式：{scope}.{category}.{attribute}
示例：user.profile.name / user.preference.food / project.meta.priority

规则：
- 全小写，只允许字母、数字、下划线和点
- 必须恰好包含 2 个点（三段式）
- scope 段必须是 "user" | "session" | "project" | "agent" 之一
- 每段长度 2-40 字符
- 不允许与已注册 slot_id 完全相同（精确去重）
```

#### 重试机制

校验失败时，Worker 构造一次补充提示，把失败原因反馈给 LLM：

```python
{
    "task": "fix_slot_proposals",
    "failed_slots": [
        {"slot_id": "user.name", "error": "格式不符：必须为三段式 {scope}.{category}.{attribute}"},
        {"slot_id": "user.pref.language", "error": "与已注册 slot 'user.preference.language' 完全重复"},
    ],
    "valid_slots_registered": ["user.profile.dietary_preference"],
    "instruction": "请修正上述 slot_id 后重新提交 proposed_slots，或将相关 artifact 的 slot_id 改为已有 slot。"
}
```

LLM 返回修正后的 `proposed_slots`（不需要重新输出全部 ConsolidationResult）。

**最多重试 1 次**。重试后仍校验失败的 slot → 对应 artifact 改为 `DISCARD`，写 decision log（`reason: "slot_proposal_failed_after_retry"`）。

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

`memory_save` 是非阻塞工具，只有前置检查（功能开关、DB 可用性）会同步返回 `ok=false`；实际写入在后台执行，失败只记 error log 和 trace。详见 write-pipeline.md §9.4。

### 12.7 降级行为汇总表

| 场景 | 主对话影响 | 记忆数据影响 | 可观测信号 | 重试机制 |
|------|-----------|------------|-----------|---------|
| 功能关闭 | 无 | 不写入、不读取 | trace | N/A |
| DB 不可用（检索） | 无记忆注入 | 无 | — | 下次请求自动恢复 |
| DB 不可用（consolidation） | 无 | 不写入 | error log | startup sweep 重试 |
| Extractor LLM 失败 | 无 | fact/preference 候选丢失 | trace（候选数=0） | consolidation 继续执行 |
| Consolidator LLM 失败 | 无 | **整次沉淀静默丢失** | trace（count=0） + error log | **不重试（已知缺口）** |
| 检索抛出异常 | 无记忆注入 | 无 | warning log + traceback | 下次请求自动恢复 |
| Consolidation task 异常 | 无 | 不写入 | error log | startup sweep 重试 |

---

*← 返回 [Memory 索引](INDEX.md)*
