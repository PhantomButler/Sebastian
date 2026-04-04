# store — 持久化层

## 职责

两套存储并存：文件系统 JSON（Session/Task 数据，支持断电恢复）+ SQLite ORM（事件日志、Approval 记录、Task 索引，支持结构化查询）。

## 关键文件

| 文件 | 职责 |
|---|---|
| `session_store.py` | **主要读写入口**：Session 和 Task 以 JSON 文件存储在 `SEBASTIAN_DATA_DIR/sessions/` 下，提供 `create_session`、`get_session`、`create_task`、`update_task_status`、`list_sessions` 等全部 CRUD 操作 |
| `index_store.py` | 轻量级 `index.json` 维护 session 元数据快速查询（避免全量扫描目录），由 `TaskManager` 在提交任务时更新 |
| `event_log.py` | `EventLog`：将 `Event` 对象追加写入 SQLite `events` 表，用于历史查询 |
| `models.py` | SQLAlchemy ORM 模型：`EventRecord`、`ApprovalRecord`、`TaskRecord`（SQLite 表定义） |
| `database.py` | SQLAlchemy async engine 初始化，`Base`、`get_db`（async session factory） |
| `task_store.py` | Task 级别的 SQLite 辅助写入（补充 session_store 的文件存储） |
| `migrations/` | Alembic 迁移脚本 |

## 存储目录结构

```
SEBASTIAN_DATA_DIR/sessions/
  sebastian/<session_id>/
    session.json          # Session 元数据
    tasks/<task_id>.json  # Task 数据（每个 task 独立文件）
  subagents/<agent_type>/<agent_id>/<session_id>/
    session.json
    tasks/<task_id>.json
```

## 公开接口（其他模块如何使用）

```python
from sebastian.store.session_store import SessionStore

store = SessionStore(data_dir=Path("./data"))
session = await store.create_session(session)
task = await store.create_task(task, agent_type, agent_id)
await store.update_task_status(task_id, session_id, agent_type, agent_id, TaskStatus.RUNNING)
sessions = await store.list_sessions(agent_type="sebastian", status="active")

# EventLog（在 SQLAlchemy session 上下文内使用）
from sebastian.store.event_log import EventLog
log = EventLog(db_session)
await log.append(event)
```

## 常见任务入口

- **修改 Session/Task 读写逻辑** → `session_store.py`
- **修改 session 快速索引** → `index_store.py`
- **查询事件历史** → `event_log.py` + `models.py` 的 `EventRecord`
- **修改 Approval 持久化结构** → `models.py` 的 `ApprovalRecord`
- **数据库 schema 变更** → `models.py` + `migrations/` 新增 Alembic migration
