# Attachment Storage Dedup, Ref-Counted Cleanup, Thumbnails — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `AttachmentStore` 在写入 blob 前去重、在 cleanup 时按 SHA 引用计数安全删除，并同步生成 SHA 内容寻址的缩略图；过程中保证并发安全与降级行为。

**Architecture:**
- `sebastian/store/attachments.py` 是核心：`upload_bytes` 写入加 `if not blob_abs.exists()` 跳过 + DB 失败时按 SHA 二次查询再决定是否回滚物理文件；新增私有函数 `_maybe_generate_thumbnail` 负责图片缩略图生成，错误一律降级为 warning；`cleanup` 按 SHA 聚合 + DB-first commit + commit 后二次查询确认无并发新增引用再 unlink。
- `sebastian/gateway/routes/attachments.py` 的 `/thumbnail` 端点改为按 `record.sha256` 优先返回缩略图、缺失则 fallback 原图。
- 测试集中在 `tests/unit/store/test_attachments.py`（已存在），增加缩略图、并发回滚、cleanup ref counting 的覆盖；`tests/integration/test_gateway_attachments.py` 补端点新行为。

**Tech Stack:** Python 3.12 + SQLAlchemy 2.0 async + aiosqlite + Pillow（新增）+ pytest-asyncio（auto mode）。

---

## File Structure

| 文件 | 改动类型 | 责任 |
|---|---|---|
| `pyproject.toml` | Modify | 添加 `Pillow>=10.0` 依赖 |
| `sebastian/store/attachments.py` | Modify | 新增模块级 logger、Pillow 设置、`_maybe_generate_thumbnail`；改写 `upload_bytes` 写入与回滚；改写 `cleanup` 引用计数 |
| `sebastian/gateway/routes/attachments.py` | Modify | `download_thumbnail` 端点：按 SHA 找 thumb，缺失 fallback 原图 |
| `tests/unit/store/test_attachments.py` | Modify | 增 dedup / 缩略图 / cleanup ref counting / 并发回滚 单元测试 |
| `tests/integration/test_gateway_attachments.py` | Modify | 补 `/thumbnail` 端点新行为集成测试 |
| `sebastian/store/README.md` | Modify | 同步说明 blob/thumb 内容寻址、ref counting cleanup 顺序约束 |

---

## Task 1：添加 Pillow 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1：编辑 `pyproject.toml`，在 `dependencies` 列表末尾追加 Pillow**

把 `pyproject.toml` 第 11-30 行的 `dependencies = [...]` 改为：

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "aiofiles>=24.1",
    "anthropic>=0.40",
    "openai>=1.50",
    "python-ulid>=3.0",
    "mcp>=1.0",
    "httpx>=0.27",
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    "apscheduler>=3.10",
    "python-dotenv>=1.0",
    "typer>=0.12",
    "rich>=13.0",
    "Pillow>=10.0",
]
```

- [ ] **Step 2：本地安装新依赖**

Run: `pip install -e ".[dev,memory]"`
Expected: 输出包含 `Successfully installed ... Pillow-...`，无报错。

- [ ] **Step 3：验证 Pillow 可导入**

Run: `python -c "from PIL import Image, ImageOps; print(Image.__version__)"`
Expected: 输出版本号（如 `10.4.0`），无 ImportError。

- [ ] **Step 4：提交**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
chore(deps): 添加 Pillow 依赖

为 attachment 缩略图生成做准备。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2：在 attachments.py 添加 Pillow 模块级配置

引入 Pillow，设置 DecompressionBomb 防护（关键：把默认仅 Warning 的 1 亿~2 亿像素区间升级为 Error），并加 logger。

**Files:**
- Modify: `sebastian/store/attachments.py:1-13`

- [ ] **Step 1：在文件顶部增加 logger 与 Pillow 设置**

把 `sebastian/store/attachments.py` 第 1-13 行（imports 部分）改为：

```python
from __future__ import annotations

import hashlib
import logging
import os
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.store.models import AttachmentRecord

logger = logging.getLogger(__name__)

# DecompressionBomb 防护：Pillow 默认在 > MAX_IMAGE_PIXELS 时只发 Warning，
# > 2 × MAX 才抛 Error。主动把 Warning 升级为 Error，让 1 亿像素成为真正的硬上限。
Image.MAX_IMAGE_PIXELS = 100_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)
```

- [ ] **Step 2：跑一次现有测试确认未破坏**

Run: `pytest tests/unit/store/test_attachments.py -x`
Expected: 全部 PASS（仍是改动前的功能集合）。

- [ ] **Step 3：提交**

```bash
git add sebastian/store/attachments.py
git commit -m "$(cat <<'EOF'
chore(store): 引入 Pillow 与 DecompressionBomb 防护

为缩略图生成准备模块级 imports 与防护设置；warning 升级为 error，
让 1 亿像素成为真正硬上限。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3：实现 `_maybe_generate_thumbnail` 多格式 happy path

实现 JPEG / PNG / WebP / GIF 四种格式的缩略图生成。GIF 走单独分支（取第一帧、输出 PNG）。本任务先写覆盖 happy path 的测试与实现，**EXIF / mode 转换 / bomb 防护放后续任务**。

**Files:**
- Modify: `sebastian/store/attachments.py`（追加 `_maybe_generate_thumbnail` 与常量）
- Modify: `tests/unit/store/test_attachments.py`（追加测试）

- [ ] **Step 1：写失败测试 — 四种 happy path**

在 `tests/unit/store/test_attachments.py` 末尾追加：

