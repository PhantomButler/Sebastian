# Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Android App 发送图片与 `.txt/.md/.csv/.json/.log` 文本文件附件，并让后端持久化、校验、投影到 LLM 上下文、恢复到 timeline 历史。

**Architecture:** REST 负责附件上传和 turn 发起，SSE 协议保持不变。后端新增 AttachmentStore 管理 `<data_dir>/attachments` blob 与 SQLite metadata，turn API 将 `attachment_ids` 写入同一 exchange 的 timeline。Android 区分发送前 `PendingAttachment` 与历史 `ContentBlock.ImageBlock/FileBlock`，Composer 左下角附件按钮根据 provider 能力拦截图片选择。

**Tech Stack:** Python 3.12, FastAPI `UploadFile`, SQLAlchemy async, SQLite, pytest, Kotlin, Jetpack Compose, Retrofit/OkHttp multipart, Android Photo Picker, SAF, Coil.

---

## Source Spec

- `docs/superpowers/specs/2026-04-27-attachments-design.md`

## File Structure

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `sebastian/config/__init__.py` | Modify | 新增 `attachments_dir` property；`ensure_data_dir()` 创建 attachments 子目录 |
| `sebastian/store/models.py` | Modify | 新增 `AttachmentRecord` ORM 模型 |
| `sebastian/store/attachments.py` | Create | AttachmentStore：上传校验、blob 原子写入、metadata CRUD、状态流转、清理 |
| `sebastian/store/session_timeline.py` | Modify | 支持 `kind="attachment"` 写入与 context 读取 |
| `sebastian/store/session_context.py` | Modify | `attachment` timeline 投影为 provider messages |
| `sebastian/store/session_store.py` | Modify | 提供跨 timeline + attachment 状态更新的事务入口 |
| `sebastian/gateway/routes/attachments.py` | Create | `POST/GET /attachments` 与 thumbnail 下载 |
| `sebastian/gateway/routes/turns.py` | Modify | `SendTurnRequest.attachment_ids`，主对话 turn 附件校验和写入 |
| `sebastian/gateway/routes/sessions.py` | Modify | session turn / sub-agent initial turn 支持附件 |
| `sebastian/gateway/app.py` | Modify | 注册 attachments router，初始化 AttachmentStore |
| `sebastian/gateway/state.py` | Modify | 暴露 `attachment_store` |
| `sebastian/llm/catalog/builtin_providers.json` | Modify | 为内置模型补 `supports_image_input` / `supports_text_file_input` |
| `sebastian/llm/catalog/loader.py` | Modify | 读取并默认化模型输入能力字段 |
| `sebastian/llm/registry.py` | Modify | Resolved provider/model DTO 暴露输入能力 |
| `sebastian/llm/anthropic.py` | Modify | 支持 Anthropic image content blocks 输入 |
| `tests/unit/store/test_attachments.py` | Create | AttachmentStore 单元测试 |
| `tests/unit/store/test_session_context_attachments.py` | Create | timeline → provider context 投影测试 |
| `tests/integration/test_gateway_attachments.py` | Create | FastAPI 上传/turn 集成测试 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt` | Modify | 新增 `ImageBlock` / `FileBlock` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/AttachmentModels.kt` | Create | `PendingAttachment` / `AttachmentKind` / `AttachmentUploadState` / `ModelInputCapabilities` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AttachmentDto.kt` | Create | 上传响应 DTO |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TurnDto.kt` | Modify | `SendTurnRequest.attachmentIds` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt` | Modify | 解析 resolved provider/model 输入能力 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentDto.kt` | Modify | Agent/session 页面需要时透传能力字段 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt` | Modify | 合并同 exchange 的 `user_message + attachment` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt` | Modify | multipart upload endpoint |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt` | Modify | sendTurn/sendSessionTurn 支持附件 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt` | Modify | 上传附件并发送 turn |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | Modify | pending attachment 状态机、能力拦截、发送流程 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentSlot.kt` | Create | 左下角附件按钮与「图片/文件」菜单 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentPreviewBar.kt` | Create | 发送前附件预览条 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/Composer.kt` | Modify | 注入附件 slot 与预览 slot，发送空文本+附件 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt` | Modify | 渲染 ImageBlock/FileBlock |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AttachmentBlocks.kt` | Create | 历史消息中的图片缩略图和文件卡片 |
| `ui/mobile-android/app/src/test/...` | Modify/Create | TimelineMapper、ChatViewModel 附件状态单测 |
| README files | Modify | `sebastian/store/README.md`、`sebastian/gateway/README.md`、`ui/mobile-android/README.md`、data/ui/composer README 同步 |

## Task 1: 后端 AttachmentRecord 与目录配置

**Files:**
- Modify: `sebastian/config/__init__.py`
- Modify: `sebastian/store/models.py`
- Create: `tests/unit/store/test_attachments.py`

- [ ] **Step 1: 写失败测试：attachments_dir 派生路径**

在 `tests/unit/store/test_attachments.py` 创建测试，覆盖：

```python
from pathlib import Path

