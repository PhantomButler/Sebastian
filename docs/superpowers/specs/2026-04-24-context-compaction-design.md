# 上下文自动压缩设计

## 背景

Sebastian 的 session 历史已经统一存储在 SQLite `session_items` 中，并且已经具备“压缩后上下文视图”的基础模型：

- 完整审计历史通过 `get_timeline_items(include_archived=True)` 读取
- LLM 当前上下文通过 `get_context_timeline_items()` 读取
- 被压缩的源记录可以标记为 `archived=true`
- `context_summary` 可以用 `effective_seq = source_seq_start` 站在被压缩范围的原始位置

当前缺失的是运行时压缩系统：当长 session 接近模型上下文窗口时，Sebastian 应该把较旧的上下文压缩成摘要，同时保留最近若干轮原文。

本功能服务的是 **短期 session 上下文**，不是长期记忆。它不替代 Profile / Episode / Relation memory。但压缩摘要必须保留可被记忆系统提取的事实，这样现有 session consolidation worker 在读取压缩后的 context view 时，仍然能提取有价值的长期记忆候选。

## 目标

- 防止长 session 撞到 provider context limit。
- 保留完整审计历史，供 UI、debug 和未来 replay 使用。
- 保证压缩后的 LLM continuation context 仍然连贯。
- 优先使用 provider 返回的真实 token usage，缺失时使用本地估算器兜底。
- 同时支持自动压缩和手动触发压缩。
- 保持 provider-neutral，兼容 Anthropic、OpenAI-compatible，以及智谱等 OpenAI-compatible API。

## 非目标

- 不删除历史 session item。
- 不把 provider 原生 compaction 作为核心路径。OpenAI Responses `compact` 等能力可作为未来 provider-specific 优化。
- 不把 context compaction 放进长期记忆写入链路。
- 不压缩正在 streaming 的 active turn。
- 不解决 cross-session memory consolidation。

## 架构

新增 `sebastian/context/` 包：

```text
sebastian/context/
├── usage.py          # TokenUsage 与 provider usage 归一化辅助
├── estimator.py      # TokenEstimator 本地兜底估算器
├── token_meter.py    # ContextTokenMeter 阈值判断
├── compaction.py     # SessionContextCompactionWorker
└── prompts.py        # context summary prompt
```

职责边界：

| 层 | 职责 |
|----|------|
| `llm/` | 将各 provider 的 usage 格式归一成 `TokenUsage` |
| `core/` | 通过 `ProviderCallEnd` 传递 usage；turn 结束后触发压缩检查 |
| `context/` | token 计量、压缩范围选择、摘要生成、压缩编排 |
| `store/` | 提供 archive + 插入 summary 的原子 timeline 更新 |
| `memory/` | 不变，继续负责长期记忆提取与沉淀 |

## Timeline 语义

`assistant_turn_id` 保持现有语义：它用于聚合同一次 assistant response 内的 assistant-side blocks 和 provider call sequence。它不是用户对话轮次边界。

新增 exchange 字段：

```text
sessions.next_exchange_index INTEGER DEFAULT 1

session_items.exchange_id TEXT NULL
session_items.exchange_index INTEGER NULL
```

字段定义：

| 字段 | 语义 |
|------|------|
| `seq` | session 内 timeline item 的真实写入顺序 |
| `exchange_id` | 一次用户输入及其触发的全部 assistant/tool 输出的唯一 ID |
| `exchange_index` | 同一 session 内从 1 开始递增的用户交互序号 |
| `assistant_turn_id` | assistant block 聚合 ID，用于 UI/provider projection |

示例：

| seq | kind | exchange_id | exchange_index | assistant_turn_id |
|---:|------|-------------|---------------:|-------------------|
| 1 | `user_message` | `ex-A` | 1 | `NULL` |
| 2 | `assistant_message` | `ex-A` | 1 | `asst-A` |
| 3 | `tool_call` | `ex-A` | 1 | `asst-A` |
| 4 | `tool_result` | `ex-A` | 1 | `asst-A` |
| 5 | `assistant_message` | `ex-A` | 1 | `asst-A` |
| 6 | `user_message` | `ex-B` | 2 | `NULL` |
| 7 | `assistant_message` | `ex-B` | 2 | `asst-B` |

