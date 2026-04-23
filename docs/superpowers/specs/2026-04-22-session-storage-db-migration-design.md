---
version: "1.0"
last_updated: 2026-04-22
status: planned
integrated_to: store/session-storage.md
integrated_at: 2026-04-23
---

# Session Storage SQLite Migration Design

## 背景

当前 session 数据仍以文件系统为事实源，分散在 `~/.sebastian/sessions/{agent_type}/{session_id}/`：

- `meta.json` 保存 session 元数据。
- `messages.jsonl` 保存 append-only 对话消息。
- `tasks/{task_id}.json` 保存 task 元数据。
- `tasks/{task_id}.jsonl` 保存 checkpoint 流。
- 历史上还存在 `sessions/index.json` 作为列表索引。

这个设计已经成为后续能力的阻碍：

- `get_messages()` 每次读取整个 `messages.jsonl` 再取尾部，长对话下有读放大。
- 文件消息没有结构化索引，按时间、role、session 范围查询只能内存过滤。
- 消息写入和记忆 DB 写入无法处于同一事务边界。
- 上下文压缩如果继续维护“当前 jsonl + 归档 jsonl”，会让视图切换和历史审计复杂化。
- 记忆增量需要按 session 顺序读取新增内容，文件实现只能全量读再过滤。

本次迁移不迁移旧 `~/.sebastian/sessions/` 测试数据。SQLite 成为新的唯一事实源，旧文件目录不再参与读写。

## 目标

- 将 Session、Timeline Item、Task、Checkpoint 迁移到 SQLite。
- 删除文件索引时代的 `IndexStore` 概念，将 session 列表和 activity 查询能力并入 `SessionStore`。
- 用 timeline item 模型替代 `message + blocks` 作为持久化抽象。
- 将 agent 上下文读取改为全量未归档上下文视图，不再固定取最近 20/50 条。
- 预留上下文压缩所需的 `archived` 和 `context_summary` 语义。
- 增加记忆增量可用的 `after_seq` 查询。
- 从一开始拆分 `SessionStore` 实现文件，避免把新 DB 逻辑继续堆到单个大文件。
- 将 per-session todos 从 `todos.json` 一并迁入 SQLite，避免 `sessions/` 目录继续作为运行时事实源。

## 非目标

- 不迁移旧文件系统 session 数据。
- 不实现上下文压缩 worker，只设计和实现支撑压缩的存储形态。
- 不要求 Android/Web 在 Phase 1 全量切换为 timeline 渲染。
- 不引入后台 async DB writer queue。
- 不做长期记忆系统的 Episode Store 重构。
- 不实现记忆增量 worker；仅为后续增量沉淀增加 cursor 字段和查询语义。

## 推荐方案

采用“直接切 SQLite，不迁移旧文件”的方案。

曾考虑过两种替代方案：

- SQLite + 一次性文件导入：能保留历史数据，但当前本地 session 均为测试数据，迁移逻辑、幂等 marker 和脏数据兼容没有收益。
- 文件和 SQLite 双写：表面安全，但会保留两个事实源，继续放大一致性和维护成本。

因此 Phase 1 直接以 SQLite 为唯一事实源。旧 `sessions/` 目录可以由用户手动删除，后端不再扫描它。

## 数据模型

### `sessions`

保存 `Session` 当前元数据和列表查询所需摘要字段。

核心字段：

- `id TEXT`
- `agent_type TEXT`
- `title TEXT`
- `goal TEXT`
- `status TEXT`
- `depth INTEGER`
- `parent_session_id TEXT NULL`
- `last_activity_at DATETIME`
- `created_at DATETIME`
- `updated_at DATETIME`
- `task_count INTEGER`
- `active_task_count INTEGER`
- `next_item_seq INTEGER DEFAULT 1`：下一条 timeline item 的 session 内 seq。

约束和索引：

- `PRIMARY KEY(agent_type, id)`。`id` 在当前生成策略下通常全局唯一，但 DB 约束以 `(agent_type, id)` 为准，匹配所有查询路径。
- index: `agent_type`
- index: `status`
- index: `parent_session_id`
- index: `last_activity_at`
- index: `(agent_type, parent_session_id, status)`

