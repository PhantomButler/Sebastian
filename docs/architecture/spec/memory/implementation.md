---
version: "1.0"
last_updated: 2026-04-19
status: implemented
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
```

Consolidator 的职责是提出建议，而不是最终执行状态迁移。

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
- 低 temperature
- schema validation

如模型输出不满足 schema：

- 允许有限重试
- 失败后进入保守降级路径
- 不允许因为 schema 错误而直接写入主存储

---

*← 返回 [Memory 索引](INDEX.md)*
