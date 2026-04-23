---
version: "1.0"
last_updated: 2026-04-22
status: planned
---

# Session Storage SQLite 迁移 Bug 修复设计

## 背景

对 `2026-04-22-session-storage-db-migration-design.md` 实现（从 commit `62e5a085` 开始）做了 review，发现以下问题未在实现中覆盖或实现有误。本 spec 描述修复方案。

原始 review 问题清单：
- **高**：`effective_seq` 写入静默为 NULL
- **高**：`turn_id / provider_call_index / block_index` 全部缺失
- **高**：OpenAI 投影在同一 group 含 tool_calls+text 时生成两条连续 assistant 消息（违反 OpenAI API）
- **高**：`cancel_session` 路径只 flush `_partial_buffer`，`assistant_blocks` 丢失
- **高**：`IntegrityError` 无 rollback + 重试
- **中**：`sessions` 复合主键列顺序 `(id, agent_type)` 应为 `(agent_type, id)`
- **中**：`get_messages_since` 未排除 `system_event`
- **中**：`tool_use` block 的 `content` 字段为空
- **中**：`episodic_memory.py` 未删除/重命名

## 实施分组

同一 feature branch，按逻辑关系分两组 commit：

- **Commit 组 1（Schema 层）**：sessions 表重建、effective_seq 写入修复、schema 启动验证
- **Commit 组 2（Logic 层）**：turn_id 生成、cancel flush 修复、OpenAI 投影修复、其余 medium 问题

每组 commit 后独立跑测试通过再继续。

---

## Commit 组 1：Schema 层修复

### 1.1 sessions 表复合主键重建

**问题**：`SessionRecord` ORM 声明主键列顺序为 `(id, agent_type)`，导致 SQLite 底层建表为 `PRIMARY KEY (id, agent_type)`，与 spec 要求的 `PRIMARY KEY (agent_type, id)` 相反。SQLite 不支持 `ALTER PRIMARY KEY`，需重建表。

**修复**：

`models.py` 中 `SessionRecord` 的列声明顺序改为 `agent_type` 在前：

```python
agent_type: Mapped[str] = mapped_column(String, primary_key=True)
id: Mapped[str] = mapped_column(String, primary_key=True)
```

`database.py` 的 `_apply_idempotent_migrations()` 中增加 PK 顺序检测和重建逻辑：

```python
# 检测 sessions 表的建表语句，判断 PK 列顺序是否需要修正
row = await conn.execute(
    text("SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'")
)
sql = (row.scalar() or "").lower()
# 旧建表语句中 id 在 agent_type 前出现于 PRIMARY KEY 段落
if "primary key" in sql and sql.index("\"id\"") < sql.index("\"agent_type\""):
    # 重建流程
    await conn.execute(text("ALTER TABLE sessions RENAME TO _sessions_old"))
    # create_all 会建出正确结构的新表
    await conn.run_sync(lambda sync_conn: Base.metadata.tables["sessions"].create(sync_conn))
    await conn.execute(text("INSERT INTO sessions SELECT * FROM _sessions_old"))
    await conn.execute(text("DROP TABLE _sessions_old"))
```

同理检查并修复 `session_consolidations` 表的主键列顺序（当前为 `(session_id, agent_type)`，应为 `(agent_type, session_id)`）。

### 1.2 effective_seq 写入层修复

**问题**：`SessionItemRecord.effective_seq` 仅声明 `nullable=True`，无默认值。普通 item 插入时若调用方未传 `effective_seq`，该字段为 NULL，导致依赖 `(effective_seq, seq)` 排序的上下文视图在压缩场景下返回错误结果。

**修复**：

在 `session_timeline.py` 的 `_append_items_locked()` 中，批量插入前对每条 item 强制赋值：

```python
for item in items:
    if item.get("effective_seq") is None:
        item["effective_seq"] = item["seq"]  # seq 在此处已分配完毕
```

`context_summary` 类型的 item 必须由调用方显式传入 `effective_seq`（等于 `source_seq_start`），不走上述 fallback。