外键定位：

- `session_items(agent_type, session_id)` 指向 `sessions(agent_type, id)`。
- `session_todos(agent_type, session_id)` 指向 `sessions(agent_type, id)`。
- `tasks(agent_type, session_id)` 逻辑上指向 `sessions(agent_type, id)`。
- `checkpoints(agent_type, session_id)` 逻辑上指向 `sessions(agent_type, id)`。

SQLite 对复合外键支持有限且现有历史表需要幂等迁移；实现可先不强制所有历史表外键，但所有查询和写入必须按 `(agent_type, session_id)` 定位。

### `session_items`

`session_items` 是 session 内统一 timeline。它不只保存 user/assistant message，也保存 thinking、tool call、tool result、summary 和系统事件。

核心字段：

- `id TEXT PRIMARY KEY`：全局唯一 item id，建议使用 UUID。
- `session_id TEXT`
- `agent_type TEXT`
- `seq INTEGER`：session 内单调递增顺序号。
- `kind TEXT`：item 类型。
- `role TEXT NULL`：对 LLM/API 有意义的角色，例如 `user`、`assistant`、`tool`、`system`。
- `content TEXT`：主要文本内容，允许为空字符串。
- `payload JSON`：kind 特有结构。
- `archived BOOLEAN DEFAULT false`
- `created_at DATETIME`
- `turn_id TEXT NULL`：同一个 user turn / assistant turn / tool loop 的归属 ID。
- `provider_call_index INTEGER NULL`：一个 turn 内第几次 provider call。工具多轮循环时用于重建 provider 消息序列。
- `block_index INTEGER NULL`：同一次 provider call 内的 block 顺序。
- `effective_seq INTEGER NULL`：上下文视图排序锚点。普通 item 默认等于 `seq`，`context_summary` 使用被压缩范围的起点作为锚点。

约束和索引：

- `UNIQUE(agent_type, session_id, seq)`
- index: `(agent_type, session_id, archived, seq)`
- index: `(agent_type, session_id, archived, effective_seq, seq)`
- index: `(agent_type, session_id, created_at)`
- index: `(agent_type, session_id, kind, seq)`
- index: `(agent_type, session_id, turn_id, provider_call_index, block_index)`

首期 `kind`：

- `user_message`
- `assistant_message`
- `thinking`
- `tool_call`
- `tool_result`
- `context_summary`
- `system_event`
- `raw_block`

`payload` 示例：

```json
{
  "tool_call_id": "toolu_123",
  "tool_name": "inspect_session",
  "input": {"session_id": "..."},
  "ok": true,
  "model_content": "...string sent back to LLM...",
  "display": "..."
}
```

`context_summary` 的 `payload` 应记录来源范围：

```json
{
  "source_seq_start": 1,
  "source_seq_end": 120,
  "effective_seq": 1,
  "summary_version": "v1",
  "token_estimate": 1800
}
```

`tool_result` 必须区分模型输入内容和 UI 展示内容：

- `payload.model_content`：用于下一轮 LLM 上下文的内容，等价于当前 `_tool_result_content()` 的输出。
- `payload.display`：人类可读摘要，用于 UI/debug。
- `payload.raw_output` / `payload.error`：可选审计字段，不默认进入 LLM 上下文。

`thinking` 必须保留 provider 需要的元数据：

- `payload.signature`：Anthropic thinking signature。
- `payload.duration_ms`：UI/debug 用。
- `payload.provider` / `payload.thinking_format`：可选，用于兼容 OpenAI compatible `reasoning_content` / `think_tags`。

### `tasks`

复用现有 `tasks` 表名，但补齐 session 维度：

- 新增 `agent_type TEXT`
- 查询、更新和删除均按 `(agent_type, session_id, id)` 定位。
- task 写事务内刷新 `sessions.task_count` 和 `sessions.active_task_count`。

### `checkpoints`

复用现有 `checkpoints` 表名，但补齐归属字段：

