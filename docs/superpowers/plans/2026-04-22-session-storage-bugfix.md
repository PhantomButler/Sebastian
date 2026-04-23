# Session Storage SQLite Bug Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 session storage SQLite 迁移中发现的 schema、turn_id、cancel flush、OpenAI 投影等问题，覆盖所有高/中优先级 bug 和遗留清理项。

**Architecture:** 三组 commit 顺序推进：(1) Schema 层——PK 顺序重建 + 启动验证；(2) Logic 层——turn_id/ULID、cancel flush、OpenAI 投影、system_event 过滤、IntegrityError 重试等；(3) 遗留清理——排序修复、IndexStore 删除、TodoStore 精简。每组 commit 后独立跑 pytest 通过再继续。

**Tech Stack:** Python 3.12+, SQLAlchemy async, aiosqlite, pytest-asyncio, python-ulid>=3.0（新增依赖）

---

## 文件变更总览

| 文件 | 操作 |
|------|------|
| `sebastian/store/models.py` | 修改：SessionRecord / SessionConsolidationRecord PK 列顺序 |
| `sebastian/store/database.py` | 修改：_apply_idempotent_migrations 加 PK 重建；新增 _verify_schema_invariants |
| `sebastian/store/session_timeline.py` | 修改：_message_to_items turn_id 透传；_CONTEXT_EXCLUDED_KINDS 加 system_event；IntegrityError 重试；get_items 排序；include_kinds 删除 |
| `sebastian/store/session_context.py` | 修改：_build_openai 双 assistant 消息修复 |
| `sebastian/core/stream_events.py` | 修改：新增 ProviderCallStart dataclass，加入 LLMStreamEvent |
| `sebastian/core/agent_loop.py` | 修改：每次 iteration 开头 yield ProviderCallStart |
| `sebastian/core/base_agent.py` | 修改：_stream_inner 加 ULID turn_id + _pending_blocks；finally 块 flush blocks |
| `sebastian/store/todo_store.py` | 修改：删除 sessions_dir 参数和文件路径分支 |
| `sebastian/store/index_store.py` | 删除 |
| `sebastian/memory/episodic_memory.py` | 删除 |
| `sebastian/memory/store.py` | 修改：移除 EpisodicMemory import 和 .episodic 字段 |
| `pyproject.toml` | 修改：新增 python-ulid>=3.0 |
| `tests/unit/store/test_session_schema.py` | 新建：PK 顺序、_verify_schema_invariants 测试 |
| `tests/unit/store/test_session_timeline.py` | 修改：补 turn_id/effective_seq/system_event/排序测试 |
| `tests/unit/store/test_session_context.py` | 修改：补 OpenAI 双消息修复测试 |
| `tests/unit/core/test_agent_loop.py` | 修改：补 ProviderCallStart 事件测试 |
| `tests/unit/core/test_base_agent_provider.py` | 修改：补 turn_id/pci/blocks cancel flush 测试 |
| `tests/unit/store/test_todo_store.py` | 修改：删除文件路径相关测试 |

---

## Task 1：ORM PK 列顺序修正

**Files:**
- Modify: `sebastian/store/models.py`

修正两处 ORM 主键声明顺序（SQLAlchemy 按声明顺序确定 PRIMARY KEY 列顺序）。

- [ ] **Step 1: 修改 SessionRecord 主键列顺序**

`sebastian/store/models.py` 第 270-271 行，将 `id` 和 `agent_type` 的声明顺序对调（`agent_type` 在前）：

```python
# 修改前（第 270-271 行）：
id: Mapped[str] = mapped_column(String, primary_key=True)
agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)

# 修改后：
agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)
id: Mapped[str] = mapped_column(String, primary_key=True)
```

- [ ] **Step 2: 修改 SessionConsolidationRecord 主键列顺序**

`sebastian/store/models.py` 第 245-246 行：

```python
# 修改前：
session_id: Mapped[str] = mapped_column(String, primary_key=True)
agent_type: Mapped[str] = mapped_column(String, primary_key=True)

# 修改后：
agent_type: Mapped[str] = mapped_column(String, primary_key=True)
session_id: Mapped[str] = mapped_column(String, primary_key=True)
```

---

## Task 2：database.py — PK 重建迁移 + Schema 启动验证

**Files:**
- Modify: `sebastian/store/database.py`
- Create: `tests/unit/store/test_session_schema.py`

- [ ] **Step 1: 写失败测试（PK 顺序检测）**

新建 `tests/unit/store/test_session_schema.py`：

```python
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def fresh_engine():
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sessions_pk_column_order(fresh_engine):
    """sessions 表 PRIMARY KEY 第一列必须是 agent_type。"""
    async with fresh_engine.begin() as conn:
        row = await conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'")
        )
        sql = (row.scalar() or "").lower()
    import re
    m = re.search(r'primary key\s*\(\s*"?(\w+)"?', sql)
    assert m is not None, "sessions 表无 PRIMARY KEY 子句"
    assert m.group(1) == "agent_type", (
        f"sessions PRIMARY KEY 首列应为 agent_type，实际为 {m.group(1)!r}\n{sql}"
    )


@pytest.mark.asyncio
async def test_session_consolidations_pk_column_order(fresh_engine):
    """session_consolidations 表 PRIMARY KEY 第一列必须是 agent_type。"""
    async with fresh_engine.begin() as conn:
        row = await conn.execute(
            text(
                "SELECT sql FROM sqlite_master"
                " WHERE type='table' AND name='session_consolidations'"
            )
        )
        sql = (row.scalar() or "").lower()
    import re
    m = re.search(r'primary key\s*\(\s*"?(\w+)"?', sql)
    assert m is not None
    assert m.group(1) == "agent_type", (
        f"session_consolidations PRIMARY KEY 首列应为 agent_type，实际为 {m.group(1)!r}"
    )


@pytest.mark.asyncio
async def test_verify_schema_invariants_passes_on_correct_schema(fresh_engine):
    """正确 schema 下 _verify_schema_invariants 不抛出。"""
    from sebastian.store.database import _verify_schema_invariants
    async with fresh_engine.begin() as conn:
        await _verify_schema_invariants(conn)  # must not raise


@pytest.mark.asyncio
async def test_verify_schema_invariants_detects_wrong_sessions_pk():
    """sessions 表 PK 顺序错误时 _verify_schema_invariants 抛出 RuntimeError。"""
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import _verify_schema_invariants
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # 手动建出 PK 顺序错误的 sessions 表
        await conn.exec_driver_sql(
            "CREATE TABLE sessions ("
            "  id TEXT NOT NULL,"
            "  agent_type TEXT NOT NULL,"
            "  title TEXT DEFAULT '',"
            "  PRIMARY KEY (id, agent_type)"
            ")"
        )
        with pytest.raises(RuntimeError, match="sessions"):
            await _verify_schema_invariants(conn)
    await engine.dispose()
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/unit/store/test_session_schema.py -v
```

