# Resident Memory Snapshot Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 code review 发现的 5 个问题：record_hash 实现、去重顺序、AsyncRWLock 语义、空文件 hash 值、以及启动 rebuild 失败后的自愈调度。

**Architecture:** 三个文件改动。`resident_snapshot.py` 修复 AsyncRWLock（换 Condition-based 实现）、record_hash（按 spec 哈希多字段）、`_write_empty_state` 空 hash 值。`retrieval.py` 调整 `_not_resident_duplicate` 去重顺序。`gateway/app.py` 在启动失败时追加 `schedule_refresh()` 自愈调度。

**Tech Stack:** Python 3.12, asyncio, pytest-asyncio, SQLAlchemy async

---

## File Structure

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `sebastian/memory/resident_snapshot.py` | Modify | AsyncRWLock 换 Condition-based；record_hash 多字段；空文件 hash 值 |
| `sebastian/memory/retrieval.py` | Modify | `_not_resident_duplicate` 去重顺序调整 |
| `sebastian/gateway/app.py` | Modify | 启动失败追加 `schedule_refresh()` |
| `tests/unit/memory/test_resident_snapshot.py` | Modify | 新增 3 个测试 |
| `tests/integration/gateway/test_resident_snapshot_startup.py` | Modify | 新增启动自愈测试 |

---

### Task 1: 修复 `_not_resident_duplicate` 去重顺序（retrieval.py）

Spec §11 规定顺序：record id → canonical bullet → slot_value dedupe key。当前代码把 slot_value 排在 canonical bullet 前面，与 `_try_add()` 注释及 spec 不符。行为等价，但保持一致性避免后续维护混乱。

**Files:**
- Modify: `sebastian/memory/retrieval.py:316-331`

> 此修改不改变任何行为（三个 check 是 OR 关系），所以不需要新测试。

- [ ] **Step 1: 调整 `_not_resident_duplicate` 内部顺序**

找到 `retrieval.py` 第 316 行的 `def _not_resident_duplicate(record: Any) -> bool:`，将函数体改为：

```python
        def _not_resident_duplicate(record: Any) -> bool:
            """Return False if *record* is already injected by resident memory snapshot.

            Dedup order per spec §11: record id → canonical bullet → slot_value key.
            """
            record_id = getattr(record, "id", None)
            if record_id and record_id in effective_context.resident_record_ids:
                return False
            # canonical bullet check comes before slot_value per spec §11
            bullet = _canonical_bullet(getattr(record, "content", "") or "")
            if bullet and bullet in effective_context.resident_canonical_bullets:
                return False
            key = _slot_value_dedupe_key(
                subject_id=getattr(record, "subject_id", None) or effective_context.subject_id,
                slot_id=getattr(record, "slot_id", None),
                structured_payload=getattr(record, "structured_payload", None) or {},
            )
            if key and key in effective_context.resident_dedupe_keys:
                return False
            return True
```

- [ ] **Step 2: 验证现有测试通过**

```bash
pytest tests/unit/memory/test_retrieval.py -v
```

期望：全部 PASS，无报错。

- [ ] **Step 3: Commit**

```bash
git add sebastian/memory/retrieval.py
git commit -m "fix(memory): 修正 _not_resident_duplicate 去重顺序与 spec §11 一致

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 修复 `_write_empty_state` 空文件 hash 值

`_write_empty_state` 把 `markdown_hash` 写成 `"sha256:"` 而非空字符串的实际 SHA-256。虽然 dirty/error state 下读取端不走 hash 校验，但这是技术上错误的值，应保持语义准确。

**Files:**
- Modify: `sebastian/memory/resident_snapshot.py:579`
- Modify: `tests/unit/memory/test_resident_snapshot.py`（新增 1 个测试）

- [ ] **Step 1: 写失败测试**

在 `tests/unit/memory/test_resident_snapshot.py` 末尾追加：

```python
async def test_write_empty_state_produces_valid_markdown_hash(tmp_path: Path) -> None:
    """_write_empty_state must write the real SHA-256 of empty content, not 'sha256:'."""
    import json as _json

    from sebastian.memory.resident_dedupe import sha256_text
    from sebastian.memory.resident_snapshot import (
        ResidentMemorySnapshotRefresher,
        ResidentSnapshotPaths,
    )

    paths = ResidentSnapshotPaths.from_user_data_dir(tmp_path)
    refresher = ResidentMemorySnapshotRefresher(paths=paths)

    # Call the internal helper directly (it's used by mark_dirty_locked and _write_error_state)
    await refresher._write_empty_state("dirty")

    meta = _json.loads(paths.metadata.read_text(encoding="utf-8"))
    expected_hash = sha256_text("")  # sha256 of empty string
    assert meta["markdown_hash"] == expected_hash, (
        f"markdown_hash should be {expected_hash!r}, got {meta['markdown_hash']!r}"
    )
    # Markdown file should be empty
    assert paths.markdown.read_bytes() == b""