- 新增 `agent_type TEXT`
- 新增 `session_id TEXT`
- 查询 checkpoint 时按 `(agent_type, session_id, task_id)` 定位。

### `session_todos`

当前 `TodoStore` 仍将 per-session todo 写到 `sessions/{agent_type}/{session_id}/todos.json`。如果目标是让旧 `sessions/` 目录不再参与运行时读写，todos 必须一并迁入 SQLite。

新增 `session_todos` 表：

- `session_id TEXT`
- `agent_type TEXT`
- `todos JSON`
- `updated_at DATETIME`

约束：

- `PRIMARY KEY(agent_type, session_id)`

`TodoStore` 可以保留类名，但底层改为 SQLite，构造方式从 `sessions_dir` 改为 DB session factory，或由 `SessionStore` 暴露 todo 方法。Phase 1 不迁移旧 `todos.json` 测试数据。

### `session_consolidations`

现有 `SessionConsolidationRecord` 只表示某个 `(session_id, agent_type)` 已完成一次性 consolidation。为后续增量记忆预留 cursor：

- `last_consolidated_seq INTEGER NULL`
- `last_seen_item_seq INTEGER NULL`
- `last_consolidated_source_seq INTEGER NULL`
- `consolidation_mode TEXT DEFAULT 'full_session'`

Phase 1 的 completed-session consolidation 仍可一次性处理全量上下文，并将 cursor 写为当时最大参与范围：

- `last_seen_item_seq`：已经扫描到的真实 item seq。
- `last_consolidated_source_seq`：已经沉淀过的语义来源范围最大 seq。

后续增量 worker 使用 `get_messages_since(after_seq=last_seen_item_seq)` 消费新增 item，但遇到 `context_summary` 时必须检查 `source_seq_end`：

- `source_seq_end <= last_consolidated_source_seq`：summary 只是已沉淀旧内容的压缩摘要，不再作为新事实沉淀。
- `source_seq_end > last_consolidated_source_seq`：summary 覆盖了新语义范围，可以进入增量处理，并更新 `last_consolidated_source_seq`。

这避免压缩后把已经 consolidation 过的旧内容摘要再次沉淀。

## Schema 迁移策略

当前仓库已经存在 SQLite 和 ORM 表，且 `tasks.id` 是全局主键、`checkpoints` 缺少 `session_id/agent_type`。本次不是只写 ORM class，还必须提供启动期幂等 schema patch。

落地方式：

- 在 `models.py` 新增 `SessionRecord`、`SessionItemRecord`、`SessionTodoRecord`。
- 调整 `TaskRecord`、`CheckpointRecord`、`SessionConsolidationRecord` ORM 字段。
- 在 `database.py::_apply_idempotent_migrations()` 增加 `ALTER TABLE` patch：
  - `tasks.agent_type TEXT DEFAULT 'sebastian'`
  - `checkpoints.session_id TEXT DEFAULT ''`
  - `checkpoints.agent_type TEXT DEFAULT 'sebastian'`
  - `session_consolidations.last_consolidated_seq INTEGER`
  - `session_consolidations.last_seen_item_seq INTEGER`
  - `session_consolidations.last_consolidated_source_seq INTEGER`
  - `session_consolidations.consolidation_mode TEXT DEFAULT 'full_session'`
- 新表由 `Base.metadata.create_all` 创建。
- 现有测试/开发 DB 中若已有 task/checkpoint 行，新增字段用 nullable/default 保证迁移不失败；后续新写入必须提供真实 `agent_type/session_id`。
- 新增索引使用幂等 `CREATE INDEX IF NOT EXISTS`。
- `TaskStore` 与 `SessionStore` 的 task 路径职责需要收口：要么删除 `TaskStore`，要么让它委托给新的 `session_tasks.py`，不能继续存在两套 task 写入语义。

## 存储接口

### `SessionStore`

`SessionStore` 是唯一 session 持久化入口，负责：

- session 元数据 CRUD。
- session 列表查询。
- active child 查询。
- activity 更新。
- timeline item 写入和读取。
- context message 投影。
- task/checkpoint CRUD。