分配流程：

1. `BaseAgent.run_streaming()` 确认 session 存在。
2. 分配一个 `exchange_id` 和 `exchange_index`。
3. 用户消息写入时带上该 exchange。
4. `_stream_inner()` 接收 exchange，并写入 assistant、thinking、tool call、tool result item。
5. cancel / stop 的 partial flush 也使用同一个 exchange。

旧数据中 exchange 字段为空仍然合法。压缩 worker 通过扫描 `user_message` 边界重建 logical exchange。

## Token Usage

新增归一化 usage 类型：

```python
@dataclass
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    raw: dict[str, Any] | None = None
```

扩展 `ProviderCallEnd`：

```python
@dataclass
class ProviderCallEnd:
    stop_reason: str
    usage: TokenUsage | None = None
```

Provider 映射：

- Anthropic：从 final message 或 streaming event usage 中读取。有效 input pressure 为 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`。
- OpenAI Chat-compatible：发送 `stream_options={"include_usage": true}`，捕获最后一个 `choices=[]` 的 usage chunk。
- 其他 OpenAI-compatible provider：尝试按同一格式解析，缺失则兜底。
- 未来 Responses API 路径：映射 `response.completed.response.usage`，并可选接入 input-token preflight counting。

`ContextTokenMeter` 的来源优先级：

```text
provider actual usage
> provider preflight count（实现后）
> local TokenEstimator
```

本地估算器是必需的：stream 可能被 cancel，网络可能中断，兼容 provider 也可能不返回 usage。

## 触发策略

阈值：

```text
usage_soft_threshold = context_window * 0.70
estimate_soft_threshold = context_window * 0.65
usage_hard_threshold = context_window * 0.85
```

规则：

- 有 provider usage 时，effective input tokens 超过模型 context window 的 70% 触发 soft 压缩（`reason="usage_threshold"`）。
- 有 provider usage 且超过 85% 时触发 hard 压缩（`reason="usage_hard"`）；hard 优先于 soft 判断，语义上是 soft 失败/skip 后的兜底档。
- 只有本地估算时，超过 65% 自动压缩（`reason="estimate_threshold"`）。
- emergency compaction（provider 返回 context length exceeded 时同步压缩并重试 turn）为独立功能，不在 v1 范围内。

触发时机：

- 自动压缩在 `TurnDone` 已持久化后执行。
- 自动压缩作为后台任务运行，不阻塞 response stream。
- 手动压缩立即执行，但要求该 session 当前没有 active stream。

## 压缩范围选择

压缩范围必须按完整 exchange 切分，不能按任意 item 切分。

默认值：

```text
retain_recent_exchanges = 8
min_compactable_items = 12
min_source_tokens = 8000
```

算法：

1. 读取当前 context timeline items。
2. 优先按 `exchange_index` / `exchange_id` 分组。
3. 旧数据按 `user_message` 边界分组。
4. 保留最近 `retain_recent_exchanges` 个 raw exchanges。
5. 可压缩范围为：最早未归档 raw exchange 到保留窗口之前的最后一个完整 exchange。
6. 如果源范围太小，跳过压缩。

不压缩：

- 最近保留窗口中的 exchanges
- active streaming exchange
- 不完整 tool chain，例如有 `tool_call` 但缺少匹配的 `tool_result`
- v1 不压缩已有 `context_summary`

未来可以在 summary 积累过多时设计 summary-of-summary。

## Summary 契约

`context_summary.content` 使用 Markdown。它是带有 memory-preserving facts 的 runtime handoff summary：

```markdown
## Compressed Session Context

### User Goal
...

### Current Working State
...

### Key Decisions And Constraints
- ...

### Tool Results And Artifacts
- ...

### Memory-Relevant Facts Preserved
- [preference] ...
- [profile] ...
- [current_state] ...
- [relationship] ...