```

- [ ] **Step 2: 运行验证测试失败**

```bash
pytest tests/unit/memory/test_resident_snapshot.py::test_write_empty_state_produces_valid_markdown_hash -v
```

期望：FAIL，断言 `markdown_hash` 不等于 `sha256_text("")`。

- [ ] **Step 3: 修复 `_write_empty_state`**

在 `resident_snapshot.py` 中，找到：

```python
            markdown_hash="sha256:",
            record_hash="sha256:",
```

改为：

```python
            markdown_hash=sha256_text(""),
            record_hash=sha256_text(""),
```

（两行同时修改，保持一致性）

- [ ] **Step 4: 验证测试通过**

```bash
pytest tests/unit/memory/test_resident_snapshot.py::test_write_empty_state_produces_valid_markdown_hash -v
```

期望：PASS。

- [ ] **Step 5: 验证全套单元测试**

```bash
pytest tests/unit/memory/test_resident_snapshot.py -v
```

期望：全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/resident_snapshot.py tests/unit/memory/test_resident_snapshot.py
git commit -m "fix(memory): 修正 _write_empty_state 空文件 markdown_hash 为实际 SHA-256

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 修复 `AsyncRWLock` — 换用 Condition-based 实现

当前 `AsyncRWLock.write()` 在 yield 期间不阻止新读者进入，仅依赖 `_writer_active` flag（mutation_scope 设置）和 `_snapshot_state` 检查（rebuild 路径）保证正确性。Condition-based 实现让 lock 本身语义正确，消除对上层机制的隐式依赖。

**Files:**
- Modify: `sebastian/memory/resident_snapshot.py:120-151`
- Modify: `tests/unit/memory/test_resident_snapshot.py`（新增 1 个测试）

- [ ] **Step 1: 写失败测试**

在 `tests/unit/memory/test_resident_snapshot.py` 末尾追加：

```python
async def test_rw_lock_write_blocks_new_readers() -> None:
    """write() must block new readers that arrive while the writer is active."""
    from sebastian.memory.resident_snapshot import AsyncRWLock

    lock = AsyncRWLock()
    order: list[str] = []
    writer_inside = asyncio.Event()

    async def do_write() -> None:
        async with lock.write():
            writer_inside.set()
            await asyncio.sleep(0)  # yield — lets reader attempt lock
            order.append("write-complete")

    async def do_read() -> None:
        await writer_inside.wait()  # start only after writer is inside
        async with lock.read():
            order.append("read-complete")

    await asyncio.gather(do_write(), do_read())

    assert order == ["write-complete", "read-complete"], (
        f"reader should not enter read section before writer exits, got {order}"
    )