SQLite 迁移后不再保留独立 `IndexStore` 存储概念。

`SessionStore` 应提供：

- `create_session(session)`
- `get_session(session_id, agent_type="sebastian")`
- `get_session_for_agent_type(session_id, agent_type)`
- `update_session(session)`
- `delete_session(session)`
- `list_sessions()`
- `list_sessions_by_agent_type(agent_type)`
- `list_active_children(agent_type, parent_session_id)`
- `update_activity(session_id, agent_type | None = None)`
- `append_message(...)`
- `append_timeline_items(...)`
- `get_context_timeline_items(session_id, agent_type)`
- `get_timeline_items(session_id, agent_type, include_archived=True)`
- `get_recent_timeline_items(session_id, agent_type, limit=25)`
- `get_context_messages(session_id, agent_type, provider_format, include_thinking=False)`
- `get_messages_since(session_id, agent_type, after_seq, limit=None)`
- task/checkpoint 现有 CRUD 方法。
- todo 读写方法，或提供 SQLite-backed `TodoStore`。

`get_messages()` 不再作为正式上下文主入口。实现迁移时应将调用点改为 `get_context_messages()`、`get_recent_timeline_items()` 或 `get_messages_since()`。

### 模块拆分

从 Phase 1 开始拆分实现，不把所有 SQL 逻辑堆在 `session_store.py`。

建议文件：

- `sebastian/store/session_store.py`：门面类 `SessionStore`，组合下列 helper。
- `sebastian/store/session_records.py`：session 元数据 CRUD、列表查询、activity、active children。
- `sebastian/store/session_timeline.py`：`session_items` 写入、seq 分配、archive/context/recent/since 视图。
- `sebastian/store/session_context.py`：timeline 到 provider-specific LLM messages 的投影。
- `sebastian/store/session_tasks.py`：Task / Checkpoint DB CRUD 和 count 刷新。
- `sebastian/store/session_todos.py`：per-session todo JSON 的 SQLite 读写，或由现有 `todo_store.py` 改为 DB-backed 实现。

## Timeline 写入

写入端分两层：

- `append_timeline_items()`：新的主要写入入口，一次写入一组 canonical timeline items。
- `append_message()`：短期便利入口，用于 user/system/plain assistant 写入和少量旧调用方适配。

`append_message()` 的转换规则：

- `role="user"` -> `kind="user_message"`
- `role="system"` -> `kind="system_event"`
- `role="assistant"` 且无 blocks -> `kind="assistant_message"`
- `role="assistant"` 且有 blocks：
  - `type="thinking"` -> `kind="thinking"`
  - `type="text"` -> `kind="assistant_message"`
  - `type="tool"`、`tool_use`、`tool_result` -> 拆为 `tool_call` / `tool_result`
  - 无法识别的 block -> `kind="raw_block"`，原始内容进入 `payload`

### `seq` 分配

`seq` 不能通过每次 `SELECT max(seq) + 1` 分配，否则并发 turn/resume/tool 写入可能读到同一个最大值。

Phase 1 使用 `sessions.next_item_seq` 作为单 session 计数器：

1. `append_timeline_items()` 开启 DB transaction。
2. 读取并锁定目标 session 的 `next_item_seq`。SQLite 下实现必须使用 SQLite 级别互斥：
   - 首选同一事务内的原子 `UPDATE ... RETURNING`。
   - 如果运行环境无法依赖 `RETURNING`，fallback 必须使用 `BEGIN IMMEDIATE` 后在同一事务中读写计数器。
   - 进程内 `asyncio.Lock` 只能作为减少本进程竞争的优化，不能作为正确性机制。
3. 对 N 条待写 item 分配 `[next_item_seq, next_item_seq + N - 1]`。
4. 将 `sessions.next_item_seq` 更新为 `next_item_seq + N`。
5. 插入所有 `session_items`。
6. transaction commit。

约束 `UNIQUE(agent_type, session_id, seq)` 仍保留，用于捕获实现 bug。若发生 `IntegrityError`，实现应 rollback 并重试有限次数，而不是静默丢消息。