from sebastian.config import Settings


def test_attachments_dir_lives_under_user_data_dir(tmp_path: Path) -> None:
    settings = Settings(sebastian_data_dir=str(tmp_path))
    assert settings.attachments_dir == tmp_path / "data" / "attachments"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/store/test_attachments.py::test_attachments_dir_lives_under_user_data_dir -v`

Expected: FAIL，`Settings` 没有 `attachments_dir`。

- [ ] **Step 3: 实现 `attachments_dir`**

在 `sebastian/config/__init__.py` 的 `Settings` 类新增：

```python
    @property
    def attachments_dir(self) -> Path:
        return self.user_data_dir / "attachments"
```

在 `ensure_data_dir()` 中创建：

```python
settings.attachments_dir.mkdir(parents=True, exist_ok=True)
(settings.attachments_dir / "blobs").mkdir(parents=True, exist_ok=True)
(settings.attachments_dir / "thumbs").mkdir(parents=True, exist_ok=True)
(settings.attachments_dir / "tmp").mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: 新增 AttachmentRecord ORM 模型**

在 `sebastian/store/models.py` 新增：

```python
class AttachmentRecord(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    blob_path: Mapped[str] = mapped_column(String, nullable=False)
    text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    attached_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    orphaned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_attachments_status_created", "status", "created_at"),
        Index("ix_attachments_session", "agent_type", "session_id"),
        Index("ix_attachments_sha256", "sha256"),
    )
```

- [ ] **Step 5: 跑路径测试**

Run: `pytest tests/unit/store/test_attachments.py -v`

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add sebastian/config/__init__.py sebastian/store/models.py tests/unit/store/test_attachments.py
git commit -m "feat(store): 新增附件目录配置与数据模型"
```

## Task 2: AttachmentStore 上传校验与 blob 写入

**Files:**
- Create: `sebastian/store/attachments.py`
- Modify: `tests/unit/store/test_attachments.py`

- [ ] **Step 1: 写失败测试：文本文件上传成功**

测试构造 `AttachmentStore(root_dir=tmp_path / "attachments", db_factory=db_session_factory)`，上传 `notes.md` bytes，断言：

- 返回 `kind == "text_file"`
- `status == "uploaded"`
- blob 存在于 `blobs/<sha256-prefix>/<sha256>`
- `text_excerpt` 包含 `# title`

- [ ] **Step 2: 写失败测试：非法后缀 / 非 UTF-8 / 超大小**

添加 3 个测试：

```python
async def test_text_file_rejects_unsupported_extension(...)
async def test_text_file_rejects_non_utf8(...)
async def test_text_file_rejects_over_size(...)
```

Expected: 抛出 `ValueError` 或项目内具体异常；实现时保持异常类型稳定，Gateway 再映射为 HTTP 400。

- [ ] **Step 3: 写失败测试：文本 MIME 必须在白名单内**

添加 2 个测试：

```python
async def test_text_file_accepts_supported_mime_and_extension(...)
async def test_text_file_rejects_unsupported_mime_even_with_supported_extension(...)
```

第二个测试使用 `filename="notes.md"`、`content_type="application/pdf"`、UTF-8 bytes，期望拒绝。这样防止实现只看后缀和解码。

- [ ] **Step 4: 写失败测试：图片 MIME 白名单**

测试 `image/jpeg` 成功，`image/svg+xml` 失败。

- [ ] **Step 5: 写失败测试：read_text_content 返回完整内容而非 excerpt**

上传超过 `TEXT_EXCERPT_CHARS` 的 `.md` 文件，断言：

- record 的 `text_excerpt` 被截断。
- `AttachmentStore.read_text_content(record)` 返回完整文本。

LLM context 投影必须使用 `read_text_content()`，不能使用 `text_excerpt`。