```python
# ── _maybe_generate_thumbnail tests ─────────────────────────────────────────

import hashlib as _hashlib
from io import BytesIO

from PIL import Image
from sebastian.store.attachments import _maybe_generate_thumbnail


def _make_image_bytes(format: str, size: tuple[int, int] = (800, 600), mode: str = "RGB") -> bytes:
    img = Image.new(mode, size, color=(120, 200, 50) if mode == "RGB" else (120, 200, 50, 200))
    buf = BytesIO()
    save_kwargs: dict = {"format": format}
    if format == "JPEG":
        save_kwargs["quality"] = 85
    img.save(buf, **save_kwargs)
    return buf.getvalue()


def test_thumbnail_jpeg_happy_path(tmp_path: Path) -> None:
    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    assert thumb_abs is not None
    assert thumb_abs == tmp_path / "thumbs" / sha[:2] / f"{sha}.jpg"
    assert thumb_abs.exists()
    with Image.open(thumb_abs) as out:
        assert out.format == "JPEG"
        assert max(out.size) <= 256


def test_thumbnail_png_happy_path(tmp_path: Path) -> None:
    data = _make_image_bytes("PNG", mode="RGBA")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    assert thumb_abs == tmp_path / "thumbs" / sha[:2] / f"{sha}.png"
    with Image.open(thumb_abs) as out:
        assert out.format == "PNG"
        assert max(out.size) <= 256


def test_thumbnail_webp_happy_path(tmp_path: Path) -> None:
    data = _make_image_bytes("WEBP")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    assert thumb_abs == tmp_path / "thumbs" / sha[:2] / f"{sha}.webp"
    with Image.open(thumb_abs) as out:
        assert out.format == "WEBP"


def test_thumbnail_gif_first_frame_as_png(tmp_path: Path) -> None:
    data = _make_image_bytes("GIF", mode="P")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    # GIF 强制走 PNG 输出
    assert thumb_abs == tmp_path / "thumbs" / sha[:2] / f"{sha}.png"
    with Image.open(thumb_abs) as out:
        assert out.format == "PNG"


def test_thumbnail_unsupported_format_returns_none(tmp_path: Path) -> None:
    # BMP 不在 _THUMB_EXT_BY_FORMAT 里
    data = _make_image_bytes("BMP")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert thumb_abs is None
    assert created is False
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/unit/store/test_attachments.py::test_thumbnail_jpeg_happy_path -v`
Expected: FAIL，错误为 `ImportError: cannot import name '_maybe_generate_thumbnail'`。

- [ ] **Step 3：实现 `_maybe_generate_thumbnail`（先写最简覆盖四格式 + None 分支）**

在 `sebastian/store/attachments.py` 中，**`AttachmentStore` 类定义之前**（紧接着 module 顶部常量之后），插入：

```python
THUMB_MAX_EDGE = 256
JPEG_QUALITY = 85
_THUMB_EXT_BY_FORMAT: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


def _maybe_generate_thumbnail(
    root_dir: Path, sha: str, data: bytes
) -> tuple[Path | None, bool]:
    """对图片字节生成 256×256 缩略图，写到 thumbs/<sha[:2]>/<sha>.<ext>。

    返回 (thumb_abs, created)：
      - thumb_abs is None / created False：未生成（不支持的格式或异常降级）
      - thumb_abs not None / created True：本次新写入了 thumb 文件
      - thumb_abs not None / created False：thumb 已存在，跳过写入（dedup）
    """
    try:
        with Image.open(BytesIO(data)) as img:
            img.load()
            src_format = img.format or ""
            if src_format == "GIF":
                img.seek(0)
                ext = "png"
                save_format = "PNG"
            else:
                ext = _THUMB_EXT_BY_FORMAT.get(src_format)
                if ext is None:
                    return None, False
                save_format = src_format

            img.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))

            thumb_rel = f"thumbs/{sha[:2]}/{sha}.{ext}"
            thumb_abs = root_dir / thumb_rel
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
        logger.warning("thumbnail generation skipped for sha=%s: %s", sha[:8], exc)
        return None, False
```

- [ ] **Step 4：跑测试验证 happy path PASS**

Run: `pytest tests/unit/store/test_attachments.py -k thumbnail -v`
Expected: 5 个测试全部 PASS。

- [ ] **Step 5：提交**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(store): 实现 _maybe_generate_thumbnail 多格式 happy path

JPEG/PNG/WebP/GIF 四种输入格式。GIF 单独分支取第一帧并以 PNG 输出。
缩略图按 SHA 内容寻址路径 thumbs/<sha[:2]>/<sha>.<ext>，最大边 256。
不支持的格式返回 (None, False) 不阻断 upload。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4：补 EXIF orientation 校正与 mode 转换

手机照片广泛带 EXIF Orientation tag，缺校正会导致缩略图颠倒；JPEG 不支持 RGBA/P 等 mode，PNG palette 模式带透明时需转 RGBA 保留信息。

**Files:**
- Modify: `sebastian/store/attachments.py`（修改 `_maybe_generate_thumbnail`）
- Modify: `tests/unit/store/test_attachments.py`（追加测试）

- [ ] **Step 1：写失败测试 — EXIF orientation 与 PNG palette**

追加：

```python
def test_thumbnail_exif_orientation_corrected(tmp_path: Path) -> None:
    """带 EXIF Orientation=6（顺时针 90°）的 JPEG，缩略图应已校正方向。"""
    img = Image.new("RGB", (800, 400), color=(255, 0, 0))  # 800×400 横图
    buf = BytesIO()
    # 写入 EXIF Orientation=6（旋转 90 CW）
    exif = img.getexif()
    exif[0x0112] = 6
    img.save(buf, format="JPEG", exif=exif.tobytes(), quality=85)
    data = buf.getvalue()
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, _ = _maybe_generate_thumbnail(tmp_path, sha, data)
    assert thumb_abs is not None

    with Image.open(thumb_abs) as out:
        # 校正后原本 800×400 横图应被旋转为竖图，宽 < 高
        assert out.width < out.height


def test_thumbnail_png_palette_with_transparency(tmp_path: Path) -> None:
    """P 模式 + transparency 信息的 PNG：转 RGBA 后输出，alpha 保留。"""
    img = Image.new("P", (200, 200))
    img.putpalette([0, 0, 0] * 256)
    buf = BytesIO()
    img.save(buf, format="PNG", transparency=0)
    data = buf.getvalue()
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    assert thumb_abs is not None
    with Image.open(thumb_abs) as out:
        assert out.format == "PNG"
        # 应已转换为 RGBA（保留透明信息），不是 P
        assert out.mode in ("RGBA", "RGB")  # 至少不能因 mode 转换抛异常
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/unit/store/test_attachments.py::test_thumbnail_exif_orientation_corrected -v`
Expected: FAIL（缩略图 width >= height，因为没做 transpose）。