测试必须覆盖同一 session 并发 append 后 seq 不重复且无空洞。

### BaseAgent 写入策略

不在流式热路径中对每个 delta 同步写 DB。

Phase 1 采用 turn 内缓冲 + 边界批量 flush：

- 用户输入：进入 turn 前立即写 `user_message`。
- `TextDelta` / `ThinkingDelta`：不写 DB，只用于 SSE 和 partial buffer。
- `ThinkingBlockStop`：放入 turn-local buffer。
- `TextBlockStop`：放入 turn-local buffer。
- `ToolCallReady`：放入 turn-local buffer，并继续执行工具。
- Tool result 完成：放入 turn-local buffer，成为独立 `tool_result` item。
- `TurnDone`：一次性批量写入本 turn 的 `thinking`、`assistant_message`、`tool_call`、`tool_result` items。
- 取消/中断：flush 已有 buffer 和 partial assistant message，避免丢失已经形成的 turn 内容。

每个 turn 应生成一个 `turn_id`。同一个 LLM provider call 内，按事件完成顺序写 `provider_call_index` 和 `block_index`。如果工具导致多次 provider call，同一个 assistant turn 内的第二轮 call 使用递增 `provider_call_index`，以便 context formatter 重建：

- Anthropic 的 assistant block list。
- Anthropic 下一轮 `role=user` 的 `tool_result` block。
- OpenAI 的 assistant `tool_calls`。
- OpenAI 后续 `role=tool` 消息。

这与现状一样，进程崩溃时仍可能丢当前未完成 assistant 输出。Phase 1 接受这个 trade-off，不引入后台 writer queue。

同一 turn 内的多轮 tool loop 不从 DB 重新读取刚产生的 tool_call/tool_result。AgentLoop 已经维护 provider-specific `working` 上下文；迁移后仍由 turn-local working state 加 pending timeline buffer 驱动后续 provider call。`get_context_messages()` 只用于 turn 启动前读取已持久化的上下文窗口，不负责合并当前 turn 尚未 flush 的 pending items。

必须测试：

- `tool_call -> tool_result -> 第二次 provider call` 的上下文来自 turn-local working state，工具结果不会漏喂给模型。
- `TurnDone` 后 pending timeline items 批量 flush 到 DB，并能被下一次 turn 的 `get_context_messages()` 读取。

## Context 投影

`session_items` 是 Sebastian 内部 canonical timeline。LLM Provider 输入格式仍然不同，需要在 provider 边界投影。

当前代码中：

- Anthropic：assistant 消息 `content` 是 block list，tool result 放在下一轮 `role="user"` 的 `tool_result` block 内。
- OpenAI：assistant 消息使用 `tool_calls` 字段，tool result 是独立 `role="tool"` 消息。

因此 `get_context_messages(session_id, agent_type, provider_format, include_thinking=False)` 或同等 formatter 必须按 `provider_format` 生成消息：

- `anthropic`：将连续 timeline items 投影为 Anthropic content blocks。
- `openai`：将 tool call 投影到 assistant `tool_calls`，将 tool result 投影成 `role="tool"`。

首期上下文规则：

- `get_context_timeline_items()` 读取 `archived=false` 的当前上下文 timeline。
- `user_message`、`assistant_message`、`tool_call`、`tool_result`、`context_summary` 参与上下文。
- `thinking` 存储为一等 timeline item，但默认不参与 `get_context_messages()`。
- `system_event` 是否进入上下文由具体调用点决定；默认不进入 provider messages。
- `raw_block` 不进入默认上下文。

Thinking 投影规则：

- 默认 agent 上下文不包含 historical thinking，避免把模型内部推理长期喂回模型。
- Anthropic provider 如未来要求 signed thinking continuation，可通过显式参数 `include_thinking=True` 或专门 replay/debug formatter 投影 thinking block。
- Phase 1 必须测试两种路径：默认 `get_context_messages(..., include_thinking=False)` 排除 thinking；Anthropic explicit thinking 投影保留 `payload.signature`。
- OpenAI compatible reasoning content / think tags 不进入默认 context，只保留在 timeline/UI/debug 视图。