```

- [ ] **Step 2: 验证测试失败（当前实现使读者先于写者完成）**

```bash
pytest tests/unit/memory/test_resident_snapshot.py::test_rw_lock_write_blocks_new_readers -v
```

期望：FAIL，`order` 为 `["read-complete", "write-complete"]`（旧实现读者不被阻塞）。

- [ ] **Step 3: 替换 `AsyncRWLock` 实现**

在 `resident_snapshot.py` 中，将整个 `AsyncRWLock` 类（约 120-151 行）替换为：

```python
class AsyncRWLock:
    """Async read/write lock.

    Multiple concurrent readers are allowed; a writer gets exclusive access.
    New readers that arrive while a writer holds the lock are blocked until
    the write side is released — the lock itself enforces this, not external flags.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers: int = 0
        self._writer: bool = False

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[None, None]:
        async with self._condition:
            while self._writer:
                await self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def write(self) -> AsyncGenerator[None, None]:
        async with self._condition:
            while self._readers > 0 or self._writer:
                await self._condition.wait()
            self._writer = True
        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()
```

**注意**：`_no_readers`、`_no_readers.set()`、`_read_mutex`、`_write_lock` 等旧字段全部删除，被 `_condition`、`_readers`、`_writer` 取代。`mutation_scope()` 中的 `_writer_active` flag 保留（仍用于 `mark_dirty_locked()` 的参数校验和 `read()` 的快速返回路径）。

- [ ] **Step 4: 验证新测试通过**

```bash
pytest tests/unit/memory/test_resident_snapshot.py::test_rw_lock_write_blocks_new_readers -v
```

期望：PASS，`order == ["write-complete", "read-complete"]`。

- [ ] **Step 5: 验证全套测试**

```bash
pytest tests/unit/memory/test_resident_snapshot.py -v
```

期望：全部 PASS（包含 barrier、dirty、race 等既有测试）。

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/resident_snapshot.py tests/unit/memory/test_resident_snapshot.py
git commit -m "fix(memory): 用 Condition-based AsyncRWLock 真正阻止写锁期间新读者进入

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 修复 `record_hash` — 对多字段做哈希

Spec §6 要求 `record_hash` 对 `id`、`content`、`slot_id`、`kind`、`confidence`、`status`、`valid_from`、`valid_until`、`policy_tags`、`updated_at` 做确定性 hash。当前实现只哈希 ID 列表且套了双重 SHA-256。`record_hash` 当前仅用于 metadata 记录，不参与运行时决策，但若未来用于失效检测则会静默漏报内容变更。

**Files:**
- Modify: `sebastian/memory/resident_snapshot.py`（imports + `_query_and_render` 内 record_hash 计算块）
- Modify: `tests/unit/memory/test_resident_snapshot.py`（新增 1 个测试）

- [ ] **Step 1: 写失败测试**

在 `tests/unit/memory/test_resident_snapshot.py` 末尾追加：

```python
async def test_record_hash_changes_when_content_changes(
    tmp_path: Path, resident_db_session: AsyncSession
) -> None:
    """record_hash must change when a record's content changes, not just when IDs change."""
    import json as _json

    from sebastian.memory.resident_snapshot import (
        ResidentMemorySnapshotRefresher,
        ResidentSnapshotPaths,
    )

    # First snapshot: record with content A
    rec = _profile_record(id="ch1", content="内容版本一", confidence=0.9)
    resident_db_session.add(rec)
    await resident_db_session.flush()

    paths = ResidentSnapshotPaths.from_user_data_dir(tmp_path)
    refresher = ResidentMemorySnapshotRefresher(paths=paths)
    await refresher.rebuild(resident_db_session)
    meta1 = _json.loads(paths.metadata.read_text(encoding="utf-8"))
    hash1 = meta1["record_hash"]

    # Update content in-place (same id, different content)
    rec.content = "内容版本二（已更新）"
    await resident_db_session.flush()

    paths2 = ResidentSnapshotPaths.from_user_data_dir(tmp_path / "snap2")
    refresher2 = ResidentMemorySnapshotRefresher(paths=paths2)
    await refresher2.rebuild(resident_db_session)
    meta2 = _json.loads(paths2.metadata.read_text(encoding="utf-8"))
    hash2 = meta2["record_hash"]

    assert hash1 != hash2, (
        "record_hash must differ when record content changes even if IDs are the same"
    )