### Open Threads
- ...

### Handoff Notes
...
```

Prompt 约束：

- 保留下一轮 LLM 继续工作所需的 continuation state。
- 保留用户明确表达或强证据支持的偏好、画像事实、当前状态事实、关系事实。
- 不编造、不泛化，不把临时上下文升级成长期事实。
- 保留继续工作需要的具体名称、路径、ID、任务状态、工具结果和决策。
- 避免低价值逐条转述聊天记录。

摘要预算：

```text
summary_target_tokens = min(8192, max(2048, source_tokens * 0.20))
```

## Summary Payload

`context_summary.payload`：

```json
{
  "summary_version": "context_compaction_v1",
  "source_seq_start": 12,
  "source_seq_end": 148,
  "source_exchange_start": 3,
  "source_exchange_end": 18,
  "source_token_estimate": 42000,
  "summary_token_estimate": 3200,
  "retained_recent_exchanges": 8,
  "model": "claude-...",
  "reason": "auto_threshold"
}
```

## Timeline 原子更新

新增 `SessionTimelineStore.compact_range(...)`。

输入：

- `session_id`
- `agent_type`
- `source_seq_start`
- `source_seq_end`
- `summary_content`
- `summary_payload`
- `effective_seq = source_seq_start`

事务流程：

1. 查询源范围内 items。
2. 校验所有源 items 仍为 `archived=false`。
3. 校验范围不包含保留 exchanges。
4. 将源 items 更新为 `archived=true`。
5. 插入一条 `context_summary`，`archived=false`，`effective_seq=source_seq_start`。
6. commit。

并发行为：

- 如果任一源 item 已经 archived，返回 `already_compacted`。
- 默认不重试；下一次 compaction check 会基于新的 context view 重新判断。

## API

手动压缩：

```http
POST /api/v1/sessions/{session_id}/compact
```

请求：

```json
{
  "mode": "manual",
  "retain_recent_exchanges": 8,
  "dry_run": false
}
```

`retain_recent_exchanges` 为 `int`，默认 `8`（非 nullable）。`dry_run` 默认 `false`：设为 `true` 时选择压缩范围但不调用 LLM 也不持久化，用于预检。

**dry_run 门槛语义**：dry_run 仍受 range 选择门槛约束（范围选不出来时返回 `skipped/range_too_small`），但**不受** `min_source_tokens`（默认 8000）门槛约束——即使源 token 估算低于门槛，只要能选出范围就返回 `dry_run` + 范围元数据。这是为了让调用方在小 session 上也能预览理论压缩范围，与 `reason="manual"` 的豁免行为一致。

响应（`status="compacted"` 时）：

```json
{
  "status": "compacted",
  "summary_item_id": "...",
  "source_seq_start": 1,
  "source_seq_end": 148,
  "archived_item_count": 96,
  "source_token_estimate": 42000,
  "summary_token_estimate": 3200
}
```

响应（`status="dry_run"` 时）：

```json
{
  "status": "dry_run",
  "summary_item_id": null,
  "source_seq_start": 1,
  "source_seq_end": 148,
  "archived_item_count": 96,
  "source_token_estimate": 42000,
  "summary_token_estimate": null
}
```

`archived_item_count` 在 dry_run 语境下是**将要**被 archive 的条数，非实际 archive 数；`summary_token_estimate` 为 null（未生成 summary）。

`status` 实际取值：`"compacted" | "skipped" | "dry_run"`。`already_compacted` 并发冲突内部映射为 `status="skipped", reason="already_compacted"`，不单独暴露为 status 值。

状态接口：

```http
GET /api/v1/sessions/{session_id}/compaction/status
```

响应：

```json
{
  "token_estimate": 56000,
  "last_summary_seq": 121,
  "compactable_exchange_count": 14,
  "retained_recent_exchanges": 8
}
```

实现备注：字段名为 `token_estimate`（非 `context_token_estimate`）；`context_window` 和 `last_compacted_at` 字段未实现，不在响应中。

`compactable_exchange_count` = 当前 context view 中非 archived、非 `context_summary` 的 exchange 分组数减去 `retained_recent_exchanges`，下限 0。不单独排除进行中的 exchange；手动 compact 路径由 409 拦截 active stream，不存在竞争。

错误与跳过：

- active stream：`409`，`detail: "Session has an active streaming turn; retry after the turn completes."`
- 没有有价值的压缩范围：`200`，body `{"status": "skipped", "reason": "range_too_small"}`
- 已被其他 worker 压缩：`200`，body `{"status": "skipped", "reason": "already_compacted"}`

## Android UX

App 当前已通过 `include_archived=true` 加载完整历史，所以压缩不会隐藏原始消息。现有 `SummaryBlock` 可以继续把 `context_summary` 渲染成折叠卡片。

首版 UI：

- 在 debug / settings 里增加 `Compact context` 操作。
- 不需要复杂聊天 UI 改动。
- 后续可在 summary card 中展示压缩范围 metadata。

## 与 Memory Consolidation 的关系

现有 session consolidation worker 读取 `get_context_timeline_items()`。压缩后它看到的是：

```text
context_summary + 最近未压缩 raw exchanges
```

它不会看到 archived 的原始源记录。

v1 接受这个行为，因为 summary prompt 会显式保留 memory-relevant facts。未来如果需要更高保真，可以让 memory consolidation 读取 full audit history，并做分段处理。

## 测试计划

后端单元测试：

- Anthropic、OpenAI-compatible、missing usage 的 `TokenUsage` 归一化。
- `TokenEstimator` 覆盖英文、中文、tools、结构化 messages。
- `ContextTokenMeter` 覆盖真实 usage 与估算值的阈值判断。
- exchange allocation 在同一 session 内递增，并写入 user、assistant、tool call、tool result、cancel partial items。
- 从旧数据 user-message 边界重建 exchange。
- range selection 保留最近 exchanges，并跳过不完整 tool chain。
- `compact_range()` 原子 archive 源记录并插入一条 summary。
- `compact_range()` 在并发/archive conflict 时返回 `already_compacted`。
- provider context projection 安全处理 `context_summary`，避免无效的连续 user/tool 结构。

集成测试：

- 长 session 在 turn 完成后触发自动压缩。
- 手动 compact endpoint 返回压缩 metadata。
- active stream 时手动 compact 返回 409。
- `GET /sessions/{id}` 返回 context view：包含 summary，不包含 archived 源记录。
- `GET /sessions/{id}?include_archived=true` 返回完整 audit history。
- session consolidation 可以处理已压缩 session 的 summary。

Android 测试：

- 暴露 exchange 字段后，`TimelineItemDto` 能正确解析。
- timeline mapper 仍然渲染 archived 源记录和 `SummaryBlock`。
- summary toggle 行为保持稳定。

## 风险

- Summary 丢信息：通过固定 handoff schema 和 memory-relevant facts section 缓解。
- Summary 幻觉：通过 prompt 约束缓解；summary 不直接写 memory，仍经过 extractor/resolver。
- Provider usage 缺失：通过 estimator fallback 缓解。
- 过度压缩：通过最近 exchange 保留窗口和最小源范围限制缓解。
- 与 active streaming 竞争：手动压缩返回 409；自动压缩只在 turn 持久化后运行。
- Memory consolidation 保真度：v1 可接受；未来可升级为分段读取 audit history。

## 实施阶段

1. Provider usage plumbing：
   - `TokenUsage`
   - `ProviderCallEnd.usage`
   - Anthropic / OpenAI-compatible 映射
2. Exchange 字段：
   - schema migration
   - exchange allocation
   - 写入路径透传
3. Context package：
   - estimator
   - token meter
   - range selection
   - compaction prompt / worker
4. Store 原子压缩：
   - `compact_range()`
   - ordering 和并发测试
5. Runtime / API：
   - turn 后自动调度
   - 手动 compact / status endpoints
6. Android / debug UX：
   - 手动 compact 操作
   - 可选 summary metadata 展示
