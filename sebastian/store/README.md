# store — 持久化层

> 上级索引：[sebastian/](../README.md)

## 模块职责

SQLite 是 session 数据的唯一主存储（通过 `SessionStore` facade 访问）。`SessionStore` 在生产模式下（`db_factory` 已注入）将读写委托给四个 SQLite helper：`SessionRecordsStore`、`SessionTimelineStore`、`SessionTaskStore`、`SessionTodoStore`。文件系统 JSON 路径（`sessions_dir`）已 **deprecated**，仅作历史兼容保留。

（`IndexStore` 和 `index_store.py` 已于迁移后删除，session 列表和子 session 查询均由 `SessionStore` 管理。）

## 目录结构

```
store/
├── __init__.py              # 模块入口（空导出，按需 import 子模块）
├── database.py              # SQLAlchemy async engine 初始化，Base、get_db（async session factory）
├── models.py                # SQLAlchemy ORM 模型：EventRecord、ApprovalRecord、TaskRecord、LLMAccountRecord、LLMCustomModelRecord、AgentLLMBindingRecord 等
├── session_store.py         # 主 facade：SessionStore，委托给下方四个 SQLite helper
├── session_records.py       # SessionRecordsStore：sessions 表 CRUD（create / get / list / update）
├── session_timeline.py      # SessionTimelineStore：timeline_items 表追加与查询（append_message / get_context）
├── session_context.py       # build_context_messages()（async）：将 timeline_items 投影为 provider messages；支持 Anthropic 和 OpenAI-format 附件投影；OpenAI 路径文本文件以 fenced text 注入，图片以 chat-completions `image_url` content block 注入
├── session_tasks.py         # SessionTaskStore：tasks / checkpoints 表 CRUD
├── session_todos.py         # SessionTodoStore：per-session todos 的 SQLite 读写
├── event_log.py             # EventLog：将 Event 对象追加写入 SQLite events 表，用于历史查询
├── task_store.py            # [DEPRECATED] TaskStore：原文件系统 task 写入辅助，已由 session_tasks.py 替代
├── attachments.py           # AttachmentStore：附件 blob 存储与状态管理（image / text_file / download，upload / mark_attached / mark_session_orphaned / cleanup，含 tmp/ 孤文件 GC）
├── todo_store.py            # TodoStore：per-session todos，委托给 SessionTodoStore（SQLite-only）
└── migrations/
    └── __init__.py          # Alembic 迁移脚本目录（schema 变更在此新增 migration）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| Session 元数据读写（create / get / list） | [session_records.py](session_records.py) |
| 消息历史读写（append / get_context） | [session_timeline.py](session_timeline.py) |
| timeline → provider messages 投影（含附件） | [session_context.py](session_context.py) 的 `build_context_messages()`（async，需传 `attachment_store`）；支持 Anthropic 和 OpenAI-format 附件投影 |
| Task / Checkpoint SQLite 读写 | [session_tasks.py](session_tasks.py) |
| Per-session todos SQLite 读写 | [session_todos.py](session_todos.py) |
| SessionStore facade 统一入口 | [session_store.py](session_store.py) |
| 事件历史查询 | [event_log.py](event_log.py) + [models.py](models.py) 的 `EventRecord` |
| Approval 持久化结构 | [models.py](models.py) 的 `ApprovalRecord` |
| LLM Account 配置持久化（含加密 API Key） | [models.py](models.py) 的 `LLMAccountRecord` |
| 自定义模型元数据持久化（含 `thinking_format` / `thinking_capability` 枚举值） | [models.py](models.py) 的 `LLMCustomModelRecord` |
| per-Agent / per-component LLM 绑定持久化 | [models.py](models.py) 的 `AgentLLMBindingRecord` |
| 数据库 schema 变更 | [models.py](models.py) 修改 ORM + [migrations/](migrations/) 新增 Alembic migration |
| 新增列的幂等迁移（启动时 ALTER TABLE 补列） | [database.py](database.py) 的 `_apply_idempotent_migrations`（已存在列自动跳过） |
| SQLAlchemy engine / session factory | [database.py](database.py) |
| scheduler 运行历史读写 | [../trigger/job_runs.py](../trigger/job_runs.py) 的 `ScheduledJobRunStore`；ORM model：[models.py](models.py) 的 `ScheduledJobRunRecord` |

## 公开接口（其他模块如何使用）

```python
from sebastian.store.session_store import SessionStore

