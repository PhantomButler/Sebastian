# Attachment Dedup Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代码审查发现的 2 个 Important 问题和 2 个 Minor 问题，不改变现有行为。

**Architecture:** 纯防御性加固——在 `upload_bytes` 回滚路径加 try/except 防止异常掩盖；为 `_maybe_generate_thumbnail` 的进程级副作用加注释；补 1 个缺失测试用例；用 `blob_absolute_path()` 替换 cleanup 中的裸路径拼接；补测试断言。

**Tech Stack:** Python 3.12, pytest-asyncio, Pillow, SQLAlchemy async

---

## 文件改动清单

| 文件 | 改动 |
|---|---|
| `sebastian/store/attachments.py` | 1) `warnings.simplefilter` 加注释；2) `upload_bytes` 回滚路径加 try/except；3) `cleanup` 用 `blob_absolute_path()` |
| `tests/unit/store/test_attachments.py` | 1) 新增 `test_upload_bytes_db_failure_keeps_thumb_when_blob_dedup`；2) `test_cleanup_deletes_thumbnail_via_glob` 加 `deleted >= 1` 断言 |

---

## Task 1: 用 `warnings.catch_warnings()` 消除进程级副作用

**Files:**
- Modify: `sebastian/store/attachments.py:26-30`（模块顶部）
- Modify: `sebastian/store/attachments.py:74-76`（`_maybe_generate_thumbnail` 函数体）

背景：原实现在模块顶部调用 `warnings.simplefilter("error", Image.DecompressionBombWarning)`，这是进程全局操作——一旦模块被导入，整个进程任何地方触发 `DecompressionBombWarning` 都会变成 Error，影响范围远超缩略图生成逻辑。正确方案是用 `warnings.catch_warnings()` 把 filter 变更作用域限制在 `_maybe_generate_thumbnail` 调用期间，退出后自动还原，不污染进程全局状态。

- [ ] **Step 1: 修改模块顶部，移除 `warnings.simplefilter`**

将 `sebastian/store/attachments.py` 第 26-30 行：

```python
# DecompressionBomb 防护：Pillow 默认 MAX_IMAGE_PIXELS ≈ 89.5M（超过时仅发 Warning，
# > 2× 才抛 Error）。这里将上限设为 100M，并把 Warning 升级为 Error，
# 使单层阈值即触发硬阻断，而非依赖 Pillow 的双重阈值机制。
Image.MAX_IMAGE_PIXELS = 100_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)
```

替换为：

```python
# DecompressionBomb 防护：仅设置像素上限常量。
# DecompressionBombWarning → Error 的升级在 _maybe_generate_thumbnail 内部
# 用 warnings.catch_warnings() 作用域化处理，避免进程级副作用。
Image.MAX_IMAGE_PIXELS = 100_000_000
```

- [ ] **Step 2: 在 `_maybe_generate_thumbnail` 内部加 `warnings.catch_warnings()`**

将 `sebastian/store/attachments.py` 第 74-76 行（`_maybe_generate_thumbnail` 函数体开头）：

```python
    try:
        with Image.open(BytesIO(data)) as opened:
            opened.load()
```

替换为：

```python
    try:
        # catch_warnings 将 filter 变更限定在本次调用栈，退出后自动还原，
        # 不污染进程全局 filter list。asyncio 单线程下无线程安全问题。
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as opened:
                opened.load()
```

注意：`opened.load()` 之后的所有代码（format 判断、exif_transpose、thumbnail、save）需整体缩进一级，保持在 `with warnings.catch_warnings():` 块内。完整修改后的函数开头如下：

```python
def _maybe_generate_thumbnail(root_dir: Path, sha: str, data: bytes) -> tuple[Path | None, bool]:
    """对图片字节生成 256×256 缩略图，写到 thumbs/<sha[:2]>/<sha>.<ext>。
    ...
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as opened:
                opened.load()
                img: Image.Image = opened
                src_format = img.format or ""
                if src_format == "GIF":
                    img.seek(0)
                    ext: str = "png"
                    save_format = "PNG"
                else:
                    _ext = _THUMB_EXT_BY_FORMAT.get(src_format)
                    if _ext is None:
                        return None, False
                    ext = _ext
                    save_format = src_format

                thumb_rel = f"thumbs/{sha[:2]}/{sha}.{ext}"
                thumb_abs = root_dir / thumb_rel
                if thumb_abs.exists():
                    return thumb_abs, False

                img = ImageOps.exif_transpose(img)

                if save_format == "JPEG":
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                elif save_format == "PNG":
                    if img.mode == "P":
                        if "transparency" in img.info:
                            img = img.convert("RGBA")
                        else:
                            img = img.convert("RGB")
                elif save_format == "WEBP":
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGBA")

                img.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))

                thumb_abs.parent.mkdir(parents=True, exist_ok=True)
                (root_dir / "tmp").mkdir(parents=True, exist_ok=True)
                tmp_path = root_dir / "tmp" / str(uuid4())
                try:
                    save_kwargs: dict[str, Any] = {"format": save_format, "optimize": True}
                    if save_format == "JPEG":
                        save_kwargs["quality"] = JPEG_QUALITY
                    img.save(tmp_path, **save_kwargs)
                    os.replace(tmp_path, thumb_abs)
                    return thumb_abs, True
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    raise
    except Exception as exc:
        logger.warning("thumbnail generation skipped for sha=%s: %s", sha[:8], exc)
        return None, False
```

