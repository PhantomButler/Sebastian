---
version: "1.3"
last_updated: 2026-05-03
status: in-progress
---

# Memory（记忆）写入流水线

> 模块索引：[INDEX.md](INDEX.md)
> 架构图：[../../diagrams/memory/write-pipeline.html](../../diagrams/memory/write-pipeline.html)

---

## 1. 总原则

### 1.1 外部访问边界

所有写入调用均通过 `MemoryService`（`sebastian/memory/services/memory_service.py`）进入，内部实现由 `MemoryWriteService`（`services/writing.py`）封装：

- `memory_save` 工具 → `MemoryService.write_candidates()`
- `SessionConsolidationWorker` → `MemoryService.write_candidates_in_session()`

两者最终都调用 `process_candidates()`（`sebastian/memory/writing/pipeline.py`），该函数是内部实现，不对外直接暴露。

`writing/` 子包边界：

| 文件 | 职责 |
|------|------|
| `pipeline.py` | `process_candidates()`：validate → resolve → persist → log 统一入口 |
| `resolver.py` | 画像冲突检测与 `ResolveDecision` 生成 |
| `write_router.py` | 按 kind 路由 artifact 到对应 store |
| `decision_log.py` | `MemoryDecisionLogger` 审计落库 |
| `feedback.py` | `memory_save` / `memory_search` 的用户可读摘要 |
| `slot_proposals.py` | ProposedSlot 校验、注册、并发 race 保护 |
| `slots.py` | `SlotRegistry` 与 builtin slots |

### 1.2 写入管线总原则

所有记忆写入来源都必须经过相同的逻辑阶段：

`Capture（捕获） -> Extract（提取） -> Normalize（规范化） -> Resolve（冲突解析） -> Persist（持久化） -> Index（索引） -> Schedule Consolidation（安排后台沉淀）`

这样可以避免 `memory_save`、session consolidation、tool observation 各自写一套逻辑。

**各阶段的实现可以因来源不同而简化，但不能被整体绕过：**

| 来源 | Extract | Normalize | Schedule Consolidation |
|------|---------|-----------|----------------------|
| `Explicit Write`（`memory_save`） | `MemoryExtractor` 对单条消息做 LLM 提取，分配 slot_id / kind；extractor 返回空则跳过保存（见 §9） | scope 固定 `USER`；subject_id 规则确定；slot_id 来自 extractor | 不主动调度；会话结束后 `SESSION_COMPLETED` 统一触发 |
| `Session Consolidation` | `MemoryExtractor`（全文）+ `MemoryConsolidator`（归纳） | 完整 slot/scope/subject 解析 | 不适用（本身即 consolidation） |
| `Cross-Session Consolidation` | 读已有 summaries 和 active memories | 完整解析 | 不适用 |

**Resolve → Persist → Index → log** 四个阶段对所有来源完全一致，统一由 `sebastian/memory/writing/pipeline.py::process_candidates()` 实现（见 §10）。

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

## 7. Dynamic Slot System（动态 Slot 系统）

### 7.1 内置 Seed Slot 集合

`SlotRegistry` 预置以下内置 slot（`sebastian/memory/writing/slots.py` 中硬编码），覆盖最高频的 user profile 场景：

| slot_id | kind | cardinality | 说明 |
|---------|------|-------------|------|
| `user.preference.response_style` | preference | single | 回复风格（简洁/详细/技术风格等） |
| `user.preference.language` | preference | single | 交流语言 |
| `user.profile.name` | fact | single | 用户姓名 |
| `user.profile.location` | fact | single | 当前所在城市/地区 |
| `user.profile.occupation` | fact | single | 职业/职位 |
| `user.current_project_focus` | fact | single | 用户当前主要关注的项目 |
| `user.profile.timezone` | fact | single | 用户所在时区 |
| `project.current_phase` | fact | single | 项目当前所处阶段 |
| `agent.current_assignment` | fact | single | Agent 当前被分配的任务 |

内置 slot 同时保留在代码中作为 seed fallback，并在 gateway 启动期通过 `seed_builtin_slots()` 幂等写入 `memory_slots` 表。随后 `bootstrap_slot_registry()` 从 DB 加载所有 slot（builtin + LLM proposed）到进程内 registry。