投影排序规则：

- 先按 `effective_seq ASC`，再按 `seq ASC`。
- 普通 item 的 `effective_seq = seq`。
- `context_summary.effective_seq = source_seq_start`，所以 summary 在上下文视图中出现在被压缩范围的原始位置，而不是 append 位置。
- 当 `archived=false` 的尾部原文仍存在时，summary 会排在尾部原文之前，保持语义顺序。

Provider 投影必须用测试覆盖这些样例：

- Anthropic：`assistant_message + tool_call + tool_result + assistant_message` 重建为合法 block/user-tool-result 序列。
- OpenAI：同一 `provider_call_index` 的多个 `tool_call` 必须出现在同一 assistant message 的 `tool_calls` 中；对应 `tool_result` 必须带相同 `tool_call_id`。
- 显式 `include_thinking=True` 时，`thinking.signature` 必须保留在 Anthropic thinking block 中。

## Timeline 读取视图

### `get_context_timeline_items()`

返回压缩后的当前上下文 timeline。默认只包含 `archived=false` item，但包括 `context_summary`，因为 summary 是当前上下文的一部分。

`get_context_messages()` 可以基于该方法实现。

排序按 `(effective_seq, seq)`，不是单纯按插入 `seq`。

### `get_timeline_items(include_archived=True)`

返回完整历史，供 App UI、debug、审计使用。

完整历史应包含：

- archived 的原始 item。
- 未 archived 的当前上下文 item。
- `context_summary` 节点。
- 每个 item 的 `seq`、`kind`、`archived`、`created_at`。

这样用户在 App 中查看历史时，能看到哪里发生过压缩、压缩摘要是什么、哪些原始内容被移出当前上下文。

### `get_recent_timeline_items(limit=25)`

返回最近未归档 timeline 内容，包含 `context_summary`，不回溯 archived 原文。

主要用于：

- 权限审批上下文。
- debug 侧栏。
- inspect session。
- completion notifier。
- 轻量状态判断。

### `get_messages_since(after_seq)`

首期用于记忆增量，不包含 thinking。

包含：

- `user_message`
- `assistant_message`
- `tool_call`
- `tool_result`
- `context_summary`

不包含：

- `thinking`
- `raw_block`

## 上下文压缩模型

上下文压缩通过 timeline 视图切换实现，不删除历史。

流程：

1. 选择一段旧 item，例如 `seq <= 120`。
2. 将这些原始 item 标记为 `archived=true`。
3. 插入一条新的 `kind="context_summary"` item。
4. `context_summary.effective_seq` 和 `payload.effective_seq` 设置为 `source_seq_start`。
5. `get_context_timeline_items()` 只看到 summary 和后续未归档 item。
6. `get_timeline_items(include_archived=True)` 仍能看到完整历史和 summary 节点。

Phase 1 的读取层只定义视图，不实现压缩 worker。后续压缩实现必须保证一个被压缩范围内最多存在一个 active `context_summary`，避免上下文重复。

## 删除历史包袱

### `IndexStore`

`IndexStore` 是文件索引时代的历史概念。SQLite 迁移后，`sessions` 表本身就是可索引的 session 元数据表。

Phase 1 应删除独立 `IndexStore` 依赖，将能力并入 `SessionStore`。调用方不再同时注入 `session_store + index_store`。

受影响区域包括：

- `gateway/app.py`
- `gateway/state.py`
- `core/base_agent.py`
- `core/task_manager.py`
- `core/session_runner.py`
- `core/stalled_watchdog.py`
- sub-agent 相关 tools
- gateway routes
- tests
- TodoStore 初始化路径

`prune_orphans()` 删除。旧磁盘目录不再是事实源。

### 旧 `EpisodicMemory`

`sebastian/memory/episodic_memory.py` 当前只是会话历史兼容层：

- `add_turn()` -> `SessionStore.append_message()`
- `get_turns()` -> `SessionStore.get_messages(limit=...)`

它不是长期记忆系统的 Episode Store，名称会误导后续设计。