- [ ] **Step 3: 运行完整缩略图测试**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/unit/store/test_attachments.py -x -q -k "thumbnail or thumb"
```

预期：全部通过。

- [ ] **Step 4: 运行全套测试确认无回归**

```bash
pytest tests/unit/store/test_attachments.py -q
```

预期：全部通过，无 FAILED。

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/attachments.py
git commit -m "fix(store): DecompressionBombWarning 升级用 catch_warnings() 作用域化，消除进程级副作用

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 修复 `upload_bytes` 回滚路径的异常掩盖

**Files:**
- Modify: `sebastian/store/attachments.py:224-239`

背景：如果 DB commit 失败是因为数据库完全不可用（连接断开等），随后开 `session2` 做二次查询也会失败。这个次生异常会**替换**原始 commit 异常向上抛，掩盖根因。同时 blob/thumb 清理被静默跳过，没有任何日志，可能遗留孤儿文件。需要用 try/except 包住二次查询，失败时记 warning 并跳过 unlink（保守策略：不确定时不删）。

- [ ] **Step 1: 更新 `upload_bytes` 回滚段**

将 `sebastian/store/attachments.py` 第 224-239 行：

```python
        except Exception:
            # 二次查询：并发 upload 可能已用同 SHA 成功入库；只有当 DB 中
            # 完全没有该 SHA 的 record 时才能删本次新写入的文件。
            if created_blob or created_thumb:
                async with self._db_factory() as session2:
                    cnt = await session2.scalar(
                        select(func.count())
                        .select_from(AttachmentRecord)
                        .where(AttachmentRecord.sha256 == sha)
                    )
                if (cnt or 0) == 0:
                    if created_blob:
                        blob_abs.unlink(missing_ok=True)
                    if created_thumb and thumb_abs is not None:
                        thumb_abs.unlink(missing_ok=True)
            raise
```

替换为：

```python
        except Exception:
            # 二次查询：并发 upload 可能已用同 SHA 成功入库；只有当 DB 中
            # 完全没有该 SHA 的 record 时才能删本次新写入的文件。
            # 若二次查询本身也失败（DB 不可用），保守跳过 unlink 并记录 warning；
            # 孤儿文件留给下次 cleanup，不掩盖原始异常。
            if created_blob or created_thumb:
                try:
                    async with self._db_factory() as session2:
                        cnt = await session2.scalar(
                            select(func.count())
                            .select_from(AttachmentRecord)
                            .where(AttachmentRecord.sha256 == sha)
                        )
                except Exception as requery_exc:
                    logger.warning(
                        "upload rollback: re-query failed for sha=%s, skipping unlink: %s",
                        sha[:8],
                        requery_exc,
                    )
                else:
                    if (cnt or 0) == 0:
                        if created_blob:
                            blob_abs.unlink(missing_ok=True)
                        if created_thumb and thumb_abs is not None:
                            thumb_abs.unlink(missing_ok=True)
            raise
```

- [ ] **Step 2: 运行现有测试，确认无回归**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/unit/store/test_attachments.py -x -q -k "db_failure"
```

预期：3 个 db_failure 测试全部通过。

- [ ] **Step 3: Commit**

