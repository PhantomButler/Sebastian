---
date: 2026-04-29
status: draft
topic: attachment-storage-dedup-cleanup-thumbnails
integrated_to: store/attachments.md, mobile/attachments.md
integrated_at: 2026-05-01
---

# Attachment Storage: Dedup, Ref-Counted Cleanup, Thumbnails

## 1. 背景

`AttachmentStore.upload_bytes` 已经按 SHA-256 把 blob 写到 `blobs/<sha[:2]>/<sha>`，路径是内容寻址的——同内容必然映射到同一文件。但当前实现存在三个相互关联的问题：

1. **重复写入**：每次上传都把数据写到 `tmp/`，再 `os.replace` 覆盖到目标 blob，即便目标已存在内容相同的文件。多次发送同一文件浪费 I/O。
2. **`cleanup` 与共享 blob 的潜在冲突**：现有 `cleanup` 按 record 逐条 `blob.unlink(...)`，没有引用计数。多条 `AttachmentRecord` 指向同一 blob 时（常见，因为路径由 SHA 决定），清理任一条都会物理删除 blob，让其他还在使用的 record 引用失效。问题在没有定时清理调用方时还未暴露，但即将上线"删除 session 后 24h 清理 orphaned record"会立刻触发。
3. **DB 失败回滚也会破坏共享 blob**：`upload_bytes` 在 DB commit 失败时无条件 `blob_abs.unlink(missing_ok=True)`。引入 dedup 后，这个分支可能删掉一个被其他 record 复用的 blob。
4. **缩略图占位实现**：`/api/v1/attachments/{id}/thumbnail` 端点直接返回原图（注释 `P0: return the original image as-is`），没有真正的缩略图生成。聊天列表渲染 256×256 预览却下载完整原图，对移动端流量和加载速度都是浪费。

本次任务一次性解决以上四个问题。

## 2. 范围

### P0 范围

- `upload_bytes` 在 blob 已存在时跳过写入；DB 失败回滚改为只清理"本次新写入"的文件。
- `cleanup` 改为引用计数：blob / thumbnail 仅在没有任何 active record 指向其 SHA 时才物理删除；**DB commit 成功后**才执行物理删除。
- 上传图片时同步生成缩略图，缩略图按 SHA 内容寻址，路径形如 `thumbs/<sha[:2]>/<sha>.<ext>`。
- 缩略图生成走 EXIF 校正、mode 转换、DecompressionBomb 防护；解码失败/超限按"跳过缩略图 + warning"降级。
- `/thumbnail` 端点优先返回缩略图文件；不存在时 fallback 返回原图（兼容老数据与生成失败场景）。
- 修掉 `cleanup` 里 `thumbs/{r.id}.jpg`（UUID）这一历史 placeholder。

### 不做

- 不做异步/后台延迟生成缩略图。
- 不做缩略图多档尺寸（只生成 256×256 一档）。
- 不写 migration script 给历史 record 补生成缩略图（依赖 fallback 路径自然兼容）。
- 不动 `mark_session_orphaned` / session 删除路径——清理逻辑只在 `cleanup` 一处处理。
- 不引入并发锁应对 TOCTOU 同内容并发上传（`os.replace` 原子性保证最终一致，重复 tmp 写入是可接受成本）。
- 不在 `AttachmentRecord` 加 `thumb_path` 字段（避免 schema migration，靠按 SHA 推算 + glob 兜底）。

## 3. 总体设计

### 3.1 Blob 去重写入与回滚一致性

`AttachmentStore.upload_bytes` 重写写入与回滚段。

**两条核心约束**：

1. 用 `created_blob` / `created_thumb` 标志位追踪本次调用是否**新写入**了内容寻址文件。
2. **回滚前必须二次查询同 SHA 引用计数**——`created_blob=True` 不等于"文件独占"。并发场景：上传 A、B 同 SHA 都看到 blob 不存在、各自 `os.replace` 到同一路径、各自 `created_blob=True`；A commit 成功、B commit 失败时，B 回滚分支若直接 unlink 会破坏 A 的 record。必须再查一次"是否还有任何同 SHA record 存在"，count == 0 才允许删除。