Phase 1 应将其从核心路径移除：

- `BaseAgent` 不再持有 `_episodic`。
- 用户消息、assistant flush、partial flush 直接写 timeline。
- 上下文读取直接使用 `SessionStore.get_context_messages()`。
- 删除 `episodic_memory.py`，或如果测试迁移需要短期过渡，则重命名为 `session_history.py`，但架构文档中不再称其为 memory。

## 调用点迁移

读取调用点按语义迁移：

- Agent 上下文：`BaseAgent` 使用 `get_context_messages()`。
- Memory consolidation / future incremental memory：使用 `get_messages_since()` 或 context/timeline 视图。
- UI/debug/inspect：使用 `get_timeline_items()` 或 `get_recent_timeline_items(limit=25)`。
- Completion notifier：使用 `get_recent_timeline_items(limit=25)` 或更小 limit。
- Watchdog / active children：使用 `SessionStore` 的 session 查询方法。
- Todo tools / BaseAgent todo section：使用 SQLite-backed todo store 或 `SessionStore` todo 方法。

### Gateway/API 响应契约

Phase 1 后端 API 可以保留兼容响应，但必须明确来源：

- `GET /sessions/{session_id}`：返回 `session`、`messages` 兼容投影、`timeline_items` 当前上下文 timeline。
- `GET /sessions/{session_id}/recent`：若存在，返回 `timeline_items = get_recent_timeline_items(limit=25)`，可附带普通 message 摘要。
- `inspect_session`：优先展示 timeline items，必要时附带 provider context 投影。
- `completion_notifier`：使用 `get_recent_timeline_items()` 查找最近 assistant/user 可读内容，不读取 archived 原文。
- `debug`/`stream`/`turns` routes：不直接读取文件；需要历史时通过 `SessionStore` timeline/context 方法。

`messages` 兼容投影 schema：

```json
{
  "role": "user|assistant|system|tool",
  "content": "...",
  "created_at": "2026-04-22T00:00:00Z",
  "seq": 12
}
```

兼容 `messages` 只用于 UI/旧调用方展示，不是 provider-specific context message；它不包含 Anthropic block list 或 OpenAI `tool_calls`。

`timeline_items` canonical schema：

```json
{
  "id": "...uuid...",
  "session_id": "...",
  "agent_type": "sebastian",
  "seq": 12,
  "effective_seq": 12,
  "turn_id": "...",
  "provider_call_index": 0,
  "block_index": 3,
  "kind": "tool_result",
  "role": "tool",
  "content": "...",
  "payload": {},
  "archived": false,
  "created_at": "2026-04-22T00:00:00Z"
}
```

Route view rules:

- `GET /sessions/{session_id}` 默认 `timeline_items = get_context_timeline_items()`，即未归档当前上下文，按 `(effective_seq, seq)` 排序。
- 如需完整审计，新增或扩展查询参数 `include_archived=true`，调用 `get_timeline_items(include_archived=True)`。
- `/recent` 默认 `limit=25`，只返回未归档 item，按 `seq DESC LIMIT 25` 查询后正序返回。
- `thinking` 在 timeline 中返回；兼容 `messages` 默认不返回 thinking。
- `context_summary` 在 timeline 中返回；兼容 `messages` 中可作为 `role="system"` 或专门摘要展示项，但不得伪装成用户原文。

现有 `BaseAgent` 的 `get_turns(limit=20)` 是技术债。Phase 1 移除固定截断，由 `get_context_messages()` 返回全量未归档上下文。上下文长度控制交给后续压缩功能。

## 分阶段落地

为降低主链路风险，实施计划应拆成可验证阶段，而不是一个大 patch：