- [ ] **Step 3：在 `_maybe_generate_thumbnail` 加 EXIF transpose 与 mode 转换**

把 `_maybe_generate_thumbnail` 中 `img.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))` **之前**插入 EXIF + mode 转换块：

```python
            # EXIF orientation 校正必须在缩放前
            img = ImageOps.exif_transpose(img)

            # 按输出格式做必要的 mode 转换
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
                # WebP 同时支持 RGB / RGBA。其他 mode 一律转 RGBA，不损失 alpha。
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")

            img.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))
```

- [ ] **Step 4：验证测试 PASS**

Run: `pytest tests/unit/store/test_attachments.py -k thumbnail -v`
Expected: 全部 PASS（含两条新测试）。

- [ ] **Step 5：提交**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(store): 缩略图加 EXIF 校正与按格式 mode 转换

EXIF Orientation 在缩放前 transpose；JPEG 转 RGB；PNG 的 P 模式按
transparency 信息转 RGBA 或 RGB；WebP 非 RGB/RGBA 转 RGBA 保 alpha。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5：补 DecompressionBomb 防护与通用异常降级

确认 `DecompressionBombWarning` 升级为 Error 后会被外层 `except Exception` 捕获；同时验证 `MemoryError` / `RuntimeError` 等非白名单异常也会降级（不让 upload 失败）。

**Files:**
- Modify: `tests/unit/store/test_attachments.py`（追加测试，无需改实现——上层 except Exception 已就位）

- [ ] **Step 1：写失败测试 — bomb 与通用异常降级**

追加：

```python
def test_thumbnail_decompression_bomb_warning_upgraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超过 MAX_IMAGE_PIXELS 触发 DecompressionBombWarning，应被 simplefilter 升级为 Error 并降级。"""

    class _BombingImage:
        format = "JPEG"
        mode = "RGB"
        size = (20000, 20000)

        def load(self):
            raise Image.DecompressionBombWarning("simulated bomb")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def _fake_open(_buf):
        return _BombingImage()

    monkeypatch.setattr("sebastian.store.attachments.Image.open", _fake_open)

    data = b"\xff\xd8\xff\xe0fake"
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert thumb_abs is None
    assert created is False
    # 没有写入 thumb
    assert not (tmp_path / "thumbs").exists() or not any((tmp_path / "thumbs").rglob("*"))


def test_thumbnail_generic_exception_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """img.save 抛 MemoryError / RuntimeError 也走外层 except Exception 兜底。"""
    import logging

    real_open = Image.open

    class _BadSaveImage:
        def __init__(self, real):
            self._real = real
            self.format = real.format
            self.mode = real.mode
            self.size = real.size

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

        def load(self):
            self._real.load()

        def seek(self, n):
            self._real.seek(n)

        def thumbnail(self, *a, **kw):
            self._real.thumbnail(*a, **kw)

        def convert(self, mode):
            return self._real.convert(mode)

        def save(self, *_a, **_kw):
            raise MemoryError("simulated OOM")

        def getexif(self):
            return self._real.getexif()

    def _fake_open(buf):
        real = real_open(buf)
        return _BadSaveImage(real)

    monkeypatch.setattr("sebastian.store.attachments.Image.open", _fake_open)
    monkeypatch.setattr(
        "sebastian.store.attachments.ImageOps.exif_transpose",
        lambda im: im,
    )

    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()

    with caplog.at_level(logging.WARNING, logger="sebastian.store.attachments"):
        thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert thumb_abs is None
    assert created is False
    assert any("thumbnail generation skipped" in m for m in caplog.messages)
```

- [ ] **Step 2：跑测试**

Run: `pytest tests/unit/store/test_attachments.py -k "decompression or generic_exception" -v`
Expected: 全部 PASS（外层 `except Exception` 已经能兜底；如果 FAIL 说明 §3.3 设计未落实，需检查上一任务的 except 是否写成了 `except Exception` 而不是白名单类型）。

- [ ] **Step 3：提交**

```bash
git add tests/unit/store/test_attachments.py
git commit -m "$(cat <<'EOF'
test(store): 补 thumbnail bomb 与通用异常降级测试

验证 DecompressionBombWarning 已升级为 Error 并被外层捕获；MemoryError
等非白名单异常也走 except Exception 兜底，不阻断 upload。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6：缩略图 dedup（同 SHA 不重复生成）

第二次拿同 SHA 调 `_maybe_generate_thumbnail` 时，thumb 文件已存在则跳过 `img.save`，返回 `(thumb_abs, False)`。

**Files:**
- Modify: `sebastian/store/attachments.py`（`_maybe_generate_thumbnail` 加 `if thumb_abs.exists(): return ..., False`）
- Modify: `tests/unit/store/test_attachments.py`（追加测试）

- [ ] **Step 1：写失败测试 — 第二次调用不写 tmp**

追加：

```python
def test_thumbnail_dedup_skips_save_when_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()

    # 第一次正常生成
    thumb_abs1, created1 = _maybe_generate_thumbnail(tmp_path, sha, data)
    assert created1 is True
    assert thumb_abs1.exists()

    # 第二次：mock os.replace 验证未被调用
    real_replace = os.replace
    call_count = {"n": 0}

    def _counting_replace(*args, **kwargs):
        call_count["n"] += 1
        return real_replace(*args, **kwargs)

    monkeypatch.setattr("sebastian.store.attachments.os.replace", _counting_replace)

    thumb_abs2, created2 = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert thumb_abs2 == thumb_abs1
    assert created2 is False
    assert call_count["n"] == 0  # 未执行 os.replace
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/unit/store/test_attachments.py::test_thumbnail_dedup_skips_save_when_exists -v`
Expected: FAIL（`call_count["n"] == 1` 而不是 0）。

- [ ] **Step 3：在 `_maybe_generate_thumbnail` 加 dedup 判断**

把 `_maybe_generate_thumbnail` 中：

```python
            thumb_rel = f"thumbs/{sha[:2]}/{sha}.{ext}"
            thumb_abs = root_dir / thumb_rel
            thumb_abs.parent.mkdir(parents=True, exist_ok=True)