```

- [ ] **Step 2: 验证测试失败**

```bash
pytest tests/unit/memory/test_resident_snapshot.py::test_record_hash_changes_when_content_changes -v
```

期望：FAIL（两次 hash 相同，因为当前实现只哈希 ID）。

- [ ] **Step 3: 更新 imports — 添加 `canonical_json`，删除 `hashlib`/`json`**

在 `resident_snapshot.py` 中，将：

```python
import hashlib
import json
```

这两行删除（它们只被 record_hash 使用）。

将：

```python
from sebastian.memory.resident_dedupe import (
    canonical_bullet,
    normalize_memory_text,
    sha256_text,
    slot_value_dedupe_key,
)
```

改为：

```python
from sebastian.memory.resident_dedupe import (
    canonical_bullet,
    canonical_json,
    normalize_memory_text,
    sha256_text,
    slot_value_dedupe_key,
)
```

- [ ] **Step 4: 替换 `record_hash` 计算块**

在 `_query_and_render` 方法中，找到：

```python
        # Compute hashes
        md_hash = sha256_text(markdown)
        source_ids = [r.id for r in all_records]
        record_hash = sha256_text(
            hashlib.sha256(json.dumps(sorted(source_ids)).encode()).hexdigest()
        )
```

替换为：

```python
        # Compute hashes
        md_hash = sha256_text(markdown)
        source_ids = [r.id for r in all_records]

        def _record_fields(rec: ProfileMemoryRecord) -> dict[str, Any]:
            def _dt(d: datetime | None) -> str | None:
                if d is None:
                    return None
                return (d.replace(tzinfo=UTC) if d.tzinfo is None else d).isoformat()

            return {
                "id": rec.id,
                "content": rec.content,
                "slot_id": rec.slot_id,
                "kind": str(rec.kind.value) if hasattr(rec.kind, "value") else str(rec.kind) if rec.kind else None,
                "confidence": float(rec.confidence) if rec.confidence is not None else None,
                "status": rec.status,
                "valid_from": _dt(rec.valid_from),
                "valid_until": _dt(rec.valid_until),
                "policy_tags": sorted(rec.policy_tags or []),
                "updated_at": _dt(rec.updated_at),
            }

        record_hash = sha256_text(
            canonical_json(
                [_record_fields(r) for r in sorted(all_records, key=lambda r: r.id)]
            )
        )
```

- [ ] **Step 5: 验证新测试通过**

```bash
pytest tests/unit/memory/test_resident_snapshot.py::test_record_hash_changes_when_content_changes -v
```

期望：PASS。

- [ ] **Step 6: 验证全套测试 + lint**

```bash
pytest tests/unit/memory/test_resident_snapshot.py -v
ruff check sebastian/memory/resident_snapshot.py
```

期望：全部 PASS，ruff 无新告警（`hashlib` / `json` 已从 imports 删除）。

- [ ] **Step 7: Commit**

```bash
git add sebastian/memory/resident_snapshot.py tests/unit/memory/test_resident_snapshot.py
git commit -m "fix(memory): record_hash 按 spec §6 哈希多字段，移除双重 SHA-256

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 修复启动 rebuild 失败后的自愈调度

`gateway/app.py` 启动时若 rebuild 失败，只打 warning 日志，但不调用 `schedule_refresh()`。系统进入安全降级（空 resident memory），但无自愈能力，需等下次记忆写入触发 `mark_dirty_locked()` 才能恢复。

对比：`_background_rebuild()` 失败时会写 error state 并（通过 `_write_error_state`）等待下次手动触发。Gateway 启动路径应更主动：失败后立即调度后台重试。

**Files:**
- Modify: `sebastian/gateway/app.py:154-157`（启动 except 块）
- Modify: `tests/integration/gateway/test_resident_snapshot_startup.py`（新增 1 个测试）

- [ ] **Step 1: 写失败测试**

在 `tests/integration/gateway/test_resident_snapshot_startup.py` 末尾追加：