```python
sha = hashlib.sha256(data).hexdigest()
blob_rel = f"blobs/{sha[:2]}/{sha}"
blob_abs = self._root_dir / blob_rel

created_blob = False
if not blob_abs.exists():
    blob_abs.parent.mkdir(parents=True, exist_ok=True)
    (self._root_dir / "tmp").mkdir(parents=True, exist_ok=True)
    tmp_path = self._root_dir / "tmp" / str(uuid4())
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, blob_abs)
        created_blob = True
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

# 缩略图生成（详见 3.3），同样追踪 created_thumb 与 thumb_abs
created_thumb = False
thumb_abs: Path | None = None
if kind == "image":
    thumb_abs, created_thumb = _maybe_generate_thumbnail(self._root_dir, sha, data)

# DB 入库
try:
    async with self._db_factory() as session:
        session.add(record)
        await session.commit()
except Exception:
    # 二次确认：并发 upload 可能已用同 SHA 成功入库；此时不能删共享文件
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

DB 层每次仍新建 `AttachmentRecord`（新 UUID），`mark_agent_sent` 状态机不受影响。

### 3.2 引用计数清理

`AttachmentStore.cleanup` 重写关键循环。**三条核心约束**：

1. **批内 SHA 一次性聚合**，避免"两条都过期、彼此看到对方还在 → 都不删 blob → 永久孤儿"。
2. **DB commit 成功后才 unlink 物理文件**。如果先删文件再 commit，commit 失败时 record 还在但 blob 已没，违反不变量"活跃 record 必能找到 blob"（见 §8）。物理 unlink 失败只 warning，不回滚 DB。
3. **commit 后、unlink 前必须二次确认 SHA 仍无引用**。窗口内可能有新 upload 命中同 SHA：blob 还在 → 跳过写入 → 新 record 入库 → cleanup 继续 unlink → 新 record 悬空。无锁设计下必须靠二次查询消除这个窗口。

```python
records = list(...)  # 已查出的待删 record 列表
batch_ids = {r.id for r in records}
shas_in_batch = {r.sha256 for r in records}

# 一次性查出本批 SHA 在批外是否还有 record
remaining_rows = await session.execute(
    select(AttachmentRecord.sha256, func.count())
    .where(
        AttachmentRecord.sha256.in_(shas_in_batch),
        AttachmentRecord.id.notin_(batch_ids),
    )
    .group_by(AttachmentRecord.sha256)
)
remaining_count = {sha: cnt for sha, cnt in remaining_rows.all()}

# 收集需要物理删除的文件，按 SHA 分组保留路径（二次确认时按 SHA 查）
pending_unlink: list[tuple[str, Path]] = []
for r in records:
    if remaining_count.get(r.sha256, 0) == 0:
        pending_unlink.append((r.sha256, self._root_dir / r.blob_path))
        thumb_dir = self._root_dir / "thumbs" / r.sha256[:2]
        if thumb_dir.exists():
            for thumb_path in thumb_dir.glob(f"{r.sha256}.*"):
                pending_unlink.append((r.sha256, thumb_path))
    await session.delete(r)
    count += 1

await session.commit()  # ← DB 必须先成功提交

# 二次确认：commit 后到此处之间可能有新 upload 命中同 SHA
shas_to_check = {sha for sha, _ in pending_unlink}
async with self._db_factory() as session2:
    confirm_rows = await session2.execute(
        select(AttachmentRecord.sha256)
        .where(AttachmentRecord.sha256.in_(shas_to_check))
        .group_by(AttachmentRecord.sha256)
    )
    still_referenced = {row[0] for row in confirm_rows.all()}