```

改为：

```python
            thumb_rel = f"thumbs/{sha[:2]}/{sha}.{ext}"
            thumb_abs = root_dir / thumb_rel
            if thumb_abs.exists():
                return thumb_abs, False
            thumb_abs.parent.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4：跑测试 PASS**

Run: `pytest tests/unit/store/test_attachments.py -k thumbnail -v`
Expected: 全部 PASS。

- [ ] **Step 5：提交**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(store): 缩略图 SHA 内容寻址 dedup

第二次同 SHA 调 _maybe_generate_thumbnail 时跳过 save，返回 (path, False)。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7：`upload_bytes` blob 去重写入

写入 blob 前 `if not blob_abs.exists():` 跳过 tmp 写入；用 `created_blob` 标志位记录是否新写入（为后续回滚二次查询服务）。

**Files:**
- Modify: `sebastian/store/attachments.py:82-93`
- Modify: `tests/unit/store/test_attachments.py`（追加测试）

- [ ] **Step 1：写失败测试 — 同内容第二次上传不写 tmp**

追加：

```python
async def test_upload_bytes_dedup_skips_blob_write(
    attachment_store: AttachmentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"hello dedup world"
    await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )

    # 第二次上传：mock os.replace 验证未被调用
    call_count = {"n": 0}
    real_replace = os.replace

    def _counting_replace(*args, **kwargs):
        call_count["n"] += 1
        return real_replace(*args, **kwargs)

    monkeypatch.setattr("sebastian.store.attachments.os.replace", _counting_replace)

    await attachment_store.upload_bytes(
        filename="b.md", content_type="text/markdown", kind="text_file", data=data
    )
    assert call_count["n"] == 0  # blob 未被重新写入
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/unit/store/test_attachments.py::test_upload_bytes_dedup_skips_blob_write -v`
Expected: FAIL（`call_count["n"] == 1`）。

- [ ] **Step 3：修改 `upload_bytes` 写入逻辑**

