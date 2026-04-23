---
version: "1.0"
last_updated: 2026-04-23
status: implemented
---

# Session Storage SQLite Migration

*← [Store 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 背景

Session 数据曾以文件系统为事实源（`~/.sebastian/sessions/{agent_type}/{session_id}/`），存在读放大、缺乏结构化索引、无法事务写入等问题。本设计将 Session、Timeline Item、Task、Checkpoint、Todo 全部迁移到 SQLite，使其成为唯一事实源。

旧文件目录不再参与运行时读写。`IndexStore` 概念已删除，session 列表和 activity 查询并入 `SessionStore`。`EpisodicMemory` 兼容层已从核心路径移除。

## 数据模型

### `sessions`

保存 session 元数据和列表查询摘要字段。

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

- `PRIMARY KEY(agent_type, id)`
- index: `agent_type`
- index: `status`
- index: `parent_session_id`
- index: `last_activity_at`
- index: `(agent_type, parent_session_id, status)`

> **实现备注**：ORM 模型 `SessionRecord` 完整实现上述字段和索引。`task_count` / `active_task_count` 由 `SessionTaskStore` 在 task 写事务内原子刷新。

### `session_items`

session 内统一 timeline。不只保存 user/assistant message，也保存 thinking、tool call、tool result、summary 和系统事件。

核心字段：

- `id TEXT PRIMARY KEY`：全局唯一，UUID。
- `session_id TEXT`
- `agent_type TEXT`
- `seq INTEGER`：session 内单调递增。
- `kind TEXT`：item 类型。
- `role TEXT NULL`
- `content TEXT`
- `payload JSON`
- `archived BOOLEAN DEFAULT false`
- `created_at DATETIME`
- `turn_id TEXT NULL`
- `provider_call_index INTEGER NULL`
- `block_index INTEGER NULL`
- `effective_seq INTEGER NULL`

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

`payload` 示例（tool_result）：

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

`payload` 示例（context_summary）：

```json
{
  "source_seq_start": 1,
  "source_seq_end": 120,
  "effective_seq": 1,
  "summary_version": "v1",
  "token_estimate": 1800
}
```

关键区分：

- `tool_result.payload.model_content`：用于下一轮 LLM 上下文。
- `tool_result.payload.display`：人类可读摘要，用于 UI/debug。
- `thinking.payload.signature`：Anthropic thinking signature。

> **实现备注**：ORM 模型 `SessionItemRecord` 完整实现，所有索引和约束已通过 `__table_args__` 声明。

### `tasks`

复用现有 `tasks` 表，补齐 session 维度：

- `agent_type TEXT`
- 查询、更新和删除均按 `(agent_type, session_id, id)` 定位。
- task 写事务内刷新 `sessions.task_count` 和 `sessions.active_task_count`。

> **实现备注**：`TaskRecord` 已包含 `agent_type` 和 `session_id` 字段，`SessionTaskStore` 负责原子 task count 刷新。

### `checkpoints`

复用现有 `checkpoints` 表，补齐归属字段：

- `agent_type TEXT`
- `session_id TEXT`
- 查询按 `(agent_type, session_id, task_id)` 定位。

> **实现备注**：`CheckpointRecord` 已包含 `session_id` 和 `agent_type` 字段。

### `session_todos`

per-session todo 的 SQLite 存储：

- `session_id TEXT`
- `agent_type TEXT`
- `todos JSON`
- `updated_at DATETIME`
- `PRIMARY KEY(agent_type, session_id)`

> **实现备注**：`SessionTodoRecord` 实现。`TodoStore` 门面委托给 `SessionTodoStore`（SQLite-only）。

### `session_consolidations`

已有 consolidation 记录，为增量记忆预留 cursor：

- `last_consolidated_seq INTEGER NULL`
- `last_seen_item_seq INTEGER NULL`
- `last_consolidated_source_seq INTEGER NULL`
- `consolidation_mode TEXT DEFAULT 'full_session'`

增量 worker 使用 `get_messages_since(after_seq=last_seen_item_seq)` 消费新增 item。遇到 `context_summary` 时按 `source_seq_end` 与 `last_consolidated_source_seq` 去重。

> **实现备注**：`SessionConsolidationRecord` 已包含全部 cursor 字段。

## Schema 迁移策略

- ORM class 在 `models.py` 中定义，新表由 `Base.metadata.create_all` 创建。
- `_apply_idempotent_migrations()` 在 `database.py` 中处理 `ALTER TABLE` patch（新增列用 nullable/default 保证不失败）。
- 新增索引使用幂等 `CREATE INDEX IF NOT EXISTS`。
- PK rebuild 逻辑处理复合主键列顺序修复。

> **实现备注**：`database.py` 已实现完整的幂等迁移框架，包括 PK rebuild、obsolete column drop、confidence normalization。

## 存储接口

### `SessionStore` 门面

`SessionStore` 是唯一 session 持久化入口，委托给四个 SQLite helper：

- `SessionRecordsStore`：session 元数据 CRUD、列表查询、activity、active children。
- `SessionTimelineStore`：`session_items` 写入、seq 分配、各类视图查询。
- `SessionTaskStore`：Task / Checkpoint DB CRUD 和 count 刷新。
- `SessionTodoStore`：per-session todo JSON 的 SQLite 读写。

核心方法：

- `create_session(session)` / `get_session(session_id, agent_type)` / `update_session(session)` / `delete_session(session)`
- `list_sessions()` / `list_sessions_by_agent_type(agent_type)` / `list_active_children(agent_type, parent_session_id)`
- `update_activity(session_id, agent_type)`
- `append_timeline_items(session_id, agent_type, items)` — 主要写入入口
- `append_message(session_id, role, content, agent_type, blocks)` — 便利入口，内部转换为 timeline items
- `get_context_timeline_items(session_id, agent_type)` — LLM 上下文视图
- `get_timeline_items(session_id, agent_type, include_archived)` — audit/历史视图
- `get_recent_timeline_items(session_id, agent_type, limit)` — 最近未归档窗口
- `get_context_messages(session_id, agent_type, provider_format, include_thinking)` — provider-specific 投影
- `get_messages_since(session_id, agent_type, after_seq)` — 增量查询
- Task/checkpoint CRUD 方法
- Todo 读写（通过 `TodoStore` 门面）

### 模块拆分

```
sebastian/store/
├── session_store.py       # 门面 SessionStore
├── session_records.py     # SessionRecordsStore
├── session_timeline.py    # SessionTimelineStore
├── session_context.py     # build_context_messages() / build_legacy_messages()
├── session_tasks.py       # SessionTaskStore
├── session_todos.py       # SessionTodoStore
├── todo_store.py          # TodoStore 门面（委托 SessionTodoStore）
├── database.py            # engine/session factory / 幂等迁移
└── models.py              # ORM 模型
```

> **实现备注**：实际代码完全遵循此拆分。`todo_store.py` 是薄门面委托给 `session_todos.py`。

## Timeline 写入

### seq 分配

使用 `sessions.next_item_seq` 作为单 session 计数器，通过 `UPDATE ... RETURNING` 原子分配：

1. 开启 DB transaction。
2. 原子读取并递增 `next_item_seq`。
3. 对 N 条待写 item 分配连续 seq。
4. 插入所有 `session_items`。
5. transaction commit。

约束 `UNIQUE(agent_type, session_id, seq)` 捕获实现 bug。

> **实现备注**：`SessionTimelineStore.append_items()` 使用 `UPDATE ... RETURNING` 实现原子 seq 分配。

### BaseAgent 写入策略

Phase 1 采用 turn 内缓冲 + 边界批量 flush：

- 用户输入：进入 turn 前立即写 `user_message`。
- `TextDelta` / `ThinkingDelta`：不写 DB，只用于 SSE 和 partial buffer。
- `ThinkingBlockStop` / `TextBlockStop` / `ToolCallReady`：放入 turn-local buffer。
- `TurnDone`：一次性批量写入本 turn 所有 items。

每个 turn 生成一个 `turn_id`，同一 provider call 内按事件完成顺序写 `provider_call_index` 和 `block_index`。

## Context 投影

`session_items` 是 Sebastian 内部 canonical timeline。LLM Provider 输入格式通过 `build_context_messages()` 投影：

- `anthropic`：将 timeline items 投影为 Anthropic content blocks（tool result 放在下一轮 `role="user"` 的 `tool_result` block）。
- `openai`：将 tool call 投影到 assistant `tool_calls`，将 tool result 投影成 `role="tool"`。

上下文规则：

- `get_context_timeline_items()` 读取 `archived=false` 的当前上下文 timeline。
- `thinking` 存储为一等 timeline item，但默认不进入 `get_context_messages()`。
- 投影排序按 `(effective_seq ASC, seq ASC)`。
- `context_summary` 的 `effective_seq = source_seq_start`，在上下文视图中出现在被压缩范围的原始位置。

`build_legacy_messages()` 将 timeline items 投影为 UI 兼容的 role/content 消息列表。

## Timeline 读取视图

### `get_context_timeline_items()`

返回压缩后的当前上下文 timeline（`archived=false` + `context_summary`）。排序按 `(effective_seq, seq)`。

### `get_timeline_items(include_archived=True)`

返回完整 audit timeline（真实 `seq ASC` 顺序），供 App UI、debug、审计使用。

### `get_recent_timeline_items(limit=25)`

返回最近未归档 timeline 内容，用于权限审批上下文、debug、inspect session、completion notifier。

### `get_messages_since(after_seq)`

增量查询，用于记忆增量。包含 user/assistant/tool/summary，不含 thinking/raw_block。

## 上下文压缩模型

通过 timeline 视图切换实现，不删除历史：

1. 选择旧 item 范围，标记 `archived=true`。
2. 插入 `kind="context_summary"` item，`effective_seq = source_seq_start`。
3. `get_context_timeline_items()` 只看到 summary 和后续未归档 item。
4. `get_timeline_items(include_archived=True)` 仍能看到完整历史。

Phase 1 只定义视图，不实现压缩 worker。

## 已删除的历史包袱

- **`IndexStore`**：已删除。session 列表和子 session 查询均由 `SessionStore` 管理。
- **`EpisodicMemory`**：已从核心路径移除。`BaseAgent` 不再持有 `_episodic`，上下文读写直接使用 `SessionStore`。
- **文件系统 JSON 路径**：`SessionStore` 保留了 deprecated 文件系统 fallback（`sessions_dir`），但仅用于迁移工具。生产模式必须注入 `db_factory`。

## Gateway/API 契约

- `GET /sessions/{session_id}?include_archived=true`：返回 `timeline_items`（完整 audit timeline，`seq ASC`）和 legacy `messages`。
- `GET /sessions/{session_id}`（不带 `include_archived`）：返回当前上下文视图的 `timeline_items`。
- `/recent` route：`get_recent_timeline_items(limit=25)`。
- `thinking` 在 timeline 中返回，兼容 `messages` 默认不返回。
- `context_summary` 在 timeline 中返回。

## 测试覆盖

- Session CRUD、list / by agent / active children / activity update
- Timeline seq 连续递增、批量 append 同一事务
- `get_context_timeline_items()` 不含 archived 原文但含 `context_summary`
- `get_timeline_items(include_archived=True)` 完整历史
- `get_recent_timeline_items(limit=25)` 只看未归档最新窗口
- `get_messages_since(after_seq)` 包含 user/assistant/tool/summary，不含 thinking
- Anthropic / OpenAI context 投影（tool_use/tool_result 映射、thinking signature）
- `context_summary` 按 `effective_seq` 出现在被压缩范围原位置
- Task / Checkpoint DB 读写、task count 刷新
- SQLite-backed todo 读写
- 并发 append 无重复 seq

验证命令：

```bash
pytest tests/unit/store -q
pytest tests/unit/core -q
pytest tests/integration/gateway -q
ruff check sebastian/ tests/
```

---

*← [Store 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