for sha, p in pending_unlink:
    if sha in still_referenced:
        continue  # 新 upload 在窗口内入库，保留物理文件
    try:
        p.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("cleanup unlink failed: %s: %s", p, exc)
```

设计要点：

- **按 sha256 查询**：schema 已有 `ix_attachments_sha256` 索引，比 `blob_path` 查更高效。
- **不限 status**：blob 在用与否的判定是"是否存在任何 record 指向同 SHA"，不区分 uploaded / attached / orphaned。
- **thumb 用 glob 取扩展名**：`AttachmentRecord` 不存 thumb 扩展名，cleanup 时无法从 record 推算扩展名，用 `glob(f"{sha}.*")` 一次性收集该 SHA 下所有缩略图（jpg/png/webp）。
- **二次确认开新 session**：避免与已 commit 的当前 session 状态混淆，独立读取最新 DB 视图。
- **新增 `from sqlalchemy import func`**。

### 3.3 缩略图生成

**新增依赖**：`pyproject.toml` 加入 `Pillow`。

**生成位置**：`AttachmentStore.upload_bytes`，blob 写入后、DB 入库前。仅对 `kind == "image"` 生成。封装为模块内私有函数 `_maybe_generate_thumbnail(root_dir, sha, data) -> (thumb_abs | None, created_thumb)`。

**生成参数与流程**：

```python
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

# 模块级：仅设置像素上限常量，不修改 Python warning 系统。
# DecompressionBombWarning → Error 的升级在 _maybe_generate_thumbnail 内部
# 用 warnings.catch_warnings() 作用域化处理（见下方），避免进程级副作用。
Image.MAX_IMAGE_PIXELS = 100_000_000  # 1 亿像素硬上限（约 10000×10000）

THUMB_MAX_EDGE = 256
JPEG_QUALITY = 85
_THUMB_EXT_BY_FORMAT = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


def _maybe_generate_thumbnail(root_dir: Path, sha: str, data: bytes) -> tuple[Path | None, bool]:
    try:
        # catch_warnings 将 warning filter 变更作用域限制在本次调用栈内，
        # 退出时自动还原，不污染进程全局 filter list。
        # asyncio 单线程下无 catch_warnings 的线程安全问题。
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as img:
                img.load()  # force decode；DecompressionBombWarning 在此升级为 Error
            src_format = img.format or ""
            # GIF 单独处理：取第一帧，输出 PNG（保留可能的透明）
            if src_format == "GIF":
                img.seek(0)
                ext = "png"
                save_format = "PNG"
            else:
                ext = _THUMB_EXT_BY_FORMAT.get(src_format)
                if ext is None:
                    return None, False  # 不支持的格式，跳过
                save_format = src_format

            # EXIF orientation 校正（手机照片必备）
            img = ImageOps.exif_transpose(img)

            # mode 转换 — 各输出格式的兼容 mode
            if save_format == "JPEG":
                if img.mode != "RGB":
                    img = img.convert("RGB")
            elif save_format == "PNG":
                # PNG 支持 RGBA / RGB / L / P；P 模式有透明时转 RGBA 避免颜色异常
                if img.mode == "P":
                    img = img.convert("RGBA" if "transparency" in img.info else "RGB")
            elif save_format == "WEBP":
                # WebP 同时支持 RGB / RGBA。其他 mode 一律转 RGBA，
                # 不损失可能存在的 alpha 通道；原图无 alpha 时只多一个全不透明通道，开销极小。
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")

            img.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))

            thumb_rel = f"thumbs/{sha[:2]}/{sha}.{ext}"
            thumb_abs = root_dir / thumb_rel
            if thumb_abs.exists():
                return thumb_abs, False  # dedup：thumb 已存在不重复生成

            thumb_abs.parent.mkdir(parents=True, exist_ok=True)
            (root_dir / "tmp").mkdir(parents=True, exist_ok=True)
            tmp_path = root_dir / "tmp" / str(uuid4())
            try:
                save_kwargs: dict = {"format": save_format, "optimize": True}
                if save_format == "JPEG":
                    save_kwargs["quality"] = JPEG_QUALITY
                img.save(tmp_path, **save_kwargs)
                os.replace(tmp_path, thumb_abs)
                return thumb_abs, True
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
    except Exception as exc:
        # 缩略图生成"一律降级"：捕获所有异常（含 UnidentifiedImageError、
        # DecompressionBombWarning（已升级为 Error）、DecompressionBombError、OSError、
        # ValueError、MemoryError、RuntimeError 等），不让 upload 因 thumb 失败而失败。
        logger.warning("thumbnail generation skipped for sha=%s: %s", sha[:8], exc)
        return None, False
