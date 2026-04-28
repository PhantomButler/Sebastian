# Attachment Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代码审查（2026-04-28）发现的五类问题：C2 Critical bug（`require_attachments` 缺失）、I1 测试缺失（orphaned attachment 路径）、I6 cleanup 小 bug、I4 可读性注释、以及 Android `refreshInputCapabilities` 失败路径测试缺失。

**Architecture:** 所有修改都是局部 bug/test/comment 修复，不改变现有架构。最重要的是 C2：`base_agent.run_streaming` 在 `attachment_store=None` 时调用 `get_context_messages` 缺少 `require_attachments=False`，会在测试环境或未注入 attachment_store 的实例中触发 `ValueError`。

**Tech Stack:** Python 3.12, pytest, Kotlin, JUnit 4, Mockito.

---

## Source Review

代码审查来源：对 `feat/attachments-design` 分支（commit `16a27dea` → `7c0953c2`）的全面 spec 合规性审查。

## File Structure

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `sebastian/core/base_agent.py` | Modify | 补传 `require_attachments=self._attachment_store is not None` |
| `sebastian/store/attachments.py` | Modify | 拆分 TTL 常量；tmp cleanup 改用 `st_ctime` |
| `tests/unit/core/test_base_agent.py` | Modify | 补充 C2 单元测试 |
| `tests/integration/test_gateway_attachments.py` | Modify | 补充 orphaned attachment 不可重用集成测试 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | Modify | 新会话上传失败路径补充注释 |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt` | Modify | refreshInputCapabilities 失败 fallback 测试（2个） |

---

## Task 1: [C2] base_agent.run_streaming 补传 require_attachments

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `tests/unit/core/test_base_agent.py`

**问题：** `run_streaming` 调用 `get_context_messages` 时没有传 `require_attachments`，默认值为 `True`。当 `_attachment_store is None`（如单元测试、未注入 agent 实例）且 timeline 中存在 `attachment` 条目时，会抛 `ValueError: attachment_store is required`，导致整个 turn 失败。

`session_context.py` 中 `build_context_messages` 的语义是：`require_attachments=False` → attachment item 被静默跳过；`require_attachments=True`（默认）→ store 为 None 时抛异常。正常 agent 路径在 `attachment_store is None` 时应当 gracefully 跳过附件 items，而不是崩溃。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/core/test_base_agent.py` 末尾追加（保持已有的 `@pytest.mark.asyncio` 风格）：

```python
@pytest.mark.asyncio
async def test_run_streaming_require_attachments_false_when_store_none(
    tmp_path: Path,
) -> None:
    """run_streaming must call get_context_messages with require_attachments=False when attachment_store is None."""
    from unittest.mock import MagicMock

    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(
        Session(id="req-att-test", agent_type="sebastian", title="t")
    )

    # db_factory non-None → get_context_messages branch is taken; attachment_store=None (default)
    agent = TestAgent(MagicMock(), store, db_factory=MagicMock())

    captured_kwargs: dict = {}

    async def spy_get_context_messages(session_id, agent_ctx, provider_format, **kwargs):
        captured_kwargs.update(kwargs)
        return []

    agent._session_store.get_context_messages = spy_get_context_messages  # type: ignore[method-assign]

    try:
        await agent.run_streaming("hello", "req-att-test")
    except Exception:
        pass  # no LLM wired — expected

    assert captured_kwargs, "get_context_messages must have been called"
    assert captured_kwargs.get("attachment_store") is None
    assert captured_kwargs.get("require_attachments") is False, (
        f"require_attachments must be False when attachment_store is None; "
        f"got: {captured_kwargs.get('require_attachments')!r}"
    )
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/core/test_base_agent.py::test_run_streaming_require_attachments_false_when_store_none -v
```

Expected: FAIL — `require_attachments` 值为默认的 `True`，而不是 `False`。

- [ ] **Step 3: 修复 base_agent.py**

`sebastian/core/base_agent.py` 定位到 `get_context_messages` 调用处（约第 417-420 行），补加一行参数：

```python
        if self._db_factory is not None:
            messages = await self._session_store.get_context_messages(
                session_id, agent_context, provider_format,
                attachment_store=self._attachment_store,
                require_attachments=self._attachment_store is not None,
            )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/core/test_base_agent.py::test_run_streaming_require_attachments_false_when_store_none -v
```

Expected: PASS。

- [ ] **Step 5: 全量 base_agent 单元测试回归**