预期：`test_verify_schema_invariants_passes_on_correct_schema` PASS（`_verify_schema_invariants` 尚未实现但函数不存在时会 ImportError），其余若 PK 顺序已被 Task 1 修正则会 PASS，`test_verify_schema_invariants_detects_wrong_sessions_pk` FAIL（函数未实现）。

- [ ] **Step 3: 在 database.py 新增 `_verify_schema_invariants` 和 PK 重建逻辑**

在 `sebastian/store/database.py` 顶部加 `import re`，然后在 `_apply_idempotent_indexes` 之后新增两个函数，并在 `_apply_idempotent_migrations` 末尾调用它们：

```python
import re  # 在文件顶部已有的 import 区加上
```

新增函数（加在 `_drop_obsolete_columns` 之后）：

```python
async def _rebuild_pk_if_needed(
    conn: Any,
    table: str,
    wrong_first_col: str,
) -> None:
    """若 table 的复合 PRIMARY KEY 第一列是 wrong_first_col，重建表修正顺序。

    通过 CREATE TABLE ... SELECT * FROM old 完成；调用前 Base.metadata 必须已更新。
    """
    from sebastian.store.models import Base  # 避免循环 import

    row = await conn.execute(
        text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
    )
    sql = (row.scalar() or "").lower()
    if not sql:
        return
    m = re.search(r'primary key\s*\(\s*"?(\w+)"?', sql)
    if not (m and m.group(1) == wrong_first_col):
        return

    logger.info("Rebuilding %s to fix PRIMARY KEY column order", table)
    tmp = f"__{table}_pk_rebuild_tmp"
    await conn.exec_driver_sql(f"ALTER TABLE {table} RENAME TO {tmp}")
    await conn.run_sync(
        lambda sync_conn: Base.metadata.tables[table].create(sync_conn)
    )
    await conn.exec_driver_sql(f"INSERT INTO {table} SELECT * FROM {tmp}")
    await conn.exec_driver_sql(f"DROP TABLE {tmp}")
    logger.info("Rebuilt %s with correct PRIMARY KEY", table)


async def _verify_schema_invariants(conn: Any) -> None:
    """启动时验证关键 schema 约束，违反时抛出 RuntimeError。

    失败说明数据库 schema 与代码预期不符，需要删库重建或运行迁移。
    """
    checks = [
        ("sessions", r'primary key\s*\(\s*"?(\w+)"?', "agent_type"),
        ("session_consolidations", r'primary key\s*\(\s*"?(\w+)"?', "agent_type"),
    ]
    for table, pattern, expected_first_col in checks:
        row = await conn.execute(
            text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        )
        sql = (row.scalar() or "").lower()
        if not sql:
            continue  # 表不存在，create_all 负责建立
        m = re.search(pattern, sql)
        if not m or m.group(1) != expected_first_col:
            actual = m.group(1) if m else "unknown"
            raise RuntimeError(
                f"Schema invariant violated: {table} PRIMARY KEY first column "
                f"should be '{expected_first_col}', got '{actual}'. "
                f"Delete the database and restart to rebuild with correct schema."
            )

    # session_items UNIQUE 约束检查
    row = await conn.execute(
        text(
            "SELECT sql FROM sqlite_master"
            " WHERE type='table' AND name='session_items'"
        )
    )
    si_sql = (row.scalar() or "").lower()
    if si_sql and "unique" not in si_sql:
        raise RuntimeError(
            "Schema invariant violated: session_items missing UNIQUE constraint. "
            "Delete the database and restart."
        )
```

在 `_apply_idempotent_migrations` 的 `await _apply_idempotent_indexes(conn)` 调用之前加入重建调用：

```python
    # PK 列顺序修复（幂等，仅在 PK 首列错误时重建）
    await _rebuild_pk_if_needed(conn, "sessions", wrong_first_col="id")
    await _rebuild_pk_if_needed(conn, "session_consolidations", wrong_first_col="session_id")

    await _apply_idempotent_indexes(conn)
    ...
```

在 `init_db` 中，`_apply_idempotent_migrations` 之后调用验证：

```python
async def init_db() -> None:
    from sebastian.store import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
        await _verify_schema_invariants(conn)   # ← 新增
    logger.info("Database initialized")
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
pytest tests/unit/store/test_session_schema.py -v
```

预期：4 个测试全部 PASS。

- [ ] **Step 5: 跑全量 store 单测确认无回归**

```bash
pytest tests/unit/store/ -q
```

预期：全部 PASS。

- [ ] **Step 6: Commit 组 1**