### 1.3 Schema 启动验证（防止类似问题再发）

在 `database.py` 增加 `_verify_schema_invariants()` 函数，在 `init_db()` 完成后调用：

验证项目：
- `sessions` 表 PRIMARY KEY 列顺序为 `(agent_type, id)`
- `session_items` 表存在 `UNIQUE (agent_type, session_id, seq)` 约束
- `ix_session_items_ctx` 索引（`agent_type, session_id, archived, seq`）存在
- `session_todos` 表 PRIMARY KEY 为 `(agent_type, session_id)`

验证方式：查询 `sqlite_master` 的 `sql` 字段做字符串匹配。验证失败时抛出 `RuntimeError`，让服务启动失败而非静默运行在错误 schema 上。

---

## Commit 组 2：Logic 层修复

### 2.1 turn_id 生成（ULID）

**问题**：`turn_id / provider_call_index / block_index` 在 `base_agent.py` 写入时全部缺失（NULL），导致 `session_context.py` 的 group 逻辑退化为全部 singleton，OpenAI 多工具调用无法合并，timeline 重放和调试能力失效。

**turn 定义**：一次 `_stream_inner()` 调用 = 一个 turn。从用户消息写入开始，到 `TurnDone` 事件结束。

**选型**：`turn_id` 使用 ULID（`python-ulid` 库）。ULID 前 10 字符为毫秒级时间戳编码，字符串排序等于时间排序，无需额外 DB 状态，满足可排查性需求。

新增依赖：`pyproject.toml` 加 `python-ulid>=3.0`。

**实现**：

**Step 1**：`stream_events.py` 新增事件类型：

```python
@dataclass
class ProviderCallStart:
    index: int  # 等于 agent_loop 的 iteration 值
```

**Step 2**：`agent_loop.py` 每次外层 for 循环开头 yield：

```python
for iteration in range(MAX_ITERATIONS):
    yield ProviderCallStart(index=iteration)
    async for event in self._provider.stream(...):
        ...
```

**Step 3**：`base_agent._stream_inner()` 处理：

```python
from ulid import ULID

turn_id = str(ULID())   # 在 _stream_inner 开头生成一次
current_pci = 0         # 当前 provider_call_index
block_index = 0         # 当前 provider call 内的 block 位置

# 事件处理中：
if isinstance(event, ProviderCallStart):
    current_pci = event.index
    block_index = 0
    continue  # 不写 DB，不 SSE

if isinstance(event, ThinkingBlockStop):
    block = {
        "type": "thinking", ...,
        "turn_id": turn_id,
        "provider_call_index": current_pci,
        "block_index": block_index,
    }
    block_index += 1
    assistant_blocks.append(block)

if isinstance(event, TextBlockStop):
    assistant_blocks.append({
        "type": "text", ...,
        "turn_id": turn_id,
        "provider_call_index": current_pci,
        "block_index": block_index,
    })
    block_index += 1

if isinstance(event, ToolCallReady):
    record = {
        "type": "tool", ...,
        "turn_id": turn_id,
        "provider_call_index": current_pci,
        "block_index": block_index,
    }
    block_index += 1
    assistant_blocks.append(record)
```

`_message_to_items()` 在将 block dict 转为 `TimelineItemInput` 时，把 `turn_id / provider_call_index / block_index` 从 block dict 透传到 item。

### 2.2 cancel_session assistant_blocks 丢失修复

**问题**：`assistant_blocks` 是 `_stream_inner` 的局部变量。`cancel_session()` 触发取消时，`run_streaming` 的 `finally` 块只 flush `_partial_buffer`（文本），`assistant_blocks` 随协程销毁，thinking block 和 tool_call records 永久丢失。

**修复**：仿照 `_partial_buffer` 模式，在 `BaseAgent` 上增加：

```python
self._pending_blocks: dict[str, list[dict[str, Any]]] = {}
```