# 生产模式（db_factory 必须注入，sessions_dir 可省略）
store = SessionStore(db_factory=db_factory)
session = await store.create_session(session)
await store.append_message(session_id, agent_type, role, content)
messages = await store.get_context_messages(session_id, agent_type)
timeline = await store.get_context_timeline_items(session_id, agent_type)
sessions = await store.list_sessions(agent_type)
```

## Timeline 方法选择

- `get_timeline_items(..., include_archived=True)` 是 audit/UI 历史视图，返回真实 `seq ASC` 顺序。
- `get_context_timeline_items(...)` 是 LLM context 视图，按非归档 item 的逻辑上下文顺序返回。

## Exchange 边界字段

一个 **exchange** = 一条用户消息 + 该消息触发的所有 assistant/tool 输出。Exchange 字段用于按用户交互轮次对 timeline item 切片，为上下文压缩（context compaction）提供精确边界。

| 字段 | 所在表 | 含义 |
|------|--------|------|
| `sessions.next_exchange_index` | sessions | 下一个可用 exchange 序号（初始为 1），通过 `allocate_exchange` 原子递增 |
| `session_items.exchange_id` | session_items | 本 item 所属 exchange 的 ULID（可为 NULL，表示系统内部 item） |
| `session_items.exchange_index` | session_items | 本 item 所属 exchange 的序号（可为 NULL） |

**分配方式：** 在每条用户消息入库之前，调用 `SessionStore.allocate_exchange(session_id, agent_type)` 得到 `(exchange_id, exchange_index)` 元组，再将其传入 `append_message(..., exchange_id=..., exchange_index=...)` 和后续所有 assistant/tool item 的写入路径。

**索引：** `ix_session_items_exchange(agent_type, session_id, exchange_index, seq)` 支持按 exchange 范围查询。

**压缩范围：** 上下文压缩应使用 `exchange_index` 界定压缩区间（不用旧的 `assistant_turn_id`）。

---

```python
# EventLog（在 SQLAlchemy session 上下文内使用）
from sebastian.store.event_log import EventLog
log = EventLog(db_session)
await log.append(event)
```

## AttachmentStore

`attachments.py` 负责附件的 blob 写入、状态流转与垃圾回收。

### 内容寻址与引用计数

- `blob_path` 由 `f"blobs/{sha[:2]}/{sha}"` 决定。多次上传同内容只占用一份 blob 文件。
- 缩略图同样按 SHA 内容寻址：`thumbs/{sha[:2]}/{sha}.{jpg|png|webp}`。
- `cleanup` 按 SHA 做引用计数：仅当 DB 中没有任何 record 指向该 SHA 时才物理删除 blob/thumb。
- `cleanup` 顺序约束：DB delete 先 commit 成功，commit 后再二次查询确认 SHA 无并发新引用，最后才 unlink 物理文件。物理 unlink 失败仅 warning 不回滚 DB。
- `upload_bytes` 失败回滚同样按 SHA 二次查询：DB commit 失败时，仅在 SHA 引用计数为 0 时才删除本次新写入的 blob/thumb，避免误删并发 upload 已 commit 的共享文件。
- 不变量：任何 DB-committed 的活跃 `AttachmentRecord` 都能通过 `blob_path` 找到磁盘文件；缩略图存在性不是不变量（解码失败 / 老数据时缺失，端点 fallback 处理）。

### 缩略图生成与 DecompressionBomb 防护

`attachments.py` 在模块级设置 `Image.MAX_IMAGE_PIXELS = 100_000_000`，把 Pillow 的像素上限收紧到 1 亿（约 10000×10000）。

`DecompressionBombWarning → Error` 的升级在 `_maybe_generate_thumbnail` 内部用 `warnings.catch_warnings()` 作用域化处理：

```python
with warnings.catch_warnings():
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    with Image.open(...) as img:
        img.load()  # 超限时抛 Error，外层 except 捕获降级
```

这样 warning filter 变更仅在本次调用栈内有效，退出后自动还原，**不产生进程级副作用**。其他使用 Pillow 的代码不受影响。

---

> 修改本目录或模块后，请同步更新此 README。