```bash
git add sebastian/store/attachments.py
git commit -m "fix(store): upload 回滚路径二次查询失败时记 warning 而非掩盖原始异常

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 新增缺失测试用例（`created_blob=False` + `created_thumb=True` + DB 失败）

**Files:**
- Modify: `tests/unit/store/test_attachments.py` — 在第 790 行（`test_upload_bytes_db_failure_keeps_blob_when_concurrent_record_exists` 之后）插入新测试

背景：现有测试覆盖了 `created_blob=True/False` 的路径，但没有覆盖 `created_blob=False` + `created_thumb=True` 的组合。场景：blob 已存在（dedup 命中，`created_blob=False`），thumb 被手动删除后本次重新生成（`created_thumb=True`），DB commit 失败，二次查询发现已有 record → thumb 应保留。

- [ ] **Step 1: 在 `tests/unit/store/test_attachments.py` 第 790 行之后插入新测试**

在 `assert blob_abs.exists()` 这行（第 789 行）之后的空行处插入：

```python
async def test_upload_bytes_db_failure_keeps_thumb_when_blob_dedup_and_other_record(
    attachment_store: AttachmentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """created_blob=False + created_thumb=True + DB 失败 + 其他 record 存在 → thumb 保留。

    场景：
    - 第一次上传成功：建立 blob + thumb + record（created_blob=True, created_thumb=True）
    - 手动删除 thumb，模拟 thumb 文件消失但 blob 和 record 仍在
    - 第二次上传相同内容：created_blob=False（blob dedup），created_thumb=True（重新生成）
    - DB commit 失败：二次查询发现已有第一次的 record → thumb 必须保留
    """
    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha
    thumb_abs = attachment_store._root_dir / "thumbs" / sha[:2] / f"{sha}.jpg"

    # 第一次上传成功（建立 blob + thumb + record）
    await attachment_store.upload_bytes(
        filename="first.jpg", content_type="image/jpeg", kind="image", data=data
    )
    assert blob_abs.exists()
    assert thumb_abs.exists()

    # 删掉 thumb，使第二次上传走 created_thumb=True 分支
    thumb_abs.unlink()
    assert not thumb_abs.exists()

    # 让第二次 upload 的 DB commit 失败
    real_factory = attachment_store._db_factory

    def _failing_factory():
        sess = real_factory()

        class _W:
            async def __aenter__(self):
                self._inner = await sess.__aenter__()

                async def _bad_commit():
                    raise RuntimeError("simulated commit failure")

                self._inner.commit = _bad_commit
                return self._inner

            async def __aexit__(self, *args):
                return await sess.__aexit__(*args)

        return _W()

    monkeypatch.setattr(attachment_store, "_db_factory", _failing_factory)

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await attachment_store.upload_bytes(
            filename="second.jpg", content_type="image/jpeg", kind="image", data=data
        )

    # 关键断言：created_blob=False, created_thumb=True, 但已有第一次的 record
    # 二次查询 count > 0 → thumb 不能删
    assert blob_abs.exists()
    assert thumb_abs.exists()
```

- [ ] **Step 2: 运行新测试，确认通过**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/unit/store/test_attachments.py::test_upload_bytes_db_failure_keeps_thumb_when_blob_dedup_and_other_record -v
```

预期：PASSED。

- [ ] **Step 3: 运行全部 db_failure 测试，确认无回归**

```bash
pytest tests/unit/store/test_attachments.py -x -q -k "db_failure"
```

预期：4 个测试全部通过。

- [ ] **Step 4: Commit**

```bash
git add tests/unit/store/test_attachments.py
git commit -m "test(store): 补 created_blob=False+created_thumb=True DB 失败时 thumb 保留测试

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Minor 修复——cleanup 用 `blob_absolute_path()` + 补 thumb 测试断言

**Files:**
- Modify: `sebastian/store/attachments.py:439`
- Modify: `tests/unit/store/test_attachments.py:864`

### 4a: cleanup 用 `blob_absolute_path()` 替换裸路径拼接

背景：`blob_absolute_path()` 内含路径遍历防护（`resolve()` + `is_relative_to()`），cleanup 中直接用 `self._root_dir / r.blob_path` 绕过了该防护。blob_path 由 SHA hex 生成，实践上不可能有遍历风险，但统一用 helper 更一致。

- [ ] **Step 1: 更新 cleanup 中的路径拼接**

将 `sebastian/store/attachments.py` 第 437-444 行：

```python
            for r in records:
                if remaining_count.get(r.sha256, 0) == 0 and r.sha256 not in seen_shas:
                    seen_shas.add(r.sha256)
                    pending_unlink.append((r.sha256, self._root_dir / r.blob_path))
                    thumb_dir = self._root_dir / "thumbs" / r.sha256[:2]
                    if thumb_dir.exists():
                        for thumb_path in thumb_dir.glob(f"{r.sha256}.*"):
                            pending_unlink.append((r.sha256, thumb_path))
                await session.delete(r)
                count += 1
```

替换为：

```python
            for r in records:
                if remaining_count.get(r.sha256, 0) == 0 and r.sha256 not in seen_shas:
                    seen_shas.add(r.sha256)
                    pending_unlink.append((r.sha256, self.blob_absolute_path(r)))
                    thumb_dir = self._root_dir / "thumbs" / r.sha256[:2]
                    if thumb_dir.exists():
                        for thumb_path in thumb_dir.glob(f"{r.sha256}.*"):
                            pending_unlink.append((r.sha256, thumb_path))
                await session.delete(r)
                count += 1
```

### 4b: 补 `test_cleanup_deletes_thumbnail_via_glob` 的返回值断言

- [ ] **Step 2: 在 `tests/unit/store/test_attachments.py` 第 864 行更新断言**

将：

```python
    await attachment_store.cleanup()
    assert not thumb_abs.exists()
```

替换为：

```python
    deleted = await attachment_store.cleanup()
    assert deleted >= 1
    assert not thumb_abs.exists()
```

- [ ] **Step 3: 运行相关测试**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/unit/store/test_attachments.py -x -q -k "cleanup"
```

预期：全部 cleanup 相关测试通过。

- [ ] **Step 4: 运行完整测试套件**

```bash
pytest tests/unit/store/test_attachments.py -q
```

预期：全部通过，无 FAILED。

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "fix(store): cleanup 用 blob_absolute_path()，补 thumb glob 测试返回值断言

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 最终验证

- [ ] **运行完整测试套件**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/ -q --tb=short
```

预期：无 FAILED，无新增 WARNING。

- [ ] **Lint 检查**

```bash
ruff check sebastian/store/attachments.py tests/unit/store/test_attachments.py
ruff format --check sebastian/store/attachments.py tests/unit/store/test_attachments.py
```

预期：无报错。