`_stream_inner` 每次追加 block 时同步更新（共享同一 list 引用）：

```python
assistant_blocks.append(block)
self._pending_blocks[session_id] = assistant_blocks
```

`TurnDone` 正常完成时清除：

```python
self._pending_blocks.pop(session_id, None)
await self._session_store.append_message(...)  # 正常写入路径不变
```

`run_streaming` 的 `finally` 块统一 flush：

```python
pending_blocks = self._pending_blocks.pop(session_id, [])
partial = self._partial_buffer.pop(session_id, "")
if partial or pending_blocks:
    await self._session_store.append_message(
        session_id, "assistant", partial,
        agent_type=agent_context,
        blocks=pending_blocks if pending_blocks else None,
    )
```

外部取消路径（`_stream_inner` 的 `except CancelledError`，`session_id not in _cancel_requested` 分支）同样使用 `_pending_blocks.pop()` 替代局部 `assistant_blocks`，并在写入后清除，避免与 `finally` 块重复写。

### 2.3 OpenAI 投影双 assistant 消息修复

**问题**：`session_context.py` 的 `_build_openai()` 在同一 group 同时含 `tool_calls_items` 和 `text_items` 时，先输出一条 `role=assistant, tool_calls=[...]` 消息（第 285-306 行），再在第 322-325 行追加一条 `role=assistant, content=text` 独立消息，产生两条连续 assistant 消息，OpenAI API 报 400。

**修复**：当 group 同时含 tool_calls 和文本时，将文本合并入同一条 assistant 消息的 `content` 字段：

```python
if tool_calls_items:
    text = " ".join(i.get("content", "") for i in text_items).strip() or None
    msgs.append({
        "role": "assistant",
        "content": text,        # 合并，OpenAI 允许 content 非 null 同时有 tool_calls
        "tool_calls": [...],
    })
    # 删除末尾独立 text 消息的追加逻辑
elif text_items:
    ...
```

### 2.4 IntegrityError 重试

**问题**：`_append_items_locked()` 对 `UNIQUE(agent_type, session_id, seq)` 冲突无捕获，消息被丢弃。

**修复**：捕获 `IntegrityError`，rollback（`async with db.begin()` 上下文自动处理），最多重试 3 次后抛出：

```python
for attempt in range(3):
    try:
        async with db.begin():
            ...  # 分配 seq + 插入
        return
    except IntegrityError:
        if attempt == 2:
            raise
        # 短暂等待后重试，下次 UPDATE...RETURNING 会读到正确的 next_item_seq
```

### 2.5 get_messages_since 排除 system_event

`session_timeline.py` 的 `_CONTEXT_EXCLUDED_KINDS` 集合加入 `"system_event"`：

```python
_CONTEXT_EXCLUDED_KINDS: frozenset[str] = frozenset({"thinking", "raw_block", "system_event"})
```

### 2.6 tool_use block content 修复

`_message_to_items()` 中 `block_content` 的取法对 `tool_use`/`tool` 类型改为序列化 `input` 字段：

```python
if block_type in ("tool_use", "tool"):
    block_content = json.dumps(block.get("input", {}), default=str)
else:
    block_content = block.get("text") or block.get("content") or ""
```

### 2.7 episodic_memory.py 清理

- 删除 `sebastian/memory/episodic_memory.py`
- `sebastian/memory/store.py` 移除对 `EpisodicMemory` 的 import 和 `.episodic` 字段
- 更新 `sebastian/memory/README.md`

---

## Commit 组 3：遗留清理

不影响功能正确性，但属于未完成的 spec 要求，统一在组 2 之后用一组独立 commit 清理。

### 3.1 get_timeline_items 排序修复

**问题**：`session_timeline.py` 的 `get_items()`（对应 `get_timeline_items`）第 254 行只按 `seq.asc()` 单列排序。上下文压缩后，`context_summary` 的 `effective_seq` 等于被压缩范围起点（如 1），但 `seq` 是实际写入顺序（如 150）。按 `seq` 排序会把 summary 放到最末尾，用户在 App 里无法看出 summary 代表哪段历史。