```bash
pytest tests/unit/core/test_base_agent.py -v
```

Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/core/test_base_agent.py
git commit -m "fix(core): run_streaming 补传 require_attachments=False 当 attachment_store 为 None"
```

---

## Task 2: [I1] 集成测试：orphaned attachment 不可重用

**Files:**
- Modify: `tests/integration/test_gateway_attachments.py`

**问题：** `validate_attachable` 对 `status=orphaned` 的 attachment 会抛 `AttachmentValidationError` → 409，但缺少端到端测试验证这条路径：upload → 绑定 → 删除 session（触发 orphan）→ 重用 attachment → 应 409。

- [ ] **Step 1: 写集成测试**

在 `tests/integration/test_gateway_attachments.py` 末尾追加（与既有 `test_send_turn_already_attached_attachment_rejected` 位置相邻）：

```python
def test_orphaned_attachment_cannot_be_reused_in_new_turn(client) -> None:
    """After a session is deleted (orphaning its attachment), reusing the attachment must return 409."""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: upload a text file
    att_id = _upload_text_file(http_client, token)

    # Step 2: attach it to a session by sending a turn (LLM call is mocked)
    with patch("sebastian.gateway.state.sebastian.run_streaming", new_callable=AsyncMock):
        turn_resp = http_client.post(
            "/api/v1/turns",
            json={"content": "check this file", "attachment_ids": [att_id]},
            headers=headers,
        )
    assert turn_resp.status_code == 200, turn_resp.text
    session_id = turn_resp.json()["session_id"]

    # Step 3: delete the session — backend calls mark_session_orphaned → attachment.status="orphaned"
    del_resp = http_client.delete(
        f"/api/v1/sessions/{session_id}",
        headers=headers,
    )
    assert del_resp.status_code == 200, del_resp.text

    # Step 4: try to reuse the same attachment_id in a new turn — must be rejected
    resp = http_client.post(
        "/api/v1/turns",
        json={"content": "reuse orphaned", "attachment_ids": [att_id]},
        headers=headers,
    )
    assert resp.status_code == 409, (
        f"Expected 409 for orphaned attachment, got {resp.status_code}: {resp.text}"
    )
```

- [ ] **Step 2: 运行测试确认通过**

```bash
pytest tests/integration/test_gateway_attachments.py::test_orphaned_attachment_cannot_be_reused_in_new_turn -v
```

Expected: PASS（现有 `validate_attachable` 对 `status != 'uploaded'` 已抛 `AttachmentValidationError` → 409）。

如果 FAIL，说明 `mark_session_orphaned` 或 `validate_attachable` 有 bug，需要先排查。

- [ ] **Step 3: 全量附件集成测试回归**

```bash
pytest tests/integration/test_gateway_attachments.py -v
```

Expected: 全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_gateway_attachments.py
git commit -m "test(gateway): 补充 orphaned attachment 不可重用集成测试"
```

---

## Task 3: [I6] cleanup TTL 常量拆分 + tmp 改用 st_ctime

**Files:**
- Modify: `sebastian/store/attachments.py`

**问题 1：** `_ORPHAN_TTL` 同时用于 `uploaded`（按 `created_at` 过期）和 `orphaned`（按 `orphaned_at` 过期）两类清理，语义不清晰，未来调整任一窗口时容易出错。

**问题 2：** tmp 文件 cleanup 使用 `st_mtime`（最后修改时间）。Linux tmpfs 上 `mtime` 会被写操作更新；`st_ctime`（inode change time）在 Linux 上更接近文件创建时间，更适合用作"此文件存在多久了"的判断。

- [ ] **Step 1: 拆分常量**

`sebastian/store/attachments.py` 第 28-30 行，将：

```python
_ORPHAN_TTL = timedelta(hours=24)
```

改为：

```python
_UPLOADED_TTL = timedelta(hours=24)   # unattached uploads expire after 24 h
_ORPHAN_TTL = timedelta(hours=24)     # orphaned blobs expire (can differ from uploaded in future)
```

- [ ] **Step 2: 更新 cleanup 方法**

定位 `cleanup` 方法（约第 207 行），将：

```python
    async def cleanup(self, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)) - _ORPHAN_TTL
        async with self._db_factory() as session:
            result = await session.execute(
                select(AttachmentRecord).where(
                    (
                        (AttachmentRecord.status == "uploaded")
                        & (AttachmentRecord.created_at < cutoff)
                    )
                    | (
                        (AttachmentRecord.status == "orphaned")
                        & (AttachmentRecord.orphaned_at < cutoff)
                    )
                )
            )
```

改为：

```python
    async def cleanup(self, now: datetime | None = None) -> int:
        _now = now or datetime.now(UTC)
        uploaded_cutoff = _now - _UPLOADED_TTL
        orphan_cutoff = _now - _ORPHAN_TTL
        async with self._db_factory() as session:
            result = await session.execute(
                select(AttachmentRecord).where(
                    (
                        (AttachmentRecord.status == "uploaded")
                        & (AttachmentRecord.created_at < uploaded_cutoff)
                    )
                    | (
                        (AttachmentRecord.status == "orphaned")
                        & (AttachmentRecord.orphaned_at < orphan_cutoff)
                    )
                )
            )
```

- [ ] **Step 3: 将 tmp cleanup 改为 st_ctime**

在同一方法的 tmp 清理部分（约第 232-242 行），将：

```python
                        mtime = datetime.fromtimestamp(tmp_file.stat().st_mtime, UTC)
                        if mtime < cutoff:
```

改为：