- [ ] **Step 6: 实现 AttachmentStore**

`sebastian/store/attachments.py` 结构：

```python
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from sebastian.store.models import AttachmentRecord

ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log"}
ALLOWED_TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/x-ndjson",
    "text/x-log",
    "application/octet-stream",  # SAF/providers often omit text MIME; extension + UTF-8 still required.
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
TEXT_EXCERPT_CHARS = 2000


@dataclass(slots=True)
class UploadedAttachment:
    id: str
    kind: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    text_excerpt: str | None


class AttachmentStore:
    ...
```

方法：

- `upload_bytes(*, filename, content_type, kind, data) -> UploadedAttachment`
- `get(attachment_id) -> AttachmentRecord | None`
- `validate_attachable(attachment_ids) -> list[AttachmentRecord]`（只读校验：存在、status=uploaded、未绑定 session）
- `mark_attached(attachment_ids, agent_type, session_id) -> list[AttachmentRecord]`
- `mark_session_orphaned(agent_type, session_id) -> int`
- `cleanup(now=None) -> int`
- `blob_absolute_path(record) -> Path`
- `read_text_content(record) -> str`（读取完整文本文件 blob，不能使用 `text_excerpt` 作为 LLM 输入）

Blob 写入要求：先写 `tmp/<uuid>`，fsync 可选，最后 `os.replace(tmp, final)`。

文本文件校验必须同时检查后缀、MIME 与 UTF-8 解码：允许的后缀见 `ALLOWED_TEXT_EXTENSIONS`，允许的 MIME 见 `ALLOWED_TEXT_MIME_TYPES`。如果 MIME 缺失或为 `application/octet-stream`，仍必须通过后缀 + UTF-8 检查；如果 MIME 是明确不支持的值（如 `application/pdf`），即使后缀是 `.md` 也拒绝。

- [ ] **Step 7: 运行单元测试**