**修复**：改为 `.order_by(effective_seq.asc(), seq.asc())`，与 `get_context_items` 和 `get_context_items_with_thinking` 保持一致。

### 3.2 include_kinds 参数删除

**问题**：`get_items_since()` 的 `include_kinds: list[str] | None` 参数意图作为白名单，但实现上与前置的 `kind.not_in(_CONTEXT_EXCLUDED_KINDS)` AND 叠加，导致无法通过 `include_kinds` 取回被 excluded 的 kind（如 `thinking`）——参数语义误导。当前代码库无任何调用方传入此参数。

**修复**：删除 `include_kinds` 参数。若未来需要包含 `thinking` 的查询路径，参照 `get_context_messages` 的做法，单独加 `include_thinking: bool = False` 参数，在为 True 时从 `excluded` 集合中移除 `"thinking"`，语义清晰不混淆。

### 3.3 IndexStore 类删除

**问题**：`sebastian/store/index_store.py` 保留完整 `IndexStore` 实现（含 `prune_orphans`），但已无任何运行时调用方。Spec 要求彻底删除 `prune_orphans` 并移除独立 `IndexStore` 概念。

**修复**：
- 删除 `sebastian/store/index_store.py`
- `sebastian/store/__init__.py` 移除相关 export
- 确认无测试仍在 import `IndexStore`（已有的相关测试文件应已在上一轮迁移中清理）

### 3.4 TodoStore 文件回退路径清理

**问题**：`TodoStore.__init__` 保留 `sessions_dir` 参数和文件读写逻辑作为降级路径。运行时 `gateway/app.py` 只传 `db_factory`，文件路径不会被触发，但代码仍然存在。

**修复**：
- 删除 `TodoStore` 中 `sessions_dir` 参数及所有文件读写分支
- `__init__` 只接受 `db_factory`，强制 SQLite 路径
- 更新相关测试

---

## 测试要求

**Commit 组 1 必须覆盖：**
- `sessions` 表 PK 列顺序为 `(agent_type, id)`（schema smoke test）
- `effective_seq` 写入非 NULL（普通 item 写入后 `effective_seq == seq`）
- `_verify_schema_invariants()` 对错误 schema 抛出 `RuntimeError`

**Commit 组 2 必须覆盖：**
- `turn_id` 为有效 ULID 格式，同一 turn 内所有 items 共享同一 `turn_id`
- 工具多轮调用后 `provider_call_index` 正确递增
- 同一 provider call 内多个 tool_call 的 `provider_call_index` 相同
- `cancel_session()` 后 DB 中存在已缓冲的 `assistant_blocks`（不丢失 thinking/tool records）
- OpenAI 投影：含 tool_calls+text 的 group 产生单条 assistant 消息
- `get_messages_since` 返回值不含 `system_event`（同时 `get_context_items` 也不含，因为修改的是共享常量 `_CONTEXT_EXCLUDED_KINDS`）
- IntegrityError 触发后重试成功，seq 不重复

**Commit 组 3 必须覆盖：**
- `get_timeline_items` 返回顺序：压缩场景下 `context_summary` 按 `effective_seq` 排在被压缩范围原位，而非末尾
- `get_items_since` 无 `include_kinds` 参数（调用方无感知，接口更简洁）
- `IndexStore` 无法被 import（模块已删除）
- `TodoStore` 构造不接受 `sessions_dir`，传入时抛 `TypeError`

---

## 备注

`_verify_schema_invariants()` 在检测到索引缺失时报错让服务无法启动，但**不会自动修复**缺失的索引。对于本地开发工具、无生产数据的场景，这个 trade-off 可接受——至少不会静默运行在错误 schema 上。如果未来需要自动修复，可在 `_apply_idempotent_indexes()` 中补 `CREATE INDEX IF NOT EXISTS` 覆盖 `session_items` 和 `sessions` 的所有显式索引。
