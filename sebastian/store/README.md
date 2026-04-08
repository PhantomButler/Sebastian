# store — 持久化层

> 上级索引：[sebastian/](../README.md)

## 模块职责

两套存储并存：文件系统 JSON（Session/Task 数据，支持断电恢复）+ SQLite ORM（事件日志、Approval 记录、LLM Provider 配置，支持结构化查询）。`SessionStore` 是主要读写入口，`IndexStore` 维护轻量级元数据索引避免全量目录扫描。

## 目录结构

```
store/
├── __init__.py          # 模块入口（空导出，按需 import 子模块）
├── database.py          # SQLAlchemy async engine 初始化，Base、get_db（async session factory）
├── models.py            # SQLAlchemy ORM 模型：EventRecord、ApprovalRecord、TaskRecord、LLMProviderRecord
├── session_store.py     # 主要读写入口：Session 和 Task 以 JSON 文件存储，提供完整 CRUD 操作
├── index_store.py       # 轻量级 index.json 维护 session 元数据快速查询，原子写入防并发损坏
├── event_log.py         # EventLog：将 Event 对象追加写入 SQLite events 表，用于历史查询
├── task_store.py        # Task 级别的 SQLite 辅助写入（补充 session_store 的文件存储）
├── todo_store.py        # per-session todos.json 原子读写（LLM 维护的 todo 列表）
└── migrations/
    └── __init__.py      # Alembic 迁移脚本目录（schema 变更在此新增 migration）
```

## 文件系统存储结构

```
SEBASTIAN_DATA_DIR/sessions/
  <agent_type>/<session_id>/   # agent_type 例如 sebastian、code
    session.json               # Session 元数据
    tasks/<task_id>.json       # Task 数据（每个 task 独立文件）
    todos.json                 # LLM 维护的 todo 列表（覆盖式写入）
  index.json                   # 全局 session 元数据索引（由 IndexStore 维护）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| Session / Task 的读写逻辑 | [session_store.py](session_store.py) |
| Session 快速索引（避免全量扫描） | [index_store.py](index_store.py) |
| 事件历史查询 | [event_log.py](event_log.py) + [models.py](models.py) 的 `EventRecord` |
| Approval 持久化结构 | [models.py](models.py) 的 `ApprovalRecord` |
| LLM Provider 配置持久化（含 `thinking_format` / `thinking_capability`） | [models.py](models.py) 的 `LLMProviderRecord` |
| 数据库 schema 变更 | [models.py](models.py) 修改 ORM + [migrations/](migrations/) 新增 Alembic migration |
| 新增列的幂等迁移（启动时 ALTER TABLE 补列） | [database.py](database.py) 的 `_apply_idempotent_migrations`（已存在列自动跳过） |
| SQLAlchemy engine / session factory | [database.py](database.py) |
| Task SQLite 辅助写入 | [task_store.py](task_store.py) |
| Todo 列表读写 | [todo_store.py](todo_store.py) |

## 公开接口（其他模块如何使用）

```python
from sebastian.store.session_store import SessionStore

store = SessionStore(data_dir=Path("./data"))
session = await store.create_session(session)
task = await store.create_task(task, agent_type)
await store.update_task_status(task_id, session_id, agent_type, TaskStatus.RUNNING)

# IndexStore — 快速元数据查询（无需遍历目录）
from sebastian.store.index_store import IndexStore
index = IndexStore(sessions_dir=Path("./data/sessions"))
await index.upsert(session)
sessions = await index.list_by_agent_type("code")
children = await index.list_active_children("code", parent_session_id="...")

# EventLog（在 SQLAlchemy session 上下文内使用）
from sebastian.store.event_log import EventLog
log = EventLog(db_session)
await log.append(event)
```

---

> 修改本目录或模块后，请同步更新此 README。