Run: `pytest tests/unit/store/test_attachments.py -v`

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "feat(store): 实现附件上传校验与 blob 存储"
```

## Task 3: Gateway attachments API

**Files:**
- Create: `sebastian/gateway/routes/attachments.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/state.py`
- Create: `tests/integration/test_gateway_attachments.py`

- [ ] **Step 1: 写失败测试：POST /attachments 上传文本文件**

使用 FastAPI TestClient/AsyncClient 走真实路由：

```python
response = client.post(
    "/api/v1/attachments",
    files={"file": ("notes.md", b"# hello", "text/markdown")},
    data={"kind": "text_file"},
    headers=auth_headers,
)
assert response.status_code == 200
assert response.json()["kind"] == "text_file"
```

- [ ] **Step 2: 写失败测试：GET /attachments/{id} 下载**

上传后 GET，断言 `status_code == 200`，body 等于原始 bytes，`content-type` 合理。

- [ ] **Step 3: 实现 router**

`attachments.py`：

- `POST /attachments`
- `GET /attachments/{attachment_id}`
- `GET /attachments/{attachment_id}/thumbnail`

上传使用 `UploadFile`：

```python
@router.post("/attachments")
async def upload_attachment(
    kind: Literal["image", "text_file"] = Form(...),
    file: UploadFile = File(...),
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    data = await file.read()
    uploaded = await state.attachment_store.upload_bytes(...)
    return {...}
```

- [ ] **Step 4: 注册 state 与 app**

在 `state.py` 新增 `attachment_store: AttachmentStore | None`。在 `app.py` lifespan 初始化 `AttachmentStore(settings.attachments_dir, db_factory)`，并 `include_router(attachments.router, prefix="/api/v1")`。

- [ ] **Step 5: 跑集成测试**

Run: `pytest tests/integration/test_gateway_attachments.py -v`

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/attachments.py sebastian/gateway/app.py sebastian/gateway/state.py tests/integration/test_gateway_attachments.py
git commit -m "feat(gateway): 新增附件上传与下载 API"
```

## Task 4: Turn API 写入附件 timeline

**Files:**
- Modify: `sebastian/gateway/routes/turns.py`
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `sebastian/store/session_store.py`
- Modify: `sebastian/store/session_timeline.py`
- Modify: `sebastian/store/attachments.py`
- Modify: `tests/integration/test_gateway_attachments.py`

- [ ] **Step 1: 写失败测试：发送 turn 携带附件写入同 exchange**

测试流程：

1. 上传 `notes.md`。
2. `POST /api/v1/turns` body `{ "content": "总结", "session_id": "...", "attachment_ids": ["..."] }`。
3. 查询 session detail。
4. 断言 timeline 有 `user_message` 和 `attachment`，二者 `exchange_id` 相同。

- [ ] **Step 2: 写失败测试：空文本 + 附件允许发送**

body `{ "content": "", "attachment_ids": ["..."] }` 应 200。

- [ ] **Step 3: 写失败测试：空文本 + 空附件拒绝**

body `{ "content": "", "attachment_ids": [] }` 应 400。

- [ ] **Step 4: 写失败测试：单 turn 超过 5 个附件拒绝且不写 timeline**

上传 6 个 `.txt` 附件，调用 turn API，期望：

- HTTP 400。
- session timeline 没有新增 `user_message` / `attachment`。
- 6 个 attachment 仍是 `uploaded`。

- [ ] **Step 5: 写失败测试：不支持图片时拒绝且不写 timeline**

设置当前 resolved provider/model `supports_image_input=False`，上传图片并发送 turn，期望：

- HTTP 400。
- 不调用 LLM。
- 不分配 exchange。
- 不写 `user_message` / `attachment` timeline item。
- 图片 attachment 仍是 `uploaded`。

- [ ] **Step 6: 写失败测试：已被引用的 attachment 再次使用返回 409**

同一个 `attachment_id` 成功发送一次后，再次发送，期望 409，且第二次不写 timeline。

- [ ] **Step 7: 扩展 SendTurnRequest**

`turns.py`：

```python
class SendTurnRequest(BaseModel):
    content: str = ""
    session_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
```

`sessions.py` 复用同样字段。同步修改 `CreateAgentSessionBody`，不能保留 `Field(min_length=1)`：

```python
class CreateAgentSessionBody(BaseModel):
    content: str = ""
    session_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
```

Sub-Agent 首条消息也支持「空文本 + 附件」，统一由共享 helper 做 `content.strip() or attachment_ids` 联合非空校验。

- [ ] **Step 8: 抽出共享 helper**

在 `sessions.py` 或新 helper 中实现：

```python
async def _persist_user_turn_with_attachments(
    *,
    session: Session,
    content: str,
    attachment_ids: list[str],
) -> tuple[str, int]:
    ...
```

行为：

- 校验 content/attachments 非空。
- 校验 attachment 数量 <= 5。
- 调 `AttachmentStore.validate_attachable(attachment_ids)`，确认全部存在、`status=uploaded`、未绑定 session。
- 校验当前 resolved provider/model 对图片附件的支持；不支持时立即 400。
- 对文本附件调用 `AttachmentStore.read_text_content(record)` 读取完整内容，使用 `TokenEstimator.estimate_text()` 做 P0 token 预算检查；超预算时立即 400。此检查必须在写 timeline 前完成，不能推迟到 context projection。
- 以上任何校验失败时，不能分配 exchange，不能写 timeline，不能更新 attachment 状态。
- 校验通过后，进入单一 DB transaction：分配 exchange、写 `user_message`、写每个 `attachment` item、将 attachment 状态更新为 `attached`。

原子性要求：timeline 写入和 attachment status transition 必须同成同败。不要先写 timeline 再调用可能失败的 `mark_attached()`。

事务入口应放在 `SessionStore`，而不是 `AttachmentStore`。原因：timeline 写入属于 `SessionTimelineStore` / `SessionStore` 职责，`AttachmentStore` 不应反向依赖 timeline。推荐新增 facade 方法：

```python
async def append_user_turn_with_attachments(
    self,
    *,
    session_id: str,
    agent_type: str,
    content: str,
    attachment_records: list[AttachmentRecord],
) -> tuple[str, int]:
    ...
```

该方法在一个 SQLAlchemy transaction 内直接操作 `sessions.next_exchange_index`、`sessions.next_item_seq`、`SessionItemRecord` 和 `AttachmentRecord`。`AttachmentStore` 只负责预校验、blob 读取和非 timeline 的 attachment CRUD。

- [ ] **Step 9: 调整 BaseAgent 入口避免重复写 user_message**

当前 `BaseAgent.run_streaming(content, session.id)` 会自行写用户消息。实现时需要引入一个最小改造，避免 turn API 预写附件 timeline 后 BaseAgent 再写一条 user_message。

推荐接口：

```python
await agent.run_streaming(
    content,
    session.id,
    preallocated_exchange=(exchange_id, exchange_index),
    persist_user_message=False,
)
```

`persist_user_message=False` 必须同时跳过三件事：

1. 不执行 `messages.append({"role": "user", "content": user_message})`，因为 `get_context_messages()` 已经从 DB 读到了预写的 user turn。
2. 不执行 `allocate_exchange_for_turn()`，必须沿用 `preallocated_exchange`。
3. 不执行 `self._session_store.append_message(...)`，否则 timeline 会多一条 user_message。

`_stream_inner(...)` 仍必须接收并使用传入的 `exchange_id/exchange_index`，确保 assistant/tool 输出与预写 user turn 属于同一个 exchange。

若改动过大，替代方案是在 BaseAgent 增加 `run_streaming_from_persisted_user_turn(...)`。不要用事后删除重复消息的补丁方案。

- [ ] **Step 10: 跑集成测试**

Run: `pytest tests/integration/test_gateway_attachments.py -v`

Expected: PASS。

- [ ] **Step 11: Commit**

```bash
git add sebastian/gateway/routes/turns.py sebastian/gateway/routes/sessions.py sebastian/store/session_store.py sebastian/store/session_timeline.py sebastian/core/base_agent.py tests/integration/test_gateway_attachments.py
git commit -m "feat(gateway): turn 请求支持附件 timeline 写入"
```

## Task 5: Provider 能力与 context 投影

**Files:**
- Modify: `sebastian/llm/catalog/builtin_providers.json`
- Modify: `sebastian/llm/catalog/loader.py`
- Modify: `sebastian/llm/registry.py`
- Modify: `sebastian/store/session_context.py`
- Modify: `sebastian/store/session_store.py`
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/llm/anthropic.py`
- Create: `tests/unit/store/test_session_context_attachments.py`

- [ ] **Step 1: 写失败测试：文本文件投影为边界清晰的 text block**

构造 timeline items：`user_message + attachment(text_file)`，AttachmentStore `read_text_content()` 返回文件完整内容 `hello`，断言 Anthropic projection 中 content list 包含：

````text
用户上传了文本文件：notes.md
```notes.md
hello
```
````

- [ ] **Step 2: 写失败测试：投影使用完整文本，不使用 text_excerpt**

上传一个超过 `TEXT_EXCERPT_CHARS` 的文本文件，record 的 `text_excerpt` 是截断预览。构造 timeline 并投影，断言 LLM content 包含完整尾部文本。这样确保 `text_excerpt` 只用于 UI 预览。

- [ ] **Step 3: 写失败测试：文本文件超过 token 预算时拒绝**

构造超出 P0 token 预算的文本附件，调用 turn helper，期望 400/明确异常，且不写 timeline。实现应在 Task 4 的共享 turn helper 中 import `sebastian.context.estimator.TokenEstimator` 并调用 `estimate_text()`；不要把此检查放到 context projection 才执行，也不要自动摘要。

- [ ] **Step 4: 写失败测试：图片不支持时拒绝**

当前 resolved provider `supports_image_input=False` 且 attachment kind=image 时，turn helper 返回 HTTP 400 或 context builder 抛明确异常。

- [ ] **Step 5: 增加 catalog 能力字段**

内置视觉模型设 `supports_image_input: true`，文本文件默认 true。非视觉模型 false。Custom model CRUD 需要允许用户配置此字段；若表结构暂不加列，P0 可先在 model spec JSON 层处理内置模型，自定义模型默认为 false。

- [ ] **Step 6: 扩展 registry resolved DTO**

在返回 Android binding/resolved model 时包含：

```json
{
  "supports_image_input": false,
  "supports_text_file_input": true
}
```

- [ ] **Step 7: 实现 `attachment` context 投影**

附件投影需要读取 blob 内容，因此不能继续让 `build_context_messages()` 保持纯同步函数。采用方案 A：

- `build_context_messages()` 改为 `async def`。
- 新增参数 `attachment_store: AttachmentStore | None = None`。
- 遇到 `kind="attachment"` 时，必须通过 `attachment_store.get(id)` + `read_text_content(record)` 或 `blob_absolute_path(record)` 读取真实 blob。
- 如果 timeline 中存在 attachment item 但 `attachment_store is None`，抛明确异常，不静默忽略。
- `SessionStore.get_context_messages()` 已经是 async，改为 `return await build_context_messages(...)`。
- `BaseAgent.__init__()` 增加 `attachment_store: AttachmentStore | None = None`，保存为 `self._attachment_store`。
- `BaseAgent.run_streaming()` 调 `get_context_messages(..., attachment_store=self._attachment_store)`。
- `gateway/app.py` 初始化 agent instances 时把 `state.attachment_store` 注入 Sebastian 和 sub-agent。

在 `session_context.py` 中实现：

- Anthropic：user message content 从 string 升级为 content block list。
- 文本文件：追加 `{ "type": "text", "text": fenced_content }`。
- 图片：追加 `{ "type": "image", "source": { "type": "base64", "media_type": "...", "data": "..." } }`。
- OpenAI-compatible：P0 对图片默认拒绝，文本文件作为普通 text。

- [ ] **Step 8: Anthropic provider 透传 image blocks**

`anthropic.py` 当前把 messages 原样给 SDK；确认 content block list 已符合 SDK 格式即可。若 SDK 类型检查需要，保持 dict 格式。

- [ ] **Step 9: 跑单元测试**

Run: `pytest tests/unit/store/test_session_context_attachments.py -v`

Expected: PASS。

- [ ] **Step 10: Commit**

```bash
git add sebastian/llm/catalog/builtin_providers.json sebastian/llm/catalog/loader.py sebastian/llm/registry.py sebastian/store/session_context.py sebastian/store/session_store.py sebastian/core/base_agent.py sebastian/gateway/app.py sebastian/llm/anthropic.py tests/unit/store/test_session_context_attachments.py
git commit -m "feat(llm): 支持附件 provider 能力与上下文投影"
```

## Task 6: Android 数据层与 timeline hydration

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/AttachmentModels.kt`
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AttachmentDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TurnDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`
- Test: `ui/mobile-android/app/src/test/.../TimelineMapperTest.kt`

- [ ] **Step 1: 写失败测试：TimelineMapper 合并 user_message + attachment**

构造同一 `exchange_id` 下的 `TimelineItemDto(kind="user_message")` 和 `TimelineItemDto(kind="attachment")`，断言输出一条 `Message(role=USER)` 且 `blocks` 包含 `ImageBlock` 或 `FileBlock`。

当前 `TimelineMapper.kt` 是单 pass 遍历，遇到 `user_message` 会立即输出一条 message。实现附件合并时不能只在现有 `when` 中追加 `attachment` 分支；需要先按 `exchangeId` 分组或做两 pass。推荐：

1. `sortedBy(seq)` 后按 `exchangeId ?: "seq-$seq"` 分组。
2. 对每个 group：若包含 `user_message`，合并该 group 内的 `attachment` items 为同一条 user message blocks。
3. assistant/tool/thinking 仍沿用现有按 `(assistantTurnId, providerCallIndex)` 分组逻辑。

- [ ] **Step 2: 实现 ContentBlock 新类型**

按 spec 增加 `ImageBlock` / `FileBlock`，更新 `isDone`。

- [ ] **Step 3: 新增发送前模型**

创建 `AttachmentModels.kt`，包含：

- `PendingAttachment`
- `AttachmentKind`
- `AttachmentUploadState`
- `ModelInputCapabilities`

- [ ] **Step 4: 写失败测试：后端能力字段映射到 ModelInputCapabilities**

构造 `AgentBindingDto` / resolved DTO JSON：

```json
{
  "resolved": {
    "supports_image_input": true,
    "supports_text_file_input": true
  }
}
```

断言 mapper 输出 `ModelInputCapabilities(supportsImageInput=true, supportsTextFileInput=true)`。没有字段时默认 `false/true`。

- [ ] **Step 5: 实现 provider 能力 DTO 解析**

在 `AgentBindingDto.kt`（以及 Chat 页面实际读取 binding 的 DTO 路径）加入：

```kotlin
@param:Json(name = "supports_image_input") val supportsImageInput: Boolean = false,
@param:Json(name = "supports_text_file_input") val supportsTextFileInput: Boolean = true,
```

Repository/ViewModel 需要把 resolved binding 转为 `ModelInputCapabilities`，存到 `ChatUiState` 或 `ChatViewModel` 当前状态中。不要只在测试里手动塞布尔值。

- [ ] **Step 6: 新增 Attachment DTO 和 multipart API**

`ApiService.kt`：

```kotlin
@Multipart
@POST("api/v1/attachments")
suspend fun uploadAttachment(
    @Part("kind") kind: RequestBody,
    @Part file: MultipartBody.Part,
): AttachmentUploadResponseDto
```

- [ ] **Step 7: 扩展 ChatRepository**

接口：

```kotlin
suspend fun uploadAttachment(pending: PendingAttachment): Result<PendingAttachment>
suspend fun sendTurn(sessionId: String?, content: String, attachmentIds: List<String>): Result<String>
suspend fun sendSessionTurn(sessionId: String, content: String, attachmentIds: List<String>): Result<Unit>
```

- [ ] **Step 8: 实现 Repository multipart upload**

从 `ContentResolver` 读取 Uri stream，构造 `RequestBody`。上传成功后返回 `PendingAttachment.copy(uploadState=Uploaded, attachmentId=...)`。

- [ ] **Step 9: 跑 Android 单元测试**

Run: `cd ui/mobile-android && ./gradlew test`

Expected: PASS。

- [ ] **Step 10: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/AttachmentModels.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AttachmentDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TurnDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt ui/mobile-android/app/src/test
git commit -m "feat(android): 增加附件数据模型与上传 API"
```

## Task 7: Android Composer 附件 UI 与发送状态机

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentSlot.kt`
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentPreviewBar.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/Composer.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`
- Test: `ui/mobile-android/app/src/test/.../ChatViewModelAttachmentTest.kt`

- [ ] **Step 1: 写 ViewModel 测试：不支持图片时只发 effect**

通过 repository/DTO hydration 给 `ChatViewModel` 当前 binding 注入 `ModelInputCapabilities(supportsImageInput=false)`，调用 `onAttachmentMenuImageSelected()`，断言发出 Toast effect，不进入 picker request 状态。测试不能直接绕过 hydration 手动塞裸布尔值。

- [ ] **Step 2: 写 ViewModel 测试：空文本 + 附件可发送**

设置一个 `PendingAttachment(uploadState=Uploaded, attachmentId="att_1")`，调用 send，断言 repository 收到 `content=""` 和 `attachmentIds=["att_1"]`。

- [ ] **Step 3: 写 ViewModel 测试：选择第 6 个附件时拒绝**

已有 5 个 pending attachments 时，再选择一个文件，期望 Toast/错误 effect，`pendingAttachments` 不增加。

- [ ] **Step 4: 写 ViewModel 测试：不支持后缀不会加入 PendingAttachment**

模拟 SAF 返回 `report.pdf` 或未知后缀，期望 Toast/错误 effect，`pendingAttachments` 不增加。

- [ ] **Step 5: 实现 AttachmentSlot**

UI：

- 左下角 icon button。
- 点击弹出菜单：图片 / 文件。
- 图片项调用 ViewModel 能力检查。
- 文件项打开 SAF。配置 MIME 为 `text/plain`, `text/markdown`, `text/csv`, `application/json`, `application/octet-stream`；选择返回后仍必须按文件名后缀 `.txt/.md/.csv/.json/.log` 做二次校验。

- [ ] **Step 6: 实现 AttachmentPreviewBar**

展示：

- 图片本地缩略图或文件图标。
- 文件名、大小。
- 上传中 progress。
- 失败原因、重试、移除。

- [ ] **Step 7: 改 Composer 签名**

新增 props：

```kotlin
pendingAttachments: List<PendingAttachment>
attachmentSlot: @Composable (() -> Unit)? = null
attachmentPreviewSlot: @Composable (() -> Unit)? = null
onSend: (String, List<PendingAttachment>) -> Unit
```

发送按钮启用条件：`text.isNotBlank() || pendingAttachments.isNotEmpty()`。

- [ ] **Step 8: ChatViewModel 串联上传与 turn**

发送流程：

1. 找出未上传附件，逐个 upload。
2. 任一失败则保留 Composer 状态，不发送 turn。
3. 全部 uploaded 后调用 sendTurn/sendSessionTurn。
4. 成功后清空 pending attachments 和文本。
5. 选择附件时 enforce 单 turn 最多 5 个，后端仍保留 400 兜底。

- [ ] **Step 9: 跑 Android 测试与 Kotlin 编译**

Run:

```bash
cd ui/mobile-android
./gradlew test
./gradlew :app:compileDebugKotlin
```

Expected: PASS。

- [ ] **Step 10: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentSlot.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentPreviewBar.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/Composer.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt ui/mobile-android/app/src/test
git commit -m "feat(android): 接入 Composer 附件选择与发送状态"
```

## Task 8: Android 历史消息附件渲染

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AttachmentBlocks.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt`

- [ ] **Step 1: 实现 ImageBlock UI**

使用 Coil `AsyncImage` 加载 `thumbnailUrl ?: downloadUrl`。点击大图预览可先用系统浏览器/intent 打开鉴权 URL；若鉴权 header 不支持，P0 点击只下载/提示。

- [ ] **Step 2: 实现 FileBlock UI**

文件卡片显示文件名、大小、后缀、`textExcerpt`。点击下载由后续任务决定，P0 可先打开 `downloadUrl`。

- [ ] **Step 3: StreamingMessage 分发 block 类型**

在 `when (block)` 中加入：

```kotlin
is ContentBlock.ImageBlock -> ImageAttachmentBlock(block)
is ContentBlock.FileBlock -> FileAttachmentBlock(block)
```

- [ ] **Step 4: 编译验证**

Run: `cd ui/mobile-android && ./gradlew :app:compileDebugKotlin`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AttachmentBlocks.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt
git commit -m "feat(android): 渲染历史消息附件块"
```

## Task 9: 清理任务、Session 删除联动与文档同步

**Files:**
- Modify: `sebastian/store/attachments.py`
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `sebastian/store/README.md`
- Modify: `sebastian/gateway/README.md`
- Modify: `sebastian/gateway/routes/README.md`
- Modify: `ui/mobile-android/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 写后端测试：删除 session 后附件 orphaned**

上传并 attach 附件，删除 session，断言 attachment status 为 `orphaned`。

- [ ] **Step 2: 写后端测试：cleanup 不删除 attached**

构造 `uploaded` 过期、`orphaned` 过期、`attached` 过期三条记录。运行 cleanup，断言只删除前两类。

- [ ] **Step 3: 实现 `mark_session_orphaned()` 和 `cleanup()`**

`cleanup()` 删除 DB 记录前先删除 blob；blob 不存在时不失败。删除缩略图同理。

- [ ] **Step 4: Session 删除路由调用 orphan 标记**

在 `delete_session()` 中删除 session 前/后调用 `attachment_store.mark_session_orphaned(session.agent_type, session.id)`。

- [ ] **Step 5: README 同步**

更新各 README 的目录职责、修改导航、API 表和 Composer 说明。

- [ ] **Step 6: CHANGELOG**

`CHANGELOG.md` 的 `[Unreleased]` → `### Added` 增加用户视角条目：

```markdown
- Android App 支持在对话中发送图片和 `.txt/.md/.csv/.json/.log` 文本文件附件。
```

- [ ] **Step 7: 全量相关验证**

Run:

```bash
pytest tests/unit/store/test_attachments.py tests/unit/store/test_session_context_attachments.py tests/integration/test_gateway_attachments.py -v
cd ui/mobile-android && ./gradlew test && ./gradlew :app:compileDebugKotlin
ruff check sebastian/ tests/
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add sebastian/store/attachments.py sebastian/gateway/routes/sessions.py sebastian/store/README.md sebastian/gateway/README.md sebastian/gateway/routes/README.md ui/mobile-android/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/README.md CHANGELOG.md tests/unit/store/test_attachments.py
git commit -m "chore: 同步附件清理与文档"
```

## Final Verification

- [ ] Run backend tests:

```bash
pytest tests/unit/store/test_attachments.py tests/unit/store/test_session_context_attachments.py tests/integration/test_gateway_attachments.py -v
```

- [ ] Run backend lint:

```bash
ruff check sebastian/ tests/
```

- [ ] Run Android tests and compile:

```bash
cd ui/mobile-android
./gradlew test
./gradlew :app:compileDebugKotlin
```

- [ ] Manual Android smoke test:

1. 启动 gateway。
2. Android 连接到 `http://10.0.2.2:8823`。
3. 当前模型不支持图片时，点附件 → 图片，Toast 出现且不打开 picker。
4. 选择 `.md` 文件，发送空文本 + 文件，确认 assistant 可读文件内容。
5. 选择图片并切换到支持视觉的模型，发送后历史恢复仍显示图片缩略图。
6. 删除 session，确认后端附件状态转为 `orphaned`。