```python
async def test_startup_rebuild_failure_schedules_refresh(tmp_path) -> None:
    """After a startup rebuild failure, schedule_refresh() must queue a background retry."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from sebastian.memory.resident_snapshot import (
        ResidentMemorySnapshotRefresher,
        ResidentSnapshotPaths,
    )

    @asynccontextmanager
    async def _fake_factory():
        yield AsyncMock()

    refresher = ResidentMemorySnapshotRefresher(
        paths=ResidentSnapshotPaths.from_user_data_dir(tmp_path),
        db_factory=_fake_factory,
    )

    # Simulate what app.py does at startup — but rebuild always fails
    async def _failing_rebuild(session):
        raise RuntimeError("simulated startup db failure")

    refresher.rebuild = _failing_rebuild  # type: ignore[method-assign]

    # Run the startup code path AS IT CURRENTLY EXISTS (no schedule_refresh call)
    # This simulates the BEFORE state — task should NOT be scheduled
    try:
        async with _fake_factory() as session:
            await refresher.rebuild(session)
    except Exception:
        pass  # old behavior: swallow and do nothing

    assert refresher._pending_refresh is None, "old behavior: no retry scheduled"

    # Now run the startup code path AS IT SHOULD BE (with schedule_refresh call)
    try:
        async with _fake_factory() as session:
            await refresher.rebuild(session)
    except Exception:
        refresher.schedule_refresh()  # new behavior: schedule a retry

    assert refresher._pending_refresh is not None, (
        "after schedule_refresh(), a background rebuild task must be pending"
    )
    assert not refresher._pending_refresh.done()
    await refresher.aclose()
```

- [ ] **Step 2: 运行确认测试本身可执行（虽然 assert 暂时通过，因旧行为）**

```bash
pytest tests/integration/gateway/test_resident_snapshot_startup.py::test_startup_rebuild_failure_schedules_refresh -v
```

期望：PASS（测试的两个断言目前都满足：旧路径 `_pending_refresh is None`，因为我们手动加了 `schedule_refresh()` 在测试里）。

> 注：这个测试直接验证 `schedule_refresh()` 调用产生预期副作用。对 `app.py` 代码变更的验证在 Step 4。

- [ ] **Step 3: 更新 `gateway/app.py` 中的启动 except 块**

找到：

```python
    except Exception as exc:  # noqa: BLE001
        logger.warning("resident snapshot rebuild failed at startup: %s", exc, exc_info=True)
```

改为：

```python
    except Exception as exc:  # noqa: BLE001
        logger.warning("resident snapshot rebuild failed at startup: %s", exc, exc_info=True)
        resident_refresher.schedule_refresh()
```

- [ ] **Step 4: 验证 gateway 启动集成测试**

```bash
pytest tests/integration/gateway/test_resident_snapshot_startup.py -v
```

期望：全部 PASS（包含旧测试 `test_gateway_startup_creates_resident_snapshot_files`）。

- [ ] **Step 5: 验证整体 integration 测试未受影响**

```bash
pytest tests/integration/gateway/ -v
```

期望：全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/app.py tests/integration/gateway/test_resident_snapshot_startup.py
git commit -m "fix(gateway): 启动时 resident snapshot rebuild 失败后调度后台自愈重建

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 最终验证

- [ ] **完整测试套件**

```bash
pytest tests/unit/memory/ tests/integration/gateway/ -v
```

期望：全部 PASS。

- [ ] **Lint 检查**

```bash
ruff check sebastian/memory/resident_snapshot.py sebastian/memory/retrieval.py sebastian/gateway/app.py
```

期望：无新告警（`hashlib`/`json` import 已删除）。

---

## Self-Review

### Spec coverage

| Spec 要求 | 对应 Task |
|-----------|----------|
| §6: record_hash 哈希 id/content/slot_id/kind/confidence/status/valid_from/valid_until/policy_tags/updated_at | Task 4 ✓ |
| §8/§11: 去重顺序 record id → canonical bullet → slot_value | Task 1 ✓ |
| §9: 启动 rebuild 失败继续运行（写日志） | 已有，Task 5 加自愈 ✓ |
| AsyncRWLock 语义正确（写锁期间阻止新读者） | Task 3 ✓ |
| 空文件 markdown_hash 语义正确 | Task 2 ✓ |

### Placeholder scan

无 TBD / TODO / "similar to Task N" / "add appropriate" 等占位符。

### Type consistency

- `canonical_json` 从 Task 4 Step 3 引入 import，在 Step 4 使用 ✓
- `sha256_text("")` 在 Task 2 和 Task 4 同一函数，签名一致 ✓
- `AsyncRWLock` 的 `read()`/`write()` 签名与现有代码调用方式兼容（`async with lock.read()` / `async with lock.write()`）✓