> **实现差异**：新设计草案使用表名 `slot_definitions` 与字段 `source`；当前代码已落地为 `memory_slots` 表，使用 `is_builtin: bool` 区分 builtin / dynamic，字段位于 `sebastian/store/models.py::MemorySlotRecord`。

> **实现增强**：`SlotRegistry(slots=None)` 仍会加载 9 个 builtin，避免测试或空 DB 场景下 registry 完全不可用；服务启动路径再从 DB additive bootstrap。

### 7.2 动态注册规则

LLM（`MemoryExtractor` / `MemoryConsolidator`）可在 `proposed_slots` 中提议新 slot，调用方收到后：

1. `validate_proposed_slot()` 校验命名：`{scope}.{category}.{attribute}` 三段式，纯小写 + 下划线，首段必须是合法 `MemoryScope`，总长不超过 64。
2. 校验字段组合：`kind_constraints` 非空；禁止 `single + append_only`；`time_bound` 至少适用于 `fact` 或 `preference`。
3. `SlotProposalHandler.register_or_reuse()` 先查内存 registry，已有则复用，不覆盖 metadata。
4. 不存在时在 `session.begin_nested()` savepoint 内 INSERT `memory_slots`；成功后热更新 `SlotRegistry`。
5. `IntegrityError` 表示并发 race，handler rollback 到 savepoint 后重新读取 DB 赢家，并把赢家 schema 注册回内存。
6. 校验失败由调用方反馈给 LLM，最多额外重试 1 次（详见 [implementation.md §9.1](implementation.md#91-slot-动态注册与重试机制)）。

动态注册的 slot 在进程重启后从 `memory_slots` DB 表恢复，与内置 slot 合并，保证持久生效。

### 7.3 Extractor / Consolidator 中的 slot 上下文

`ExtractorInput.known_slots` 与 `ConsolidatorInput.slot_definitions` 都传入当前**所有已注册 slot**（内置 + 动态注册）。prompt 层通过 `prompts.py::group_slots_by_kind()` 按 `kind_constraints` 分桶展示，让 LLM 在提议之前能判断：

- 现有 slot 是否已覆盖此场景 → 直接使用，不新建
- 无合适 slot → 提议新建

系统提示词中需明确：**优先使用已有 slot；仅在没有语义吻合的已有 slot 时才提议新建。**

> **实现增强**：Extractor 和 Consolidator 共用 `prompts.py` 的 slot 规则与示例，避免两套 prompt 漂移；`policy_tags` 字段说明明确为“一般 []，不要主动设置任何值”，避免 LLM 误设 `pinned`。

## 8. subject_id 在 Normalize 阶段的赋值规则

Normalize 阶段负责把 `CandidateArtifact.subject_hint`（Extractor 产出的松散提示）转为正式的 `subject_id`，写入最终 `MemoryArtifact`。

### 8.1 解析逻辑（当前 Phase B / C）

解析函数：`sebastian/memory/subject.py::resolve_subject(scope, *, session_id, agent_type)`

| `scope` | `subject_id` 值 | 说明 |
|---------|----------------|------|
| `USER` | `"owner"` | 单用户阶段固定为常量 `OWNER_SUBJECT = "owner"` |
| `PROJECT` | `"owner"` | Phase B 暂与 USER 共用 owner；Phase 5 按项目 ID 区分 |
| `AGENT` | `f"agent:{agent_type}"` | 按 agent_type 编码，隔离各 agent 的记忆空间 |
| `SESSION` | `f"session:{session_id}"` | 按 session_id 编码，仅在 session 内有效 |

### 8.2 subject_hint 的当前角色

`CandidateArtifact.subject_hint` 是 Extractor / Consolidator 产出的提示字段，**当前不参与实际 subject_id 解析**。Normalize 直接根据 `candidate.scope` 调用 `resolve_subject()`，忽略 hint。

`subject_hint` 保留的原因：
- Phase 5 多用户扩展时，`USER` scope 下需要通过 hint 区分不同用户
- 日志与审计回溯时提供 LLM 的原始意图参考

**当前约束**：如果 Extractor 把 `subject_hint` 设成了具体用户名或实体 ID，Normalize 不使用该值，以避免 subject 污染。

### 8.3 Phase 5 扩展方向

多用户阶段（Phase 5）将扩展 `resolve_subject()` 逻辑：

- `USER` scope：从 identity 系统查询当前请求者的用户 ID，不再固定返回 `"owner"`
- `PROJECT` scope：从 session 上下文中取 project_id，映射到 project entity ID
- `subject_hint` 作为辅助参考，但最终 ID 必须经 identity 系统校验

**当前不实现**，也不允许在 subject.py 里提前添加 hint-based 分支。

---

## 9. `memory_save` 工具调用契约

本节面向调用 `memory_save` 工具的 Agent，定义入参语义、内部处理规则和错误行为。

### 9.1 触发条件

`memory_save` 仅在**用户明确要求记住某件事**时调用，例如"帮我记住……"、"你记一下……"。其他场景（对话推断、行为观察、后台沉淀）不走此工具，均由后台 consolidation 流程处理。

### 9.2 入参定义

Agent 只需传一个字段：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | `str` | 是 | 要记住的内容，用自然语言描述 |

**Agent 不传、也不需要知道的字段**（由 Extractor / pipeline 确定）：

| 字段 | 推断规则 |
|------|----------|
| `slot_id` / `kind` | 由 `MemoryExtractor` 从 `content` 提取（LLM 分配） |
| `scope` | 由 Extractor 输出；显式记忆保存通常为 `USER` |
| `confidence` | 由 Extractor 输出；显式来源建议接近 `0.95` |
| `source` | 由 Extractor 输出；显式记忆保存通常为 `explicit` |
| `subject_id` | 由 `resolve_subject(candidate.scope, session_id, agent_type)` 确定 |
| `policy_tags` | 由 Extractor 输出；prompt 要求一般为 `[]`，不要主动设置 |
| `structured_payload` | 来自 extractor 输出，工具层不另行填充 |
| `valid_from` / `valid_until` | 来自 Extractor 输出；一般为 `null` |
| `needs_review` | 来自 Extractor 输出；不确定时为 `true` |

> **实现差异**：早期设计要求 `memory_save` 工具层强制覆盖 `scope/source/confidence/policy_tags`；当前代码把这些字段交给 `ExtractorOutput` 与统一 validate/resolve 流程处理，工具层只负责同步执行、slot proposal 注册和事务提交。

### 9.3 同步执行流程

`memory_save` 是**同步工具**：tool call 会 await Extractor、slot proposal 校验/注册、`process_candidates()` 与 `commit()`，然后把真实保存结果作为 `ToolResult.output` 返回给 Agent。

**完整流程**：

```
1. 调用 MemoryExtractor.extract_with_slot_retry(
       conversation_window=[{"role": "user", "content": content}],
       known_slots=[所有已注册 slot]
   )
   → 得到 ExtractorOutput(artifacts, proposed_slots)

2. proposed_slots 先经过 validate_proposed_slot 预检；若失败，反馈给 LLM 重试一次

3. 调用 process_candidates(candidates, proposed_slots, session_id, agent_type, ...)
   → register proposed slots → validate → resolve → persist → log（见 §10）

4. commit 成功后返回 MemorySaveResult：
   saved_count / discarded_count / proposed_slots_registered /
   proposed_slots_rejected / summary
```

同步化的原因：Claude tool-use 协议要求 `tool_use` / `tool_result` 1:1 配对，后台完成后无法再以同一次 tool result 补充真实状态。短文本记忆保存的 LLM 调用延迟可接受，直接同步返回能让 Agent 准确回复“已记住 / 未保存 / 新增了分类”。

### 9.4 错误响应

以下错误同步返回 `ok=false`：

| 错误消息 | 触发条件 | Agent 应对策略 |
|---------|---------|---------------|
| `记忆功能当前已关闭，无法保存。` | `memory_settings.enabled = false` | 告知用户，不重试 |
| `记忆存储暂时不可用，无法保存，请稍后再试。` | DB 连接未就绪 | 告知用户可稍后重试 |
| `记忆处理超时，未能保存。` | `MEMORY_SAVE_TIMEOUT_SECONDS = 15.0` 超时 | 告知用户可稍后重试 |
| `保存失败：...` | Extractor / DB / pipeline 未捕获异常 | 告知用户保存失败 |

### 9.5 成功响应

```json
{
  "saved_count": 1,
  "discarded_count": 0,
  "proposed_slots_registered": [],
  "proposed_slots_rejected": [],
  "summary": "已记住 1 条记忆。"
}
```

`ok=true` 表示本次同步处理已完成。`summary` 由 `sebastian/memory/writing/feedback.py::render_memory_save_summary()` 生成，Agent 可直接引用或改写。

---

## 10. 共享写入管线：`process_candidates()`

### 10.1 职责

`process_candidates()` 是所有写入来源的**共同后半段**，封装 Validate → Resolve → Persist → Index → Log 五个确定性阶段，不含任何 LLM 调用。

位置：`sebastian/memory/writing/pipeline.py`

```python
async def process_candidates(
    candidates: list[CandidateArtifact],
    proposed_slots: list[ProposedSlot] | None = None,
    *,
    session_id: str,
    agent_type: str,
    db_session: AsyncSession,
    profile_store: ProfileMemoryStore,
    episode_store: EpisodeMemoryStore,
    entity_registry: EntityRegistry,
    decision_logger: MemoryDecisionLogger,
    slot_registry: SlotRegistry,
    slot_proposal_handler: SlotProposalHandler | None = None,
    worker_id: str,
    model_name: str | None,
    rule_version: str,
    input_source: dict[str, Any],
    proposed_by: Literal["extractor", "consolidator"] = "extractor",
) -> PipelineResult:
```

处理顺序：

1. **Register proposed slots**：若 `proposed_slots` 非空，必须传入 `slot_proposal_handler`；注册失败的 slot_id 记录到 `PipelineResult.proposed_slots_rejected`。
2. **Downgrade affected candidates**：引用失败 slot_id 的 candidate 会复制一份并把 `slot_id=None`，再进入统一 validate。
3. **Normalize subject**：`resolve_subject(candidate.scope, session_id, agent_type)` → `subject_id`。
4. **Validate**：`slot_registry.validate_candidate(candidate)`；校验失败 → 构造 `DISCARD` decision，写 log，跳过后续步骤。
5. **Resolve**：`resolve_candidate(candidate, subject_id=..., ...)` → `ResolveDecision`。
6. **Persist**：`decision.decision != DISCARD` 时调 `persist_decision(...)`（含 FTS Index）。
7. **Log**：`decision_logger.append(decision, worker=worker_id, ...)`。

返回 `PipelineResult`，包含所有 decisions、已注册 slot_id、被拒 slot 明细，以及 `saved_count` / `discarded_count` 统计。

### 10.2 调用方

| 调用方 | 传入的 candidates 来源 |
|--------|----------------------|
| `memory_save` 同步工具 | `MemoryExtractor.extract_with_slot_retry(单条消息)` |
| `SessionConsolidationWorker` | `MemoryExtractor.extract(全文)` + `MemoryConsolidator.consolidate()` 输出的 summaries / proposed_artifacts |

两者传入同一函数，保证 Validate → Resolve → Persist → Log 逻辑完全一致，不各自维护一套。

### 10.3 不在此函数内的职责

- **Extract**（B）：由调用方自行完成（LLM Extractor / Consolidator）
- **source / confidence 覆盖策略**：由调用方和 Extractor prompt 协议决定，pipeline 不隐式改写 candidate 内容
- **proposed_actions（EXPIRE）**：`SessionConsolidationWorker` 在调用 `process_candidates()` 之外单独处理，因为 EXPIRE 不经过 validate/resolve，直接调 `persist_decision` + log
- **Session 幂等标记**：`SessionConsolidationWorker` 在所有 `process_candidates()` 调用完成后写入，不在此函数内

---

*← 返回 [Memory 索引](INDEX.md)*