```bash
git add sebastian/store/models.py sebastian/store/database.py tests/unit/store/test_session_schema.py
git commit -m "fix(store): 修正 sessions/session_consolidations 复合主键列顺序并加启动验证

- SessionRecord 主键改为 (agent_type, id)
- SessionConsolidationRecord 主键改为 (agent_type, session_id)
- _apply_idempotent_migrations 加幂等重建逻辑（检测旧顺序后 rename+create+copy+drop）
- 新增 _verify_schema_invariants()，启动时校验关键约束，违反时报错拒绝启动

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3：ProviderCallStart 事件 + ULID 依赖

**Files:**
- Modify: `sebastian/core/stream_events.py`
- Modify: `sebastian/core/agent_loop.py`
- Modify: `pyproject.toml`
- Modify: `tests/unit/core/test_agent_loop.py`

- [ ] **Step 1: 写失败测试（ProviderCallStart 从 agent_loop yield 出来）**

读取 `tests/unit/core/test_agent_loop.py` 的现有 MockLLMProvider fixture，在文件末尾追加：

```python
@pytest.mark.asyncio
async def test_agent_loop_yields_provider_call_start():
    """AgentLoop 每次 provider call 前 yield ProviderCallStart(index=N)。"""
    from sebastian.core.agent_loop import AgentLoop
    from sebastian.core.stream_events import ProviderCallStart, TurnDone

    # 简单一轮，无工具
    provider = MockLLMProvider([
        TextBlockStart(block_id="b0_0"),
        TextDelta(block_id="b0_0", delta="hi"),
        TextBlockStop(block_id="b0_0", text="hi"),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

    loop = AgentLoop(provider=provider, gate=MagicMock(), model="test-model")
    events = []
    gen = loop.stream("sys", [{"role": "user", "content": "hello"}])
    try:
        while True:
            event = await gen.asend(None)
            events.append(event)
    except StopAsyncIteration:
        pass

    pcs = [e for e in events if isinstance(e, ProviderCallStart)]
    assert len(pcs) == 1, f"Expected 1 ProviderCallStart, got {len(pcs)}"
    assert pcs[0].index == 0
```

- [ ] **Step 2: 运行，确认失败（ImportError: ProviderCallStart）**

```bash
pytest tests/unit/core/test_agent_loop.py::test_agent_loop_yields_provider_call_start -v
```

预期：ImportError 或 AttributeError。

- [ ] **Step 3: 新增 ProviderCallStart dataclass 并加入 LLMStreamEvent**

`sebastian/core/stream_events.py`，在 `ProviderCallEnd` 前新增：

```python
@dataclass
class ProviderCallStart:
    index: int  # agent_loop 的 iteration 值，从 0 开始
```

同时更新 `LLMStreamEvent` 类型别名，在 `ProviderCallEnd` 前加入：

```python
LLMStreamEvent = (
    ThinkingBlockStart
    | ThinkingDelta
    | ThinkingBlockStop
    | TextBlockStart
    | TextDelta
    | TextBlockStop
    | ToolCallBlockStart
    | ToolCallReady
    | ToolResult
    | ProviderCallStart       # ← 新增
    | ProviderCallEnd
    | TurnDone
)
```

- [ ] **Step 4: agent_loop.py 每次 iteration 开头 yield ProviderCallStart**

`sebastian/core/agent_loop.py`，在文件顶部 import 区加：

```python
from sebastian.core.stream_events import (
    ...
    ProviderCallStart,   # 加入已有 import
    ...
)
```

在 `for iteration in range(MAX_ITERATIONS):` 循环体第一行加：

```python
for iteration in range(MAX_ITERATIONS):
    yield ProviderCallStart(index=iteration)   # ← 新增，在 assistant_blocks = [] 之前
    assistant_blocks: list[dict[str, Any]] = []
    ...
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/unit/core/test_agent_loop.py::test_agent_loop_yields_provider_call_start -v
```

预期：PASS。

- [ ] **Step 6: 新增 ULID 依赖**

`pyproject.toml` 的 `dependencies` 列表中，在 `"anthropic>=0.40",` 后加一行：

```toml
"python-ulid>=3.0",
```

安装依赖：

```bash
pip install -e ".[dev,memory]"
```

确认 `from ulid import ULID` 可以正常 import：

```bash
python -c "from ulid import ULID; print(str(ULID()))"
```

预期：打印一个 26 字符 ULID 字符串，如 `01JQKZ7F3E2XXXXXXXXXXXX`。

---

## Task 4：base_agent —— turn_id + provider_call_index + _pending_blocks

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `tests/unit/core/test_base_agent_provider.py`

- [ ] **Step 1: 写失败测试（turn_id 存在 + pci 正确递增 + cancel flush blocks）**

在 `tests/unit/core/test_base_agent_provider.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_stream_inner_sets_turn_id_and_pci():
    """_stream_inner 写入的 assistant items 应携带非空 turn_id 和正确的 provider_call_index。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import (
        ProviderCallEnd, ProviderCallStart,
        TextBlockStart, TextBlockStop, TextDelta,
        ToolCallBlockStart, ToolCallReady,
    )
    from sebastian.store.session_store import SessionStore
    from unittest.mock import AsyncMock, MagicMock, call

    # Two provider calls: first produces a tool_call, second produces text.
    provider = MockLLMProvider([
        # provider call 0
        ProviderCallStart(index=0),
        ToolCallBlockStart(block_id="b0_tc", tool_id="tc1", name="my_tool"),
        ToolCallReady(block_id="b0_tc", tool_id="tc1", name="my_tool", inputs={}),
        ProviderCallEnd(stop_reason="tool_use"),
        # provider call 1
        ProviderCallStart(index=1),
        TextBlockStart(block_id="b1_0"),
        TextDelta(block_id="b1_0", delta="done"),
        TextBlockStop(block_id="b1_0", text="done"),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "sys"

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()

    gate = MagicMock()
    gate.call = AsyncMock(return_value=MagicMock(ok=True, output="result", error=None, empty_hint=None))

    agent = TestAgent(gate=gate, session_store=session_store, provider=provider)
    await agent.run("hi", session_id="s1")

    # The TurnDone append_message call carries blocks with turn_id and pci
    calls = session_store.append_message.call_args_list
    # First call: user message (no blocks), second call: assistant (blocks)
    assistant_call = next(
        (c for c in calls if c.kwargs.get("blocks") or (len(c.args) > 2 and c.args[1] == "assistant")),
        None,
    )
    assert assistant_call is not None, "No assistant append_message call found"
    blocks = assistant_call.kwargs.get("blocks") or []
    turn_ids = {b.get("turn_id") for b in blocks if b.get("turn_id")}
    assert len(turn_ids) == 1, f"All blocks should share one turn_id, got: {turn_ids}"
    turn_id = next(iter(turn_ids))
    assert len(turn_id) == 26, f"ULID should be 26 chars, got: {turn_id!r}"

    pcis = [b.get("provider_call_index") for b in blocks]
    assert 0 in pcis, "tool_call block should have provider_call_index=0"
    assert 1 in pcis, "text block should have provider_call_index=1"


@pytest.mark.asyncio
async def test_cancel_session_flushes_pending_blocks():
    """cancel_session 后 finally 块应 flush 已缓冲的 assistant_blocks，不丢 thinking/tool blocks。"""
    import asyncio
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import (
        ProviderCallEnd, ProviderCallStart,
        ThinkingBlockStart, ThinkingBlockStop,
        TextBlockStart, TextDelta, TextBlockStop,
    )
    from sebastian.store.session_store import SessionStore
    from unittest.mock import AsyncMock, MagicMock

    # Thinking block 完成后模拟文本流（还没 TurnDone 就被 cancel）
    events_yielded = []
    cancel_event = asyncio.Event()

    async def slow_stream(*args, **kwargs):
        yield ProviderCallStart(index=0)
        yield ThinkingBlockStart(block_id="t0")
        yield ThinkingBlockStop(block_id="t0", thinking="some thought", signature="sig")
        events_yielded.append("thinking_done")
        cancel_event.set()           # 通知测试可以 cancel 了
        yield TextBlockStart(block_id="b0")
        yield TextDelta(block_id="b0", delta="par")
        await asyncio.sleep(10)      # 模拟长时间流
        yield TextBlockStop(block_id="b0", text="partial")
        yield ProviderCallEnd(stop_reason="end_turn")

    class SlowProvider:
        message_format = "anthropic"
        def stream(self, *a, **kw):
            return slow_stream()

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "sys"

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()

    agent = TestAgent(gate=MagicMock(), session_store=session_store, provider=SlowProvider())

    run_task = asyncio.create_task(agent.run("hi", session_id="s2"))
    await cancel_event.wait()
    await asyncio.sleep(0.05)   # let ThinkingBlockStop be processed
    agent.cancel_session("s2")
    try:
        await run_task
    except Exception:
        pass

    # After cancel, append_message should have been called for the thinking block
    calls = session_store.append_message.call_args_list
    block_calls = [c for c in calls if c.kwargs.get("blocks") or "assistant" in str(c)]
    assert len(block_calls) >= 1, "Expected at least one assistant flush with blocks after cancel"
    all_blocks = []
    for c in block_calls:
        all_blocks.extend(c.kwargs.get("blocks") or [])
    kinds = [b.get("type") or b.get("kind") for b in all_blocks]
    assert "thinking" in kinds, f"thinking block should be flushed on cancel, got: {kinds}"
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/core/test_base_agent_provider.py::test_stream_inner_sets_turn_id_and_pci tests/unit/core/test_base_agent_provider.py::test_cancel_session_flushes_pending_blocks -v
```

预期：两个测试 FAIL。

- [ ] **Step 3: 修改 base_agent.py —— 初始化 _pending_blocks**

在 `BaseAgent.__init__` 的 `self._partial_buffer: dict[str, str] = {}` 后加一行：

```python
self._pending_blocks: dict[str, list[dict[str, Any]]] = {}
```

- [ ] **Step 4: 修改 _stream_inner —— turn_id + pci + block_index + _pending_blocks 同步**

在 `_stream_inner` 函数顶部，`full_text = ""` 之前加：

```python
from ulid import ULID
turn_id = str(ULID())
current_pci: int = 0
block_index: int = 0
```

在 `while True:` 循环内，`event = await gen.asend(send_value)` 之后加对 `ProviderCallStart` 的处理（在所有其他 isinstance 检查之前）：

```python
from sebastian.core.stream_events import ProviderCallStart  # 顶部 import 区加

if isinstance(event, ProviderCallStart):
    current_pci = event.index
    block_index = 0
    continue
```

修改 `ThinkingBlockStop` 分支，给 `block` dict 加上 turn 元数据，并同步 `_pending_blocks`：

```python
if isinstance(event, ThinkingBlockStop):
    block: dict[str, Any] = {
        "type": "thinking",
        "thinking": event.thinking,
        "turn_id": turn_id,
        "provider_call_index": current_pci,
        "block_index": block_index,
    }
    block_index += 1
    if event.signature is not None:
        block["signature"] = event.signature
    if event.duration_ms is not None:
        block["duration_ms"] = event.duration_ms
    assistant_blocks.append(block)
    self._pending_blocks[session_id] = assistant_blocks
```

修改 `TextBlockStop` 分支：

```python
if isinstance(event, TextBlockStop):
    assistant_blocks.append({
        "type": "text",
        "text": event.text,
        "turn_id": turn_id,
        "provider_call_index": current_pci,
        "block_index": block_index,
    })
    block_index += 1
    self._pending_blocks[session_id] = assistant_blocks
```

修改 `ToolCallReady` 分支，在 `record` dict 里加字段，在 `assistant_blocks.append(record)` 后同步：

```python
record: dict[str, Any] = {
    "type": "tool",
    "tool_id": event.tool_id,
    "name": event.name,
    "input": json.dumps(event.inputs, default=str),
    "status": "failed",
    "turn_id": turn_id,
    "provider_call_index": current_pci,
    "block_index": block_index,
}
block_index += 1
assistant_blocks.append(record)
self._pending_blocks[session_id] = assistant_blocks
```

修改 `TurnDone` 分支，在 `append_message` 之前清理 `_pending_blocks`：

```python
if isinstance(event, TurnDone):
    self._pending_blocks.pop(session_id, None)   # ← 新增，防止 finally 重复 flush
    await self._session_store.append_message(
        session_id,
        "assistant",
        event.full_text,
        agent_type=agent_context,
        blocks=assistant_blocks if assistant_blocks else None,
    )
    ...
```

修改外部取消路径（`except asyncio.CancelledError` 块中 `if session_id not in self._cancel_requested:` 分支）：

```python
if session_id not in self._cancel_requested:
    pending_blocks = self._pending_blocks.pop(session_id, [])
    if full_text or pending_blocks:
        await self._session_store.append_message(
            session_id,
            "assistant",
            full_text,
            agent_type=agent_context,
            blocks=pending_blocks if pending_blocks else None,
        )
```

- [ ] **Step 5: 修改 run_streaming finally 块 —— flush pending_blocks**

在 `run_streaming` 的 `finally` 块中，`if was_cancelled:` 分支里：

将现有 partial flush 逻辑改为同时 flush blocks：

```python
if was_cancelled:
    assert cancel_intent is not None
    self._completed_cancel_intents[session_id] = cancel_intent
    pending_blocks = self._pending_blocks.pop(session_id, [])
    partial = self._partial_buffer.pop(session_id, "")
    if partial or pending_blocks:
        try:
            text_to_save = (
                f"{partial}\n\n[用户中断]" if cancel_intent == "cancel" else partial
            )
            await self._session_store.append_message(
                session_id,
                "assistant",
                text_to_save,
                agent_type=agent_context,
                blocks=pending_blocks if pending_blocks else None,
            )
        except Exception:
            logger.warning("Failed to flush partial text on cancel", exc_info=True)
    ...
else:
    self._pending_blocks.pop(session_id, None)   # ← 正常完成时也清理
    self._partial_buffer.pop(session_id, None)
```

- [ ] **Step 6: 运行测试，确认通过**

```bash
pytest tests/unit/core/test_base_agent_provider.py -v
```

预期：全部 PASS（含两个新测试）。

---

## Task 5：_message_to_items —— turn_id / pci / block_index 透传

**Files:**
- Modify: `sebastian/store/session_timeline.py`
- Modify: `tests/unit/store/test_session_timeline.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/store/test_session_timeline.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_append_message_preserves_turn_id_from_blocks(store, session_in_db):
    """append_message 传入带 turn_id 的 blocks 时，写入 DB 的 item 应保留 turn_id。"""
    blocks = [
        {
            "type": "thinking",
            "thinking": "thought",
            "turn_id": "01JQTEST00000000000000000A",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "type": "text",
            "text": "reply",
            "turn_id": "01JQTEST00000000000000000A",
            "provider_call_index": 0,
            "block_index": 1,
        },
    ]
    await store.append_message(
        session_in_db.id, "assistant", "reply",
        agent_type="sebastian", blocks=blocks,
    )
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    thinking = next(i for i in items if i["kind"] == "thinking")
    text = next(i for i in items if i["kind"] == "assistant_message")

    assert thinking["turn_id"] == "01JQTEST00000000000000000A"
    assert thinking["provider_call_index"] == 0
    assert thinking["block_index"] == 0
    assert text["turn_id"] == "01JQTEST00000000000000000A"
    assert text["block_index"] == 1


@pytest.mark.asyncio
async def test_append_message_tool_use_block_content_is_json_input(store, session_in_db):
    """tool_use block 的 content 字段应为 JSON 序列化的 input，不为空。"""
    blocks = [
        {
            "type": "tool_use",
            "tool_id": "tc1",
            "name": "my_tool",
            "input": {"key": "value"},
            "turn_id": "01JQTEST00000000000000000B",
            "provider_call_index": 0,
            "block_index": 0,
        }
    ]
    await store.append_message(
        session_in_db.id, "assistant", "",
        agent_type="sebastian", blocks=blocks,
    )
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    tool_call = next(i for i in items if i["kind"] == "tool_call")
    import json
    assert tool_call["content"] == json.dumps({"key": "value"})
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/store/test_session_timeline.py::test_append_message_preserves_turn_id_from_blocks tests/unit/store/test_session_timeline.py::test_append_message_tool_use_block_content_is_json_input -v
```

预期：两者 FAIL（turn_id 为 None，tool_call content 为空）。

- [ ] **Step 3: 修改 _message_to_items**

`sebastian/store/session_timeline.py` 的 `_message_to_items` 方法（当前第 170-194 行），将 `for idx, block in enumerate(blocks):` 循环体改为：

```python
import json as _json  # 在文件顶部已有的 import 区加

for idx, block in enumerate(blocks):
    block_type = block.get("type", "")
    kind = _BLOCK_TYPE_TO_KIND.get(block_type, "raw_block")

    # tool_use/tool block 的 content 是序列化的 input，不是 text/content
    if block_type in ("tool_use", "tool"):
        block_content = _json.dumps(block.get("input", {}), default=str)
    else:
        block_content = block.get("text") or block.get("content") or ""

    result.append({
        "kind": kind,
        "role": role,
        "content": block_content,
        # 优先使用 block dict 里的索引（base_agent 传入的），fallback 到 enumerate
        "turn_id": block.get("turn_id"),
        "provider_call_index": block.get("provider_call_index"),
        "block_index": block.get("block_index", idx),
        "payload": {
            k: v for k, v in block.items()
            if k not in ("text", "content", "turn_id", "provider_call_index", "block_index")
        },
    })
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/unit/store/test_session_timeline.py -v
```

预期：全部 PASS。

---

## Task 6：OpenAI 投影双 assistant 消息修复

**Files:**
- Modify: `sebastian/store/session_context.py`
- Modify: `tests/unit/store/test_session_context.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/store/test_session_context.py` 末尾追加：

```python
def test_openai_mixed_tool_and_text_single_assistant_message():
    """同一 group 含 tool_calls 和文本时，OpenAI 投影只产生一条 assistant 消息。"""
    from sebastian.store.session_context import build_context_messages

    items = [
        {
            "kind": "assistant_message", "role": "assistant",
            "content": "I'll use the tool.",
            "turn_id": "t1", "provider_call_index": 0, "block_index": 0,
            "seq": 1, "effective_seq": 1, "archived": False,
            "payload": {},
        },
        {
            "kind": "tool_call", "role": "assistant",
            "content": '{"q": "weather"}',
            "turn_id": "t1", "provider_call_index": 0, "block_index": 1,
            "seq": 2, "effective_seq": 2, "archived": False,
            "payload": {
                "tool_call_id": "tc1",
                "tool_name": "search",
                "input": {"q": "weather"},
            },
        },
    ]
    messages = build_context_messages(items, provider_format="openai")

    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1, (
        f"Expected 1 assistant message, got {len(assistant_msgs)}: {assistant_msgs}"
    )
    msg = assistant_msgs[0]
    assert msg.get("tool_calls"), "Should have tool_calls"
    assert msg.get("content") == "I'll use the tool.", "Text should be in content field"
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/store/test_session_context.py::test_openai_mixed_tool_and_text_single_assistant_message -v
```

预期：FAIL（产生了两条 assistant 消息）。

- [ ] **Step 3: 修改 _build_openai**

`sebastian/store/session_context.py` 中 `_build_openai` 函数的 assistant-side group 处理段（约第 284-325 行）。

将现有逻辑替换为：

```python
# Emit assistant message(s)
if tool_calls_items:
    tool_calls = []
    for item in sorted(tool_calls_items, key=lambda i: (i.get("block_index") or 0)):
        payload = item.get("payload") or {}
        input_data = payload.get("input", {})
        tool_calls.append({
            "id": payload.get("tool_call_id", ""),
            "type": "function",
            "function": {
                "name": payload.get("tool_name", ""),
                "arguments": (
                    json.dumps(input_data)
                    if isinstance(input_data, dict)
                    else str(input_data)
                ),
            },
        })
    # 合并文本到同一条 assistant 消息（OpenAI 允许 content + tool_calls 共存）
    text_content = (
        " ".join(i.get("content", "") for i in text_items if i.get("content")).strip()
        or None
    )
    messages.append({
        "role": "assistant",
        "content": text_content,
        "tool_calls": tool_calls,
    })
elif text_items:
    content = " ".join(i.get("content", "") for i in text_items if i.get("content"))
    messages.append({"role": "assistant", "content": content})

# Emit tool results that appear in this group
for item in tool_result_items:
    payload = item.get("payload") or {}
    messages.append({
        "role": "tool",
        "tool_call_id": payload.get("tool_call_id", ""),
        "content": payload.get("model_content", item.get("content", "")),
    })

# 删除原来第 320-325 行的重复 text 追加逻辑（已合并到上方）
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/unit/store/test_session_context.py -v
```

预期：全部 PASS。

---

## Task 7：IntegrityError 重试 + system_event 过滤

**Files:**
- Modify: `sebastian/store/session_timeline.py`
- Modify: `tests/unit/store/test_session_timeline.py`

- [ ] **Step 1: 写失败测试（system_event 不进入 get_messages_since）**

在 `tests/unit/store/test_session_timeline.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_get_messages_since_excludes_system_event(store, session_in_db):
    """get_messages_since 不返回 system_event 类型。"""
    items = [
        {"kind": "user_message", "role": "user", "content": "hello"},
        {"kind": "system_event", "role": "system", "content": "session started"},
        {"kind": "assistant_message", "role": "assistant", "content": "hi"},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    since = await store.get_messages_since(session_in_db.id, "sebastian", after_seq=0)
    kinds = [i["kind"] for i in since]
    assert "system_event" not in kinds, f"system_event should be excluded, got: {kinds}"
    assert "user_message" in kinds
    assert "assistant_message" in kinds


@pytest.mark.asyncio
async def test_get_context_items_excludes_system_event(store, session_in_db):
    """get_context_timeline_items 不返回 system_event（影响 LLM context）。"""
    items = [
        {"kind": "user_message", "role": "user", "content": "hello"},
        {"kind": "system_event", "role": "system", "content": "started"},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    ctx = await store.get_context_timeline_items(session_in_db.id, "sebastian")
    kinds = [i["kind"] for i in ctx]
    assert "system_event" not in kinds, f"system_event should not be in context: {kinds}"
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/store/test_session_timeline.py::test_get_messages_since_excludes_system_event tests/unit/store/test_session_timeline.py::test_get_context_items_excludes_system_event -v
```

预期：两者 FAIL。

- [ ] **Step 3: 修改 _CONTEXT_EXCLUDED_KINDS**

`sebastian/store/session_timeline.py` 第 18 行：

```python
# 修改前：
_CONTEXT_EXCLUDED_KINDS = frozenset({"thinking", "raw_block"})

# 修改后：
_CONTEXT_EXCLUDED_KINDS = frozenset({"thinking", "raw_block", "system_event"})
```

- [ ] **Step 4: 修改 _append_items_locked 加 IntegrityError 重试**

`sebastian/store/session_timeline.py`，在文件顶部 import 区加：

```python
from sqlalchemy.exc import IntegrityError
```

将 `_append_items_locked` 方法重构为带重试：

```python
async def _append_items_locked(
    self,
    session_id: str,
    agent_type: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute within the per-session lock."""
    n = len(items)
    now = datetime.now(UTC)

    for attempt in range(3):
        try:
            async with self._db() as db:
                async with db.begin():
                    result = await db.execute(
                        text(
                            "UPDATE sessions SET next_item_seq = next_item_seq + :n"
                            " WHERE id = :sid AND agent_type = :at"
                            " RETURNING next_item_seq - :n"
                        ),
                        {"n": n, "sid": session_id, "at": agent_type},
                    )
                    row = result.first()
                    if row is None:
                        raise ValueError(
                            f"Session {session_id!r} (agent={agent_type!r}) not found"
                        )
                    start_seq: int = row[0]

                    inserted: list[dict[str, Any]] = []
                    for i, item in enumerate(items):
                        seq = start_seq + i
                        eff_seq = item.get("effective_seq") or seq
                        record = SessionItemRecord(
                            id=str(uuid4()),
                            session_id=session_id,
                            agent_type=agent_type,
                            seq=seq,
                            kind=item.get("kind", "raw_block"),
                            role=item.get("role"),
                            content=item.get("content", ""),
                            payload=item.get("payload", {}),
                            archived=item.get("archived", False),
                            turn_id=item.get("turn_id"),
                            provider_call_index=item.get("provider_call_index"),
                            block_index=item.get("block_index"),
                            effective_seq=eff_seq,
                            created_at=now,
                        )
                        db.add(record)
                        inserted.append(_record_to_dict(record))
            return inserted
        except IntegrityError:
            if attempt == 2:
                logger.error(
                    "seq IntegrityError after 3 attempts for session %s, giving up",
                    session_id,
                )
                raise
            logger.warning(
                "seq conflict on attempt %d for session %s, retrying",
                attempt + 1,
                session_id,
            )
    raise RuntimeError("unreachable")
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/unit/store/test_session_timeline.py -v
```

预期：全部 PASS。

---

## Task 8：episodic_memory.py 清理

**Files:**
- Delete: `sebastian/memory/episodic_memory.py`
- Modify: `sebastian/memory/store.py`

- [ ] **Step 1: 确认 episodic_memory.py 无活跃调用方**

```bash
grep -rn "episodic_memory\|EpisodicMemory\|\.episodic" sebastian/ --include="*.py" | grep -v "episodic_memory.py" | grep -v "memory/store.py"
```

预期：无输出（只有 `store.py` 自己引用）。

- [ ] **Step 2: 修改 memory/store.py 移除 EpisodicMemory**

读取 `sebastian/memory/store.py`，找到 `EpisodicMemory` 的 import 和 `.episodic` 字段，删除相关行。

```bash
grep -n "episodic\|EpisodicMemory" sebastian/memory/store.py
```

根据输出删除对应行（import 行 + `self.episodic = ...` 行 + `episodic: EpisodicMemory` 类型注解行）。

- [ ] **Step 3: 删除 episodic_memory.py**

```bash
git rm sebastian/memory/episodic_memory.py
```

- [ ] **Step 4: 跑 memory 相关测试**

```bash
pytest tests/unit/memory/ tests/unit/core/test_base_agent_memory.py -v
```

预期：全部 PASS。

- [ ] **Step 5: Commit 组 2**

```bash
git add sebastian/core/stream_events.py sebastian/core/agent_loop.py sebastian/core/base_agent.py \
    sebastian/store/session_timeline.py sebastian/store/session_context.py \
    sebastian/memory/store.py pyproject.toml \
    tests/unit/core/test_base_agent_provider.py tests/unit/core/test_agent_loop.py \
    tests/unit/store/test_session_timeline.py tests/unit/store/test_session_context.py
git commit -m "fix(core/store): turn_id/ULID、cancel flush、OpenAI投影、system_event过滤、IntegrityError重试

- stream_events.py 新增 ProviderCallStart 事件
- agent_loop.py 每次 iteration yield ProviderCallStart(index=N)
- base_agent._stream_inner 生成 ULID turn_id，按 ProviderCallStart 递增 pci/block_index
- _pending_blocks 模式确保 cancel 时 thinking/tool blocks 不丢失
- _message_to_items 透传 turn_id/provider_call_index/block_index；tool_use content 改为 json(input)
- _build_openai 修复含 tool_calls+text 的 group 产生两条 assistant 消息的 bug
- _CONTEXT_EXCLUDED_KINDS 加入 system_event（同时修复 get_context_items 和 get_messages_since）
- _append_items_locked 捕获 IntegrityError 并最多重试 3 次
- 删除 episodic_memory.py，memory/store.py 移除相关引用
- 新增 python-ulid>=3.0 依赖

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9：get_timeline_items 排序 + include_kinds 删除

**Files:**
- Modify: `sebastian/store/session_timeline.py`
- Modify: `tests/unit/store/test_session_timeline.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/store/test_session_timeline.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_get_timeline_items_orders_by_effective_seq_then_seq(store, session_in_db):
    """get_timeline_items 按 (effective_seq, seq) 排序，context_summary 出现在原位。"""
    # 写 5 条普通 item
    items = [{"kind": "user_message", "role": "user", "content": f"msg{i}"} for i in range(5)]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    # 取得 seq 1-5，插入一条 effective_seq=1 的 context_summary（seq 会是 6）
    summary: dict[str, Any] = {
        "kind": "context_summary",
        "role": None,
        "content": "summary",
        "effective_seq": 1,   # 显式传入，不走 fallback
        "payload": {"source_seq_start": 1, "source_seq_end": 3},
    }
    await store.append_timeline_items(session_in_db.id, "sebastian", [summary])

    all_items = await store.get_timeline_items(session_in_db.id, "sebastian")
    # context_summary 的 effective_seq=1，应排在最前
    assert all_items[0]["kind"] == "context_summary", (
        f"context_summary should be first (effective_seq=1), got: {[i['kind'] for i in all_items]}"
    )
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/store/test_session_timeline.py::test_get_timeline_items_orders_by_effective_seq_then_seq -v
```

预期：FAIL（context_summary 在末尾，不在开头）。

- [ ] **Step 3: 修改 get_items 排序**

`sebastian/store/session_timeline.py` 的 `get_items` 方法（第 254 行）：

```python
# 修改前：
q = q.order_by(SessionItemRecord.seq.asc())

# 修改后：
q = q.order_by(
    SessionItemRecord.effective_seq.asc(),
    SessionItemRecord.seq.asc(),
)
```

- [ ] **Step 4: 删除 include_kinds 参数**

`get_items_since` 方法签名去掉 `include_kinds` 参数，方法体删除对应的 `if include_kinds is not None:` 分支：

```python
# 修改前：
async def get_items_since(
    self,
    session_id: str,
    agent_type: str,
    after_seq: int,
    include_kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    ...
    if include_kinds is not None:
        q = q.where(SessionItemRecord.kind.in_(include_kinds))

# 修改后：
async def get_items_since(
    self,
    session_id: str,
    agent_type: str,
    after_seq: int,
) -> list[dict[str, Any]]:
    ...
    # include_kinds 参数已删除：如需 thinking 路径，使用独立方法
```

- [ ] **Step 5: 确认 SessionStore 的 get_messages_since 透传签名无需改动**

```bash
grep -n "get_items_since\|get_messages_since" sebastian/store/session_store.py | head -10
```

若 `session_store.py` 的 `get_messages_since` 对 `include_kinds` 有透传，一并删除。

- [ ] **Step 6: 运行测试，确认通过**

```bash
pytest tests/unit/store/test_session_timeline.py -v
```

预期：全部 PASS。

---

## Task 10：IndexStore 删除 + TodoStore 精简

**Files:**
- Delete: `sebastian/store/index_store.py`
- Modify: `sebastian/store/__init__.py`
- Modify: `sebastian/store/todo_store.py`
- Modify: `tests/unit/store/test_todo_store.py`

- [ ] **Step 1: 确认 IndexStore 无运行时调用**

```bash
grep -rn "IndexStore\|index_store" sebastian/ --include="*.py" | grep -v "index_store.py" | grep -v "__pycache__"
```

预期：无输出（或只有 tests/ 目录下的旧测试文件）。

- [ ] **Step 2: 删除 index_store.py**

```bash
git rm sebastian/store/index_store.py
```

- [ ] **Step 3: 清理 __init__.py**

```bash
grep -n "IndexStore\|index_store" sebastian/store/__init__.py
```

若有相关 export，删除对应行。

- [ ] **Step 4: 删除遗留 IndexStore 测试文件**

```bash
ls tests/unit/store/ | grep index
```

若存在 `test_index_store*.py` 等文件，已被旧迁移删除则跳过；否则：

```bash
git rm tests/unit/store/test_index_store*.py 2>/dev/null || true
```

- [ ] **Step 5: 修改 TodoStore 删除文件路径分支**

重写 `sebastian/store/todo_store.py`，移除 `sessions_dir` 参数和所有 `if self._db_todo is not None:` / `else:` 分支，只保留 SQLite 路径：

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from sebastian.core.types import TodoItem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TodoStore:
    """per-session todo 存储（SQLite-backed）。"""

    def __init__(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        from sebastian.store.session_todos import SessionTodoStore
        self._db_todo = SessionTodoStore(db_factory)

    async def read_updated_at(self, agent_type: str, session_id: str) -> str | None:
        dt = await self._db_todo.read_updated_at(agent_type, session_id)
        return dt.isoformat() if dt is not None else None

    async def read(self, agent_type: str, session_id: str) -> list[TodoItem]:
        return await self._db_todo.read(agent_type, session_id)

    async def write(
        self,
        agent_type: str,
        session_id: str,
        todos: list[TodoItem],
    ) -> None:
        await self._db_todo.write(agent_type, session_id, todos)
```

- [ ] **Step 6: 更新 test_todo_store.py**

```bash
grep -n "sessions_dir\|Path\|file" tests/unit/store/test_todo_store.py | head -20
```

删除依赖 `sessions_dir` 的测试用例，只保留 SQLite 路径测试。确认 `TodoStore(db_factory=...)` 正常构造；确认 `TodoStore(sessions_dir=...)` 抛 `TypeError`（无该参数）：

```python
def test_todo_store_requires_db_factory():
    """TodoStore 不再接受 sessions_dir 参数。"""
    from sebastian.store.todo_store import TodoStore
    import pytest
    with pytest.raises(TypeError):
        TodoStore(sessions_dir=Path("/tmp/foo"))  # type: ignore[call-arg]
```

- [ ] **Step 7: 跑全量测试**

```bash
pytest tests/unit/ -q
```

预期：全部 PASS。

- [ ] **Step 8: Commit 组 3**

```bash
git add sebastian/store/todo_store.py sebastian/store/__init__.py \
    tests/unit/store/test_session_timeline.py tests/unit/store/test_todo_store.py
git commit -m "chore(store): 遗留清理 — get_timeline_items 排序、include_kinds 删除、IndexStore 删除、TodoStore 精简

- get_items 改为按 (effective_seq, seq) 排序，与其他视图一致
- 删除 get_items_since 的 include_kinds 参数（无调用方，语义混乱）
- 删除 sebastian/store/index_store.py（已无运行时调用）
- TodoStore 移除 sessions_dir 参数和文件路径分支，强制 SQLite 路径

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 最终验证

- [ ] **全量单测**

```bash
pytest tests/unit/ -q
```

预期：全部 PASS，无 warning 关于 deprecated imports。

- [ ] **全量集成测试**

```bash
pytest tests/integration/ -q
```

预期：全部 PASS。

- [ ] **Lint 和类型检查**

```bash
ruff check sebastian/ tests/
ruff format --check sebastian/ tests/
mypy sebastian/
```

预期：无错误。