把 `sebastian/store/attachments.py` 第 82-93 行（`sha = ...` 到第一个 `try ... except` 块结束）改为：

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
```

- [ ] **Step 4：跑测试 PASS**

Run: `pytest tests/unit/store/test_attachments.py -k upload -v`
Expected: 全部 PASS（已存在的 upload 测试 + 新 dedup 测试）。

- [ ] **Step 5：提交**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(store): upload_bytes 同内容 blob 去重写入

blob 已存在时跳过 tmp 写入与 os.replace；created_blob 标志位记录是否
新写入，为后续回滚二次查询做准备。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8：把缩略图生成与并发安全回滚接入 `upload_bytes`

`upload_bytes` 在 image 类型时调 `_maybe_generate_thumbnail`；DB 失败回滚时**先二次查询同 SHA count**，count == 0 才删本次新写入的文件。

**Files:**
- Modify: `sebastian/store/attachments.py:95-120`
- Modify: `tests/unit/store/test_attachments.py`（追加测试）

- [ ] **Step 1：写失败测试 — DB 失败、blob 已存在不该删；DB 失败、blob 新写入且无并发应删；DB 失败、有并发同 SHA 应保留**

追加：

```python
async def test_upload_bytes_db_failure_keeps_dedup_blob(
    attachment_store: AttachmentStore,
    sqlite_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB commit 失败 + blob 是 dedup 命中（非本次新建）→ 不删 blob。"""
    data = b"shared blob content"
    await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha
    assert blob_abs.exists()

    # 让 DB commit 抛异常
    real_factory = attachment_store._db_factory

    class _FailingSession:
        def __init__(self, real_session):
            self._real = real_session

        async def __aenter__(self):
            return await self._real.__aenter__()

        async def __aexit__(self, *args):
            return await self._real.__aexit__(*args)

    def _failing_factory():
        sess = real_factory()
        original_commit = None

        class _W:
            async def __aenter__(self):
                self._inner = await sess.__aenter__()
                nonlocal original_commit
                original_commit = self._inner.commit

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
            filename="b.md", content_type="text/markdown", kind="text_file", data=data
        )

    # blob 必须保留（已有 record 在用）
    assert blob_abs.exists()


async def test_upload_bytes_db_failure_deletes_new_blob_when_no_other_record(
    attachment_store: AttachmentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB commit 失败 + blob 是本次新建 + 无其他 record → 删 blob。"""
    data = b"unique brand new content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

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

    with pytest.raises(RuntimeError):
        await attachment_store.upload_bytes(
            filename="x.md", content_type="text/markdown", kind="text_file", data=data
        )

    # blob 必须被删除（没有任何 record 引用它）
    assert not blob_abs.exists()
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/unit/store/test_attachments.py -k "db_failure" -v`
Expected: FAIL（当前实现的 except 会无条件 unlink，第一条会失败：blob 被错误删除）。

- [ ] **Step 3：改写 `upload_bytes` 的缩略图接入与并发安全回滚**

把 `sebastian/store/attachments.py` 第 95-120 行（`text_excerpt` 那段到 `try / except` 结束）改为：

```python
        text_excerpt: str | None = None
        if kind == "text_file":
            text = data.decode("utf-8")
            text_excerpt = text[:TEXT_EXCERPT_CHARS]

        created_thumb = False
        thumb_abs: Path | None = None
        if kind == "image":
            thumb_abs, created_thumb = _maybe_generate_thumbnail(
                self._root_dir, sha, data
            )

        att_id = str(uuid4())
        record = AttachmentRecord(
            id=att_id,
            kind=kind,
            original_filename=filename,
            mime_type=content_type,
            size_bytes=len(data),
            sha256=sha,
            blob_path=blob_rel,
            text_excerpt=text_excerpt,
            status="uploaded",
            created_at=datetime.now(UTC),
            owner_user_id=None,
        )
        try:
            async with self._db_factory() as session:
                session.add(record)
                await session.commit()
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

> 注意：原来 `record = AttachmentRecord(...)` 块已经存在，不要重复添加。本步实质是把现有 `record = ...` 块**保留**、把后面的 `try/except Exception: blob_abs.unlink(...)` **替换为**新的二次查询版本。请用 Read 确认行号与现有内容后做精确 Edit。

- [ ] **Step 4：跑测试 PASS**

Run: `pytest tests/unit/store/test_attachments.py -k "upload or thumbnail" -v`
Expected: 全部 PASS。

Run（全量回归）: `pytest tests/unit/store/test_attachments.py -v`
Expected: 所有现有 + 新增测试全 PASS。

- [ ] **Step 5：提交**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(store): 接入缩略图生成与并发安全回滚

upload_bytes 在 image 类型时调 _maybe_generate_thumbnail。DB commit 失败
回滚分支改为先按 SHA 二次查询 count，==0 才 unlink，避免并发 upload
场景下误删共享 blob/thumb。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9：`cleanup` 改为按 SHA 引用计数 + DB-first commit

把现有 `cleanup` 的 "for r in records: blob.unlink(...); session.delete(r)" 模式改为：先按 SHA 聚合 ref count、收集 `pending_unlink: list[tuple[str, Path]]`、`session.commit()` 成功**之后**再 unlink 文件；同时把历史 placeholder `thumbs/{r.id}.jpg` 改为 `thumbs/<sha[:2]>/<sha>.*` 的 glob。

**Files:**
- Modify: `sebastian/store/attachments.py:240-278`
- Modify: `tests/unit/store/test_attachments.py`（追加测试）

- [ ] **Step 1：写失败测试 — ref counting 与 DB-first commit**

追加：

```python
async def test_cleanup_keeps_blob_when_other_record_uses_same_sha(
    attachment_store: AttachmentStore, sqlite_session_factory
) -> None:
    """两条 record 同 SHA：一条过期一条活跃 → 清理后 blob 保留。"""
    data = b"shared content for cleanup"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    # 第一条：手动写成已过期的 uploaded
    r1 = await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )
    # 第二条：活跃 uploaded
    await attachment_store.upload_bytes(
        filename="b.md", content_type="text/markdown", kind="text_file", data=data
    )

    # 把 r1 created_at 改成 2 天前，触发 uploaded TTL
    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r1.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    deleted = await attachment_store.cleanup()
    assert deleted >= 1
    assert blob_abs.exists()  # 第二条仍持有引用


async def test_cleanup_deletes_blob_when_last_record_removed(
    attachment_store: AttachmentStore, sqlite_session_factory
) -> None:
    """同 SHA 两条 record 都过期 → blob 被删（最后一条引用消失）。"""
    data = b"dies together content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    r1 = await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )
    r2 = await attachment_store.upload_bytes(
        filename="b.md", content_type="text/markdown", kind="text_file", data=data
    )

    async with sqlite_session_factory() as session:
        for rid in (r1.id, r2.id):
            rec = await session.get(AttachmentRecord, rid)
            rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    deleted = await attachment_store.cleanup()
    assert deleted >= 2
    assert not blob_abs.exists()


async def test_cleanup_deletes_thumbnail_via_glob(
    attachment_store: AttachmentStore, sqlite_session_factory
) -> None:
    """image record 过期且 SHA 无其他引用 → thumbs/<sha[:2]>/<sha>.* 被删。"""
    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()
    thumb_abs = attachment_store._root_dir / "thumbs" / sha[:2] / f"{sha}.jpg"

    r = await attachment_store.upload_bytes(
        filename="x.jpg", content_type="image/jpeg", kind="image", data=data
    )
    assert thumb_abs.exists()

    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    await attachment_store.cleanup()
    assert not thumb_abs.exists()


async def test_cleanup_db_failure_keeps_files(
    attachment_store: AttachmentStore, sqlite_session_factory, monkeypatch
) -> None:
    """cleanup commit 失败时不能 unlink 物理文件（违反不变量）。"""
    data = b"db failure content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    r = await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )
    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    # mock：让 cleanup 内部的 commit 抛错
    real_factory = attachment_store._db_factory
    fail_first = {"done": False}

    def _factory_with_failing_commit():
        sess = real_factory()

        class _W:
            async def __aenter__(self):
                self._inner = await sess.__aenter__()
                if not fail_first["done"]:
                    fail_first["done"] = True

                    async def _bad_commit():
                        raise RuntimeError("simulated cleanup commit failure")

                    self._inner.commit = _bad_commit
                return self._inner

            async def __aexit__(self, *args):
                return await sess.__aexit__(*args)

        return _W()

    monkeypatch.setattr(attachment_store, "_db_factory", _factory_with_failing_commit)

    with pytest.raises(RuntimeError, match="simulated cleanup commit failure"):
        await attachment_store.cleanup()

    # blob 必须保留
    assert blob_abs.exists()
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/unit/store/test_attachments.py -k cleanup -v`
Expected: 多条 FAIL。

- [ ] **Step 3：改写 `cleanup` 关键循环**

把 `sebastian/store/attachments.py` 第 240-278 行的整个 `cleanup` 方法替换为：

```python
    async def cleanup(self, now: datetime | None = None) -> int:
        _now = now or datetime.now(UTC)
        uploaded_cutoff = _now - _UPLOADED_TTL
        orphan_cutoff = _now - _ORPHAN_TTL
        count = 0
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
            records = list(result.scalars().all())

            if not records:
                # 仍需清理 tmp 目录
                count += self._cleanup_tmp(uploaded_cutoff)
                return count

            batch_ids = {r.id for r in records}
            shas_in_batch = {r.sha256 for r in records}

            remaining_rows = await session.execute(
                select(AttachmentRecord.sha256, func.count())
                .where(
                    AttachmentRecord.sha256.in_(shas_in_batch),
                    AttachmentRecord.id.notin_(batch_ids),
                )
                .group_by(AttachmentRecord.sha256)
            )
            remaining_count = {row[0]: row[1] for row in remaining_rows.all()}

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

        # commit 后到 unlink 之前，可能有新 upload 命中同 SHA（Task 10 处理二次确认）
        for _sha, p in pending_unlink:
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("cleanup unlink failed: %s: %s", p, exc)

        count += self._cleanup_tmp(uploaded_cutoff)
        return count

    def _cleanup_tmp(self, uploaded_cutoff: datetime) -> int:
        cleaned = 0
        tmp_dir = self._root_dir / "tmp"
        if tmp_dir.exists():
            for tmp_file in tmp_dir.iterdir():
                if tmp_file.is_file():
                    try:
                        mtime = datetime.fromtimestamp(tmp_file.stat().st_mtime, UTC)
                        if mtime < uploaded_cutoff:
                            tmp_file.unlink(missing_ok=True)
                            cleaned += 1
                    except OSError:
                        pass
        return cleaned
```

- [ ] **Step 4：跑测试 PASS**

Run: `pytest tests/unit/store/test_attachments.py -k cleanup -v`
Expected: 全部 PASS。

Run（全量回归）: `pytest tests/unit/store/test_attachments.py -v`
Expected: 所有测试 PASS。

- [ ] **Step 5：提交**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(store): cleanup 引入按 SHA 引用计数与 DB-first commit

按 SHA 一次性聚合"批外是否仍有引用"，仅当无引用时才把 blob/thumb 加入
pending_unlink。session.commit 成功后才 unlink 物理文件，commit 失败时
保留所有文件。thumb 路径改为 glob 取 SHA 下所有候选扩展名，移除历史
{r.id}.jpg placeholder。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10：`cleanup` commit 后二次确认无并发新增引用

无锁场景下，cleanup commit 与 unlink 之间的窗口内可能有新 upload 命中同 SHA → blob 还在 → 跳过写入 → DB 入库新 record。继续 unlink 会让新 record 悬空。本任务把"二次确认"提取为命名方法 `_check_still_referenced_shas`，在 commit 后调用；测试用 `monkeypatch` 替换该方法即可模拟并发场景。

**Files:**
- Modify: `sebastian/store/attachments.py`（提取 `_check_still_referenced_shas`，在 cleanup 中使用）
- Modify: `tests/unit/store/test_attachments.py`（追加测试）

- [ ] **Step 1：写失败测试 — 二次确认返回"仍有引用"时跳过 unlink**

追加：

```python
async def test_cleanup_skips_unlink_when_confirm_finds_references(
    attachment_store: AttachmentStore,
    sqlite_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟 commit 与 unlink 之间出现新 upload：把 _check_still_referenced_shas
    monkeypatch 成"全部仍有引用"，验证 unlink 被跳过、blob 保留。"""
    data = b"two-step confirm content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    r = await attachment_store.upload_bytes(
        filename="x.md", content_type="text/markdown", kind="text_file", data=data
    )
    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    async def _fake_check(_self, shas):
        # 模拟二次确认时，所有 SHA 都仍有引用（被并发 upload 占用）
        return set(shas)

    monkeypatch.setattr(
        AttachmentStore,
        "_check_still_referenced_shas",
        _fake_check,
    )

    await attachment_store.cleanup()
    assert blob_abs.exists()


async def test_cleanup_unlinks_when_confirm_returns_empty(
    attachment_store: AttachmentStore, sqlite_session_factory
) -> None:
    """二次确认返回空集合（确实无并发引用）→ blob 被 unlink。
    顺带覆盖 _check_still_referenced_shas 默认实现的 happy path。"""
    data = b"safe to delete content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    r = await attachment_store.upload_bytes(
        filename="x.md", content_type="text/markdown", kind="text_file", data=data
    )
    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    await attachment_store.cleanup()
    assert not blob_abs.exists()
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/unit/store/test_attachments.py::test_cleanup_skips_unlink_when_confirm_finds_references -v`
Expected: FAIL，错误为 `AttributeError: ... has no attribute '_check_still_referenced_shas'`。

- [ ] **Step 3：把二次确认抽成方法并在 cleanup 中调用**

在 `AttachmentStore` 类中（紧贴 `cleanup` 方法之前）新增私有方法：

```python
    async def _check_still_referenced_shas(self, shas: set[str]) -> set[str]:
        """返回 `shas` 中仍被 AttachmentRecord 引用的 SHA。

        cleanup 在 commit DB 删除 record 之后、unlink 物理文件之前调用此方法做
        二次确认：commit 与 unlink 的窗口内可能有新 upload 命中同 SHA（blob 还在 →
        跳过写入 → 新 record 入库），此时不能 unlink，否则新 record 悬空。
        """
        if not shas:
            return set()
        async with self._db_factory() as session:
            rows = await session.execute(
                select(AttachmentRecord.sha256)
                .where(AttachmentRecord.sha256.in_(shas))
                .group_by(AttachmentRecord.sha256)
            )
            return {row[0] for row in rows.all()}
```

把 cleanup 中 `await session.commit()` **之后**到 `for _sha, p in pending_unlink:` 之间的代码改为调用该方法：

```python
            await session.commit()  # ← DB 必须先成功提交

        shas_to_check = {sha for sha, _ in pending_unlink}
        still_referenced = await self._check_still_referenced_shas(shas_to_check)

        for sha, p in pending_unlink:
            if sha in still_referenced:
                continue  # 新 upload 在窗口内入库，保留物理文件
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("cleanup unlink failed: %s: %s", p, exc)
```

> 注意 `_check_still_referenced_shas` 是 `AttachmentStore` 实例方法，不是 module-level 函数；`async with self._db_factory()` 必须在 `async with self._db_factory() as session:` 主块**已经退出之后**调用（即在 `cleanup` 方法的外层，不在第一个 with 块内）。改完用 Read 验证缩进。

- [ ] **Step 4：跑测试 PASS**

Run: `pytest tests/unit/store/test_attachments.py -k cleanup -v`
Expected: 全部 PASS。

Run: `pytest tests/unit/store/test_attachments.py -v`
Expected: 全部 PASS。

- [ ] **Step 5：提交**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(store): cleanup commit 后二次确认 SHA 无并发新引用

无锁设计下，commit 与 unlink 之间可能有新 upload 命中同 SHA。物理删除
前再按 SHA 查一次 DB，仍被引用则跳过 unlink，避免新 record 悬空。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11：`/thumbnail` 端点改为按 SHA 找 thumb，缺失 fallback 原图

**Files:**
- Modify: `sebastian/gateway/routes/attachments.py:69-89`
- Modify: `tests/integration/test_gateway_attachments.py`（追加端点测试）

- [ ] **Step 1：写失败测试 — 端点行为**

在 `tests/integration/test_gateway_attachments.py` 末尾追加（沿用文件已有的 client/auth fixture，名字以实际为准；用 Read 确认模式后落实）：

```python
def test_thumbnail_returns_real_thumb_when_present(client_with_auth) -> None:
    """上传 image → /thumbnail 返回真正的缩略图（Content-Type=image/jpeg）。"""
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (1024, 768), color=(0, 100, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    payload = buf.getvalue()

    resp = client_with_auth.post(
        "/api/v1/attachments",
        data={"kind": "image"},
        files={"file": ("photo.jpg", payload, "image/jpeg")},
    )
    assert resp.status_code == 201
    att_id = resp.json()["attachment_id"]

    thumb_resp = client_with_auth.get(f"/api/v1/attachments/{att_id}/thumbnail")
    assert thumb_resp.status_code == 200
    assert thumb_resp.headers["content-type"].startswith("image/jpeg")

    out = Image.open(BytesIO(thumb_resp.content))
    assert max(out.size) <= 256


def test_thumbnail_falls_back_to_blob_when_thumb_missing(client_with_auth, tmp_path) -> None:
    """thumb 不存在但 blob 存在 → fallback 返回原图。"""
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (200, 200), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    payload = buf.getvalue()

    resp = client_with_auth.post(
        "/api/v1/attachments",
        data={"kind": "image"},
        files={"file": ("p.jpg", payload, "image/jpeg")},
    )
    att_id = resp.json()["attachment_id"]
    sha = resp.json()["sha256"]

    # 手动删除 thumb 文件，模拟老数据 / 生成失败
    import sebastian.gateway.state as state

    thumb_abs = state.attachment_store._root_dir / "thumbs" / sha[:2] / f"{sha}.jpg"
    thumb_abs.unlink(missing_ok=True)

    thumb_resp = client_with_auth.get(f"/api/v1/attachments/{att_id}/thumbnail")
    assert thumb_resp.status_code == 200
    # fallback 用 record.mime_type，仍是 image/jpeg
    assert thumb_resp.headers["content-type"].startswith("image/jpeg")
    # 但 body 是原图（尺寸 200×200）
    out = Image.open(BytesIO(thumb_resp.content))
    assert out.size == (200, 200)
```

> **如果文件 fixture 名称不是 `client_with_auth`**：用 Read 看 `tests/integration/test_gateway_attachments.py` 现有测试的 fixture 命名，按现有约定改名。**不要**新建 fixture，复用既有的。

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/integration/test_gateway_attachments.py -k thumbnail -v`
Expected: FAIL（当前端点直接返回原图，第一条会因尺寸 = 1024 而非 ≤256 失败）。

- [ ] **Step 3：改写 `download_thumbnail` 端点**

把 `sebastian/gateway/routes/attachments.py` 第 69-89 行的 `download_thumbnail` 函数替换为：

```python
@router.get("/attachments/{attachment_id}/thumbnail")
async def download_thumbnail(
    attachment_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    store = state.attachment_store
    if store is None:
        raise HTTPException(status_code=503, detail="Attachment store not initialized")
    record = await store.get(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if record.kind != "image":
        raise HTTPException(status_code=400, detail="Thumbnail only available for images")

    # 按 SHA 推算 thumb 路径，逐个尝试 jpg/png/webp 三种扩展名
    _THUMB_EXT_TO_MIME = {
        "jpg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    thumb_dir = store._root_dir / "thumbs" / record.sha256[:2]
    for ext, mime in _THUMB_EXT_TO_MIME.items():
        candidate = thumb_dir / f"{record.sha256}.{ext}"
        if candidate.exists():
            return Response(content=candidate.read_bytes(), media_type=mime)

    # 缺 thumb 时 fallback 返回原图（兼容老数据 / 生成失败）
    blob_path = store.blob_absolute_path(record)
    if not blob_path.exists():
        raise HTTPException(status_code=404, detail="Attachment blob not found")
    return Response(content=blob_path.read_bytes(), media_type=record.mime_type)
```

> **设计取舍**：直接读 `store._root_dir` 是私有属性访问。如果觉得别扭，可以在 `AttachmentStore` 加一个公开方法 `def thumbnail_candidate_paths(record) -> Iterable[tuple[Path, str]]:` 返回三个候选 (path, mime)。但既有代码已有 `store.blob_absolute_path(record)` 的私有访问惯例，本次保持一致即可。

- [ ] **Step 4：跑测试 PASS**

Run: `pytest tests/integration/test_gateway_attachments.py -k thumbnail -v`
Expected: 全部 PASS。

Run（全量集成回归）: `pytest tests/integration/test_gateway_attachments.py -v`
Expected: 全部 PASS。

- [ ] **Step 5：提交**

```bash
git add sebastian/gateway/routes/attachments.py tests/integration/test_gateway_attachments.py
git commit -m "$(cat <<'EOF'
feat(gateway): /thumbnail 端点按 SHA 找 thumb 缺失则 fallback 原图

按 record.sha256 推算 thumbs/<sha[:2]>/<sha>.{jpg,png,webp} 候选；命中
则返回缩略图与对应 MIME；缺失则 fallback 读 blob 用 record.mime_type，
兼容老数据和生成失败场景。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12：更新 `sebastian/store/README.md`

**Files:**
- Modify: `sebastian/store/README.md`

- [ ] **Step 1：用 Read 看下现有 README**

Run: `cat sebastian/store/README.md | head -120`（用 Read 工具更稳）
Expected: 看到现有结构，知道 attachments 这一节在哪。

- [ ] **Step 2：在 attachments 相关段落补充新行为说明**

在 README 中"AttachmentStore"或"附件"章节追加（具体位置看现有结构选最贴切处插入）：

```markdown
### 内容寻址与引用计数

- `blob_path` 由 `f"blobs/{sha[:2]}/{sha}"` 决定。多次上传同内容只占用一份 blob 文件。
- 缩略图同样按 SHA 内容寻址：`thumbs/{sha[:2]}/{sha}.{jpg|png|webp}`。
- `cleanup` 按 SHA 做引用计数：仅当 DB 中没有任何 record 指向该 SHA 时才物理删除 blob/thumb。
- `cleanup` 顺序约束：DB delete 先 commit 成功，commit 后再二次查询确认 SHA 无并发新引用，最后才 unlink 物理文件。物理 unlink 失败仅 warning 不回滚 DB。
- `upload_bytes` 失败回滚同样按 SHA 二次查询：DB commit 失败时，仅在 SHA 引用计数为 0 时才删除本次新写入的 blob/thumb，避免误删并发 upload 已 commit 的共享文件。
- 不变量：任何 DB-committed 的活跃 `AttachmentRecord` 都能通过 `blob_path` 找到磁盘文件；缩略图存在性不是不变量（解码失败 / 老数据时缺失，端点 fallback 处理）。
```

- [ ] **Step 3：提交**

```bash
git add sebastian/store/README.md
git commit -m "$(cat <<'EOF'
docs(store): README 同步 attachment 内容寻址与引用计数清理

补充 blob/thumb SHA 寻址、cleanup DB-first commit + 二次确认顺序、
upload 回滚二次查询、不变量边界。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## 全量回归与 PR 准备

- [ ] **Step 1：全量跑后端测试**

Run: `pytest tests/unit tests/integration -v --timeout=120`
Expected: 全部 PASS。

- [ ] **Step 2：lint / 类型**

Run: `ruff check sebastian/ tests/`
Expected: 无 error。

Run: `ruff format --check sebastian/ tests/`
Expected: 无 diff。

Run: `mypy sebastian/store/attachments.py sebastian/gateway/routes/attachments.py`
Expected: 无 type error。

- [ ] **Step 3：手动启动 gateway 烟测一次**

Run: `uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8823 --reload`
配合 Android 模拟器或 curl 上传一张图、调一次 `/thumbnail`，确认返回值是真正缩略尺寸（用 `Content-Length` 或 PIL 解码验证）。

- [ ] **Step 4：创建 PR**

```bash
git push -u origin HEAD
gh pr create --base main --title "feat(store): 附件去重、引用计数清理与缩略图" --body "$(cat <<'EOF'
## Summary
- `upload_bytes` 同 SHA 跳过 blob 写入；DB 失败回滚先二次查询同 SHA count 再决定是否删本次新写入的物理文件
- `cleanup` 按 SHA 聚合引用计数 + DB-first commit + commit 后二次确认无并发新增引用；修掉历史 placeholder thumb 路径
- 上传图片同步生成 SHA 内容寻址缩略图（256×256，跟随原格式，GIF 转 PNG 第一帧）；EXIF 校正、按格式 mode 转换、DecompressionBomb 防护、解码失败一律降级
- `/thumbnail` 端点按 SHA 找 thumb，缺失 fallback 原图（兼容老数据，无需 migration）

详见 [spec](docs/superpowers/specs/2026-04-29-attachment-storage-dedup-cleanup-thumbnails-design.md)。

## Test plan
- [x] `pytest tests/unit/store/test_attachments.py -v` 全 PASS（含新增 dedup / 缩略图 / cleanup ref counting / 并发回滚 用例）
- [x] `pytest tests/integration/test_gateway_attachments.py -v` 全 PASS（含新增 /thumbnail 真值 + fallback 用例）
- [x] `ruff check`, `ruff format --check`, `mypy` 无 issue
- [x] 手动启动 gateway，上传图片调 /thumbnail 验证返回真缩略图

EOF
)"
```

---

## Self-Review

写完所有任务后，对照 [spec](../../specs/2026-04-29-attachment-storage-dedup-cleanup-thumbnails-design.md) 各章节核对：

- §3.1 blob 去重写入 + 回滚一致性 → Task 7（去重）+ Task 8（回滚二次查询）
- §3.2 cleanup 批内 SHA 聚合 + DB-first commit → Task 9
- §3.2 cleanup commit 后二次确认 → Task 10
- §3.3 缩略图四格式 + EXIF + mode + bomb + dedup → Tasks 3 / 4 / 5 / 6
- §3.4 端点优先 thumb，缺失 fallback → Task 11
- §4 错误处理表格各行 → 在 Tasks 3-10 的测试用例里逐条覆盖
- §5 数据迁移：依赖 fallback 路径，由 Task 11 的 fallback 测试覆盖
- §6 测试策略 → 在 Tasks 3-11 的 Step 1 中体现
- §7 文件改动清单 → Tasks 1-12 全覆盖（含 README）
- §8 不变量 → Tasks 7-10 共同保证

**No placeholder check**：所有 step 都有完整代码或精确命令；无 "TBD"/"TODO"/"add appropriate ..."；类型与方法签名跨任务一致（`_maybe_generate_thumbnail` 在 Tasks 3-6 一致演进）。