```

**关键设计点：**

- **DecompressionBomb 防护**：`Image.MAX_IMAGE_PIXELS = 100_000_000` 在模块级设置像素上限；`warnings.simplefilter("error", Image.DecompressionBombWarning)` 用 `warnings.catch_warnings()` 作用域化，仅在 `_maybe_generate_thumbnail` 调用期间生效，退出后自动还原，不产生进程级副作用。两者配合让 1 亿像素成为**真正的硬上限**（默认行为下 1 亿到 2 亿之间只警告不阻断）。原图本体不受影响（已通过 `MAX_IMAGE_BYTES = 10MB` 校验）。
- **EXIF orientation**：`ImageOps.exif_transpose(img)` 必须在尺寸缩放前调用。手机照片广泛带 EXIF orientation tag，跳过会出现缩略图横竖颠倒。
- **mode 转换**：
  - JPEG 输出强制 RGB（JPEG 不支持 RGBA/P/LA/CMYK 等）。
  - PNG 输出保留 RGBA；P 模式带透明时转 RGBA 避免调色板透明丢失。
  - WebP 支持 RGB / RGBA，其他 mode 一律转 RGBA（不损失 alpha 信息）。
  - GIF 强制走 PNG 输出分支，先 `seek(0)` 取第一帧。
- **GIF 字典缺位修复**：`_THUMB_EXT_BY_FORMAT` 不包含 `"GIF"`；GIF 在查表前就走单独分支强制 PNG，不会 miss 表。
- **生成失败一律降级**：外层 `except Exception` 兜底（含 `MemoryError` / `RuntimeError` 等非白名单异常），不让 upload 失败。`AttachmentRecord` 仍正常入库，下游靠端点 fallback。
- **thumb 也按 SHA 内容寻址**：路径 `thumbs/<sha[:2]>/<sha>.<ext>`，写入前 `if thumb_abs.exists()` 跳过，与 blob 写入对称。

### 3.4 端点行为

`/api/v1/attachments/{id}/thumbnail` 改为：

1. 取 record，校验 `kind == "image"`。
2. 按 `record.sha256` 推算 thumb 文件路径，逐个尝试 `jpg / png / webp` 三种扩展名（生成时只可能选其中一种）。
3. 命中文件 → 直接返回缩略图，`media_type` 用对应扩展名的 MIME（`image/jpeg` / `image/png` / `image/webp`）。
4. 未命中（老数据 / 生成失败 / 解码超限）→ fallback 读取原 blob，使用 `record.mime_type` 返回。
5. 原 blob 也不存在 → 404。

## 4. 错误处理与降级

| 场景 | 行为 |
|---|---|
| Pillow 解码失败（损坏/非图） | upload 成功，跳过 thumb，warning 日志 |
| DecompressionBomb（像素 > 100M） | `DecompressionBombWarning` 已升级为 Error，外层 `except Exception` 捕获 → upload 成功，跳过 thumb，warning 日志 |
| Pillow 抛出未列入白名单的异常（`MemoryError` 等） | 外层 `except Exception` 兜底，upload 成功，跳过 thumb |
| 同 SHA 并发上传（TOCTOU） | 两次都写各自 tmp，`os.replace` 互相覆盖；最终一致，无锁 |
| upload DB commit 失败、blob 复用 | 二次查 SHA count > 0，blob 保留 |
| upload DB commit 失败、blob 新写入且无并发 | 二次查 SHA count == 0，blob 删除 |
| upload DB commit 失败、并发 upload 已 commit 同 SHA | 二次查 SHA count > 0，blob 保留（消除"删别人 blob"的并发风险） |
| upload DB commit 失败、thumb 同上 | 与 blob 同规则：二次查 SHA count == 0 才删 thumb |
| cleanup DB commit 失败 | `pending_unlink` 不执行，blob/thumb 全部保留；下次 cleanup 重试 |
| cleanup commit 后到 unlink 之间有新 upload 命中同 SHA | 二次查询 SHA 仍被引用，跳过 unlink，blob/thumb 保留 |
| cleanup unlink 物理文件失败 | warning 日志，DB 不回滚 |
| 老 record 没有 thumb 文件 | 端点 fallback 返回原图 |
| 端点 thumb 与 blob 都不存在 | 404 |

## 5. 数据迁移

无需 migration。

- 现有 record 的 `blob_path` 不变。
- 现有 record 没有 thumb 文件——端点 fallback 自动返回原图，行为与改动前一致。
- 新上传的 image record 会同步生成 thumb 文件，下次请求开始走缩略图路径。

## 6. 测试策略

### 单元测试（扩展 `tests/unit/store/test_attachments.py`，按需新建）

**Blob 去重写入**：
- 第二次上传同内容：mock `os.replace` 验证未被调用（**不用 mtime 断言**——同秒写入 mtime 可能不变，flaky）。
- 第二次上传同内容：tmp 目录在调用结束后无新增临时文件。

**Upload 异常路径**：
- DB commit 失败 + blob 已存在（dedup 命中）：二次查 SHA count > 0，blob **保留**。
- DB commit 失败 + blob 新写入 + 无并发：二次查 SHA count == 0，blob 被**删除**。
- DB commit 失败 + blob 新写入 + 并发 upload 已用同 SHA 入库：mock 二次查询返回 count > 0，断言 blob **保留**（关键并发安全测试）。
- DB commit 失败 + thumb：与 blob 同规则覆盖。

**引用计数清理**：
- 两条 record 同 SHA、都在过期清理批次内：清理后两条 record 都被删，**blob 也被删**（最后一条引用消失）。
- 两条 record 同 SHA，一条过期一条活跃：清理只删过期 record，**blob 保留**。
- 三条 record 同 SHA，两条过期一条活跃：清理删两条 record，blob 保留。
- 多种 SHA 混合批次：批内每个 SHA 独立判定。
- **cleanup DB commit 失败**：mock `session.commit` raise，断言 blob/thumb 文件未被 unlink。
- **cleanup unlink 失败**：mock `Path.unlink` raise OSError，断言 DB 状态正确（record 已删），warning 被记录。
- **cleanup commit 后并发 upload 命中同 SHA**：用两个 db_factory 模拟（或在 cleanup commit 与 unlink 之间手动插入一条新 record），断言二次查询识别到引用、blob/thumb 保留。

**缩略图生成**：
- 上传 JPEG：`thumbs/<sha[:2]>/<sha>.jpg` 存在；缩略图最大边 ≤ 256；用 Pillow 重新打开能成功解码（**不断言"thumb 文件 < 原图"**——小图低质量原图可能反而变大）。
- 上传 PNG（带透明度）：thumb 是 PNG，alpha 通道保留。
- 上传 WebP：thumb 是 WebP。
- 上传 GIF：thumb 是 PNG（验证 `Image.open(thumb).format == "PNG"`），尺寸正确。
- **EXIF orientation**：用带 EXIF Orientation tag 的 JPEG fixture（旋转 90°），断言缩略图实际像素方向已校正。
- **PNG palette 模式**：上传 P 模式 + 透明的 PNG，断言 thumb 顺利生成（覆盖 `convert("RGBA")` 分支）。
- **DecompressionBomb 降级**：mock `Image.open(...).load()` raise `DecompressionBombError`（构造真实超大图片不现实），断言 upload 成功、thumb 不存在、warning 被记录。
- **DecompressionBombWarning 升级为 Error**：mock `Image.open(...).load()` 触发 `DecompressionBombWarning`，验证已被 `warnings.simplefilter("error", ...)` 升级为 Error 并被外层捕获（确认 spec §3.3 的 warning filter 真的生效，避免 100M~200M 像素图片漏过）。
- **未列入白名单的异常降级**：mock `img.save` raise `MemoryError` / `RuntimeError`，断言外层 `except Exception` 捕获，upload 成功、thumb 不存在。
- **解码失败降级**：上传文件名为 `.png` 但内容是任意字节，断言 upload 成功、thumb 不存在、warning 被记录。
- 上传同内容图片两次：thumb 文件路径相同，mock `Image.open` 第二次未被调用 OR mock 写入路径未被触发。

**端点 fallback**：
- thumb 文件存在 → 返回 thumb，`Content-Type` 是缩略图格式。
- thumb 文件不存在但 blob 存在 → fallback 返回原图，`Content-Type` 是原图 MIME。
- thumb 与 blob 都不存在 → 404。

### 集成测试（扩展 `tests/integration/test_gateway_attachments.py`）

- `send_file` 同一文件两次：返回不同 `attachment_id`，但磁盘 blob/thumb 不重复（用文件 inode 或 mock 验证）。
- 上传图片后调用 `/thumbnail`：返回缩略图，`Content-Type` 为缩略图格式（验证与原图 MIME 不同时的差异）。
- 老 record（手动构造无 thumb 文件的场景）调 `/thumbnail`：返回原图。

## 7. 文件改动清单

| 文件 | 改动 |
|---|---|
| `pyproject.toml` | 加 `Pillow` 依赖 |
| `sebastian/store/attachments.py` | `upload_bytes` 加 blob 去重写入与精确回滚；新增 `_maybe_generate_thumbnail`；`cleanup` 改为引用计数 + DB-first commit + glob thumb 路径；**修掉历史 placeholder `thumbs/{r.id}.jpg`**；`from sqlalchemy import func` |
| `sebastian/gateway/routes/attachments.py` | `/thumbnail` 端点改为优先返回 SHA-based 缩略图、fallback 原图 |
| `tests/unit/store/test_attachments.py`（新建或扩展） | 新单元测试 |
| `tests/integration/test_gateway_attachments.py` | 集成测试补充 |
| `sebastian/store/README.md` | 同步说明 blob/thumb 内容寻址、ref counting cleanup 行为、DB-first 顺序约束 |

## 8. 不变量

- `AttachmentRecord.id` 在每次 `upload_bytes` 都是新 UUID，跨次发送不复用。
- `AttachmentRecord.sha256` 与 `blob_path` 一一对应（`blob_path == f"blobs/{sha[:2]}/{sha}"`）。
- **任何 DB-committed 的活跃 `AttachmentRecord`（不在 cleanup 待删集合里）都能通过 `blob_path` 找到磁盘文件**。这条不变量在无锁设计下由三层机制共同保证：
  - cleanup 的 "DB commit 后才 unlink 物理文件" 顺序；
  - upload 回滚的 "二次查 SHA count == 0 才 unlink" 检查；
  - cleanup 物理删除前的 "二次查 SHA 仍无引用" 检查。
- `kind == "image"` 的 record 的缩略图存在性**不是**不变量——可能因解码失败 / DecompressionBomb / 老数据而缺失，端点必须处理。