1. **Schema + Store 基础层**：新增 ORM/migrations，拆出 records/timeline/context/tasks/todos helper，完成 `SessionStore` SQLite 门面和 store 单元测试。
2. **Context 投影层**：实现 `get_context_timeline_items()`、`get_context_messages(provider_format, include_thinking=False)`、recent/since 视图，补 Anthropic/OpenAI 投影测试。
3. **BaseAgent 写入切换**：移除旧 `EpisodicMemory` 主链路，改为 turn buffer + timeline flush；用户输入立即写 DB。
4. **IndexStore 退场**：迁移 watchdog、TaskManager、session_runner、tools 和 gateway state，使调用方只依赖 `SessionStore`。
5. **Gateway/API/Memory 调用点迁移**：更新 sessions/debug/inspect/completion notifier/consolidation，补集成测试。
6. **文档清理**：更新 store/memory/gateway/core README 和架构 spec，删除或标记旧文件存储说明。

每个阶段都应有独立测试通过后再进入下一阶段。

## 测试策略

新增或改造测试时优先使用 in-memory SQLite fixture。

必须覆盖：

- Session CRUD。
- Session list / by agent / active children / activity update。
- Timeline `seq` 连续递增。
- 批量 append 时 seq 连续且同一事务写入。
- `get_context_timeline_items()` 不含 archived 原文但含 `context_summary`。
- `get_timeline_items(include_archived=True)` 包含完整历史。
- `get_recent_timeline_items(limit=25)` 只看未归档最新窗口。
- `get_messages_since(after_seq)` 包含 user/assistant/tool/summary，不含 thinking。
- `context_summary` 增量查询按 `source_seq_end` 与 `last_consolidated_source_seq` 去重。
- `get_context_messages(provider_format="anthropic")` 的 tool_use/tool_result 投影。
- `get_context_messages(provider_format="openai")` 的 assistant tool_calls + role tool 投影。
- 默认 context 投影排除 thinking；显式 Anthropic thinking 投影保留 signature。
- `context_summary` 按 `effective_seq` 出现在被压缩范围原位置。
- Task / Checkpoint DB 读写。
- task count / active task count 刷新。
- SQLite-backed todo 读写。
- `sessions.next_item_seq` 并发 append 分配无重复 seq。
- `session_consolidations.last_seen_item_seq` / `last_consolidated_source_seq` 写入或迁移存在性。
- BaseAgent 不再固定 `limit=20`。
- Stalled watchdog 通过 `SessionStore` 查询和更新 activity。
- spawn/resume/delegate 子代理流程不再依赖 `IndexStore`。

建议验证命令：

```bash
pytest tests/unit/store -q
pytest tests/unit/core -q
pytest tests/unit/capabilities -q
pytest tests/integration/gateway -q
ruff check sebastian/ tests/
```

## 风险与取舍

- Turn 内缓冲意味着进程崩溃仍可能丢当前未完成 assistant 输出。这与当前 TurnDone 后一次性写 assistant blocks 的行为一致，Phase 1 接受。
- 删除 `IndexStore` 和旧 `EpisodicMemory` 会牵动较多调用点，但这是清理旧存储模型的一部分，不应推迟。
- Provider context 投影是高风险点。Anthropic/OpenAI 的 tool call/result 顺序和 ID 对应必须用测试锁住。
- `context_summary` 插入时的 `seq` 是真实写入顺序，`effective_seq` 是上下文排序顺序。所有上下文视图必须使用 `effective_seq`，审计视图可使用真实 `seq`。
- `sessions.next_item_seq` 是 seq 分配的事实源；任何绕过它直接写 `session_items` 的路径都会破坏顺序，必须禁止。
- `SessionStore` 门面应保持小而稳定，SQL 细节分散到 records/timeline/context/tasks helper 中，避免形成新的巨型文件。

## 验收标准

- 新建 session、发送消息、重启后能从 SQLite 读取完整 timeline。
- Agent 上下文来自全量未归档 timeline，不再取最近 20/50 条。
- tool call 和 tool result 在 DB 中是独立 timeline item。
- thinking 在 DB 中是一等 timeline item，但默认不进入 `get_context_messages()` 和 `get_messages_since()`。
- session 列表、active children、stalled watchdog 不依赖 `IndexStore`。
- task/checkpoint 不再写文件。
- Todo 不再写 `sessions/{agent_type}/{session_id}/todos.json`。
- 旧 `~/.sebastian/sessions/` 文件不再参与运行时读写。