```python
                        ctime = datetime.fromtimestamp(tmp_file.stat().st_ctime, UTC)
                        if ctime < uploaded_cutoff:
```

- [ ] **Step 4: 运行 cleanup 单元测试确认行为未回归**

```bash
pytest tests/unit/store/test_attachments.py -v
```

Expected: 全部 PASS（两个常量值相同，行为等价）。

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/attachments.py
git commit -m "fix(store): 拆分 cleanup TTL 常量，tmp 清理改用 st_ctime"
```

---

## Task 4: [I4] ChatViewModel 新会话上传失败路径补充注释

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`

**问题：** 新会话路径上传失败时，`_uiState` 清空了消息气泡和 `activeSessionId`，但没有清空 `pendingAttachments`（故意如此：`Failed` 条目保留供用户重试）。代码缺少注释，未来维护者可能误判为 bug。

- [ ] **Step 1: 补充注释**

在 `ChatViewModel.kt` 中找到 `if (uploadedAttachments == null)` 新会话失败路径（约第 391 行），在该 `if` 块的第一条注释之后、`cancelPendingTimeout()` 之前，插入一行：

```kotlin
                if (uploadedAttachments == null) {
                    // uploadPendingAttachments already set composerState=IDLE_READY and showed toast.
                    // Also clean up the provisional session state.
                    // Note: pendingAttachments is intentionally NOT cleared here — failed-upload
                    // entries retain AttachmentUploadState.Failed so the user can retry or remove them.
                    cancelPendingTimeout()
```

（将原有的两行注释保留，追加第三行 `// Note: pendingAttachments...`。）

- [ ] **Step 2: 编译确认**

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin
```

Expected: PASS（注释改动，无编译影响）。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt
git commit -m "docs(android): 新会话上传失败路径补充 pendingAttachments 保留意图注释"
```

---

## Task 5: Android refreshInputCapabilities 失败 fallback 测试

**Files:**
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt`

**问题：** 现有 Test 7/8 只覆盖 `getDefaultBinding()` / `getAgentBinding()` 成功路径。失败路径（网络错误、未配置 binding）由 `.getOrNull()` → `?: ModelInputCapabilities()` 提供默认值（`supportsImageInput=false, supportsTextFileInput=true`），但没有测试。

- [ ] **Step 1: 追加两个失败路径测试**

在 `ChatViewModelAttachmentTest.kt` 末尾（最后一个 `}` 之前）追加：

```kotlin
    // ── Test 9 ─────────────────────────────────────────────────────────────────

    @Test
    fun `refreshInputCapabilities falls back to defaults when getDefaultBinding fails`() = vmTest {
        whenever(settingsRepository.getDefaultBinding()).thenReturn(
            Result.failure(RuntimeException("network error")),
        )

        viewModel.refreshInputCapabilities(agentId = null)
        // runCurrent(): avoids infinite advanceUntilIdle loop from startDeltaFlusher
        dispatcher.scheduler.runCurrent()

        // Default ModelInputCapabilities: supportsImageInput=false, supportsTextFileInput=true
        assertFalse(
            "supportsImageInput must be false (default) on binding failure",
            viewModel.uiState.value.inputCapabilities.supportsImageInput,
        )
        assertTrue(
            "supportsTextFileInput must be true (default) on binding failure",
            viewModel.uiState.value.inputCapabilities.supportsTextFileInput,
        )
    }

    // ── Test 10 ────────────────────────────────────────────────────────────────

    @Test
    fun `refreshInputCapabilities falls back to defaults when getAgentBinding fails`() = vmTest {
        whenever(agentRepository.getAgentBinding("forge")).thenReturn(
            Result.failure(RuntimeException("agent not found")),
        )

        viewModel.refreshInputCapabilities(agentId = "forge")
        dispatcher.scheduler.runCurrent()

        assertFalse(
            "supportsImageInput must be false (default) on agent binding failure",
            viewModel.uiState.value.inputCapabilities.supportsImageInput,
        )
        assertTrue(
            "supportsTextFileInput must be true (default) on agent binding failure",
            viewModel.uiState.value.inputCapabilities.supportsTextFileInput,
        )
    }
```

- [ ] **Step 2: 运行 Android 单元测试确认通过**

```bash
cd ui/mobile-android
./gradlew test --tests "com.sebastian.android.viewmodel.ChatViewModelAttachmentTest"
```

Expected: PASS（现有实现 `getOrNull() ?: ModelInputCapabilities()` 已正确处理失败路径）。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt
git commit -m "test(android): refreshInputCapabilities 失败路径 fallback 测试"
```

---

## Final Verification

- [ ] 运行后端相关测试：

```bash
pytest tests/unit/core/test_base_agent.py tests/unit/store/test_attachments.py tests/integration/test_gateway_attachments.py -v
```

- [ ] 运行后端 lint：

```bash
ruff check sebastian/ tests/
```

- [ ] 运行 Android 测试和编译：

```bash
cd ui/mobile-android
./gradlew test
./gradlew :app:compileDebugKotlin
```

Expected: 全部 PASS，无新 lint 错误。
