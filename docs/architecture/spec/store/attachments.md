---
version: "1.0"
last_updated: 2026-05-01
status: implemented
---

# Attachment Store：去重、引用计数清理、缩略图

*← [Store 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景

`AttachmentStore`（`sebastian/store/attachments.py`）已按 SHA-256 把 blob 写入内容寻址路径 `blobs/<sha[:2]>/<sha>`。本 spec 覆盖三个相互关联的改进：

1. **Blob 去重写入**：同内容多次上传跳过重复写文件。
2. **引用计数 cleanup**：多条 record 指向同一 blob 时，仅在最后一条 record 被清理时才物理删除文件。
3. **服务端缩略图**：图片上传时同步生成 256×256 缩略图，`/thumbnail` 端点优先返回缩略图。

接口层（REST API、timeline、Android 端）见 [mobile/attachments.md](../mobile/attachments.md)；Agent 发送文件流程见 [capabilities/agent-file-send.md](../capabilities/agent-file-send.md)。

---

## 2. 不变量

- `AttachmentRecord.id` 每次 `upload_bytes` 是新 UUID，跨次不复用。
- `AttachmentRecord.sha256` 与 `blob_path` 一一对应：`blob_path == f"blobs/{sha[:2]}/{sha}"`。
- **任何 DB-committed 的活跃 `AttachmentRecord` 都能通过 `blob_path` 找到磁盘文件**。由三层机制保证：
  - cleanup 的 "DB commit 后才 unlink 物理文件" 顺序
  - upload 回滚的 "二次查 SHA count == 0 才 unlink" 检查
  - cleanup 的 "unlink 前二次确认 SHA 仍无引用" 检查
- `kind == "image"` 的 record 的缩略图存在性**不是**不变量——可能因解码失败/DecompressionBomb/老数据而缺失，端点必须处理。

---

## 3. Blob 去重写入与回滚一致性

`upload_bytes` 写入与回滚段的两条核心约束：

1. 用 `created_blob` / `created_thumb` 标志位追踪本次调用是否**新写入**了内容寻址文件。
2. **回滚前必须二次查询同 SHA 引用计数**：并发场景下两次上传同 SHA 可能都看到 blob 不存在、各自 `os.replace` 到同一路径、各自 `created_blob=True`；若 A commit 成功、B commit 失败，B 回滚时若直接 unlink 会破坏 A 的 record。必须再查 count，`count == 0` 才允许删除。

```python
sha = hashlib.sha256(data).hexdigest()
blob_abs = self._root_dir / f"blobs/{sha[:2]}/{sha}"

created_blob = False
if not blob_abs.exists():
    # 写入 tmp/ 后原子 os.replace
    ...
    created_blob = True

created_thumb = False
thumb_abs: Path | None = None
if kind == "image":
    thumb_abs, created_thumb = _maybe_generate_thumbnail(self._root_dir, sha, data)

try:
    async with self._db_factory() as session:
        session.add(record)
        await session.commit()
except Exception:
    if created_blob or created_thumb:
        # 二次查询：并发 upload 可能已成功入库同 SHA record
        async with self._db_factory() as session2:
            cnt = await session2.scalar(
                select(func.count()).select_from(AttachmentRecord)
                .where(AttachmentRecord.sha256 == sha)
            )
        if (cnt or 0) == 0:
            if created_blob: blob_abs.unlink(missing_ok=True)
            if created_thumb and thumb_abs: thumb_abs.unlink(missing_ok=True)
    raise
```

> **实现增强**：二次查询失败（DB 不可用）时，代码保守跳过 unlink 并记录 warning，不掩盖原始异常。

---

## 4. 引用计数 cleanup

`cleanup` 三条核心约束：

1. **批内 SHA 一次性聚合**：避免同批两条同 SHA record 都认为对方还在而互相跳过 blob 删除。
2. **DB commit 成功后才 unlink 物理文件**：先删文件再 commit，commit 失败后 record 还在但 blob 已没，违反不变量。
3. **commit 后、unlink 前必须二次确认 SHA 仍无引用**：窗口内可能有新 upload 命中同 SHA，此时不能 unlink。

```python
# 1. 查出批外同 SHA record 数
remaining_rows = await session.execute(
    select(AttachmentRecord.sha256, func.count())
    .where(
        AttachmentRecord.sha256.in_(shas_in_batch),
        AttachmentRecord.id.notin_(batch_ids),
    )
    .group_by(AttachmentRecord.sha256)
)
remaining_count = {sha: cnt for sha, cnt in remaining_rows.all()}

# 2. 收集待 unlink 文件（按 sha glob thumb）
pending_unlink: list[tuple[str, Path]] = []
seen_shas: set[str] = set()
for r in records:
    if remaining_count.get(r.sha256, 0) == 0 and r.sha256 not in seen_shas:
        seen_shas.add(r.sha256)
        pending_unlink.append((r.sha256, blob_absolute_path(r)))
        thumb_dir = self._root_dir / "thumbs" / r.sha256[:2]
        if thumb_dir.exists():
            for p in thumb_dir.glob(f"{r.sha256}.*"):
                pending_unlink.append((r.sha256, p))
    await session.delete(r)

await session.commit()  # ← DB 必须先 commit

# 3. 二次确认：commit 后可能有新 upload 命中同 SHA
still_referenced = await self._check_still_referenced_shas(
    {sha for sha, _ in pending_unlink}
)
for sha, p in pending_unlink:
    if sha in still_referenced:
        continue
    try:
        p.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("cleanup unlink failed: %s: %s", p, exc)
```

设计要点：

- **按 sha256 查**：schema 已有 `ix_attachments_sha256` 索引，比 blob_path 查更高效。
- **不限 status**：blob 是否可删的判定是"是否存在任何 record 指向同 SHA"，不分 uploaded/attached/orphaned。
- **thumb 用 glob 取扩展名**：record 不存 thumb 扩展名，用 `glob(f"{sha}.*")` 收集所有候选（jpg/png/webp）。
- **`_check_still_referenced_shas` 开新 session**：避免与已 commit 的当前 session 状态混淆。

> **实现增强**：`seen_shas` set 保证同批多条同 SHA record 只加一次到 `pending_unlink`，避免重复 unlink 同一路径。`_check_still_referenced_shas` 抽取为独立方法，清理主流程更清晰。

---

## 5. 缩略图生成

**依赖**：`Pillow`（`pyproject.toml` 已加入）

**入口**：`_maybe_generate_thumbnail(root_dir, sha, data) -> tuple[Path | None, bool]`

- `Path | None`：thumb 绝对路径（None 表示未生成）
- `bool created`：`True` = 本次新写入；`False` = 已存在（dedup）或未生成

**生成参数**：最大边 256px（`img.thumbnail((256, 256))`），JPEG quality 85。

**路径**：`thumbs/<sha[:2]>/<sha>.<ext>`，按 SHA 内容寻址，同 blob 对称。

**格式映射**：

| 输入格式 | 输出格式 | ext |
|---------|---------|-----|
| JPEG | JPEG | jpg |
| PNG | PNG | png |
| WEBP | WebP | webp |
| GIF | PNG（取第一帧） | png |
| 其他 | 跳过 | — |

**关键处理**：

1. **DecompressionBomb 防护**：`Image.MAX_IMAGE_PIXELS = 100_000_000`（模块级）作为像素上限。用 `warnings.catch_warnings()` 作用域将 `DecompressionBombWarning` 升级为 Error，使 1 亿像素成为真正硬上限，退出后自动还原，不产生进程级副作用。

2. **EXIF orientation 校正**：`ImageOps.exif_transpose(img)` 在缩放前调用，防止手机照片缩略图方向错误。

3. **mode 转换**：
   - JPEG 输出强制 RGB
   - PNG 输出：P 模式带透明时转 RGBA
   - WebP 输出：非 RGB/RGBA 时转 RGBA
   - GIF：`seek(0)` 取第一帧后走 PNG 分支

4. **生成失败一律降级**：外层 `except Exception` 兜底（含 `MemoryError`/`RuntimeError` 等），upload 不因 thumb 失败而失败。`AttachmentRecord` 仍正常入库，下游靠端点 fallback。

5. **thumb 去重**：写入前 `if thumb_abs.exists(): return thumb_abs, False`，与 blob 去重对称。

---

## 6. 缩略图端点

`GET /api/v1/attachments/{id}/thumbnail`（`sebastian/gateway/routes/attachments.py`）：

1. 取 record，校验 `kind == "image"`。
2. 调用 `store.thumb_candidate_paths(record)` 按 SHA 推算候选路径（尝试 `jpg/png/webp` 三种扩展名）。
3. 命中文件 → 返回缩略图，`media_type` 用对应扩展名的 MIME。
4. 未命中（老数据/生成失败/解码超限）→ fallback 读取原 blob，使用 `record.mime_type`。
5. 原 blob 也不存在 → 404。

`thumb_candidate_paths` 方法：

```python
def thumb_candidate_paths(self, record: AttachmentRecord) -> list[tuple[Path, str]]:
    # 返回 [(path, mime), ...]，按 jpg/png/webp 顺序
    ...
```

---

## 7. 错误处理矩阵

| 场景 | 行为 |
|---|---|
| Pillow 解码失败 | upload 成功，跳过 thumb，warning 日志 |
| DecompressionBomb（> 1 亿像素） | warning 升级为 Error，外层捕获 → upload 成功，跳过 thumb |
| 其他 Pillow 异常（MemoryError 等） | 外层 `except Exception` 兜底，upload 成功，跳过 thumb |
| 同 SHA 并发上传（TOCTOU） | `os.replace` 原子互覆，最终一致，无锁 |
| upload DB commit 失败 + blob 复用 | 二次查 SHA count > 0，blob **保留** |
| upload DB commit 失败 + blob 新写入 + 无并发 | 二次查 SHA count == 0，blob **删除** |
| upload DB commit 失败 + 并发 upload 已 commit 同 SHA | 二次查 SHA count > 0，blob **保留** |
| cleanup DB commit 失败 | `pending_unlink` 不执行，blob/thumb 全部保留，下次重试 |
| cleanup commit 后窗口内有新 upload 同 SHA | 二次确认 SHA 仍被引用，跳过 unlink |
| cleanup unlink 物理文件失败 | warning 日志，DB 不回滚 |
| 老 record 无 thumb 文件 | 端点 fallback 返回原图 |
| 端点 thumb 与 blob 都不存在 | 404 |

---

## 8. 数据迁移

无需迁移。现有 record `blob_path` 不变；无 thumb 的老 record 通过端点 fallback 自动返回原图。

---

## 9. 测试覆盖

主要测试文件：

- `tests/unit/store/test_attachments.py`
- `tests/integration/test_gateway_attachments.py`

关键场景（单元）：

- 同内容二次上传：`os.replace` 未被调用（mock）
- upload DB commit 失败 + blob 已存在：blob 保留
- upload DB commit 失败 + blob 新写入 + 无并发：blob 删除
- upload DB commit 失败 + 并发已 commit：mock 二次查返回 count > 0，blob 保留
- cleanup：两条同 SHA 都过期 → blob 删除
- cleanup：一过期一活跃同 SHA → blob 保留
- cleanup DB commit 失败 → blob/thumb 文件未 unlink
- cleanup unlink 失败 → DB 状态正确，warning 被记录
- cleanup 窗口内并发 upload → 二次查识别引用，blob 保留
- 上传 JPEG/PNG/WebP/GIF：thumb 文件存在，格式正确，最大边 ≤ 256
- EXIF orientation：带 EXIF tag 的 JPEG，缩略图方向已校正
- DecompressionBomb：upload 成功，thumb 不存在，warning 被记录
- 解码失败降级：upload 成功，thumb 不存在
- 端点：thumb 存在 → 返回 thumb；不存在 → fallback 原图；都不存在 → 404

---

*← [Store 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
