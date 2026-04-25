# gateway — FastAPI HTTP/SSE 网关

> 上级索引：[sebastian/](../README.md)

## 模块职责

对外暴露 REST API 和 SSE 事件流，是 Sebastian 系统唯一的 HTTP 入口。
管理全局运行时单例（`agent_instances`、`agent_registry`、SessionStore、EventBus、SSEManager 等），在 `lifespan` 中按严格顺序完成初始化与清理。
处理 JWT 认证，路由请求至对应业务处理器。

Session 列表和子 session 查询均通过 `SessionStore`（SQLite backed）完成；`IndexStore` 已从运行时移除。
`GET /sessions/{id}` 同时返回 `timeline_items`（规范 timeline 格式）和 `messages`（向后兼容投影）。

## 目录结构

```
gateway/
├── __init__.py              # 模块入口（空）
├── app.py                   # FastAPI 应用创建、lifespan 初始化/关闭、路由注册
├── auth.py                  # JWT 认证：token 生成/校验、密码哈希、require_auth 依赖
├── completion_notifier.py   # CompletionNotifier：订阅子代理 session 生命周期事件，触发父 Agent 新 LLM turn
├── sse.py                   # SSEManager：订阅 EventBus，向客户端广播 SSE 事件流
├── state.py                 # 全局运行时单例容器（模块级变量，全项目通过 import 访问）
├── routes/                  # → [routes/README.md](routes/README.md)
└── setup/                   # 首次启动 Web 初始化向导（secret key 生成、owner 账号创建）
    ├── __init__.py
    ├── secret_key.py        # SecretKeyManager：生成/读取 secret.key 文件
    ├── security.py          # SetupSecurity：localhost 或 one-time token 访问校验
    └── setup_routes.py      # /setup GET（HTML 向导页）+ /setup/complete POST（落库并退出）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 REST 路由 | [routes/](routes/README.md) 下选对应文件或新建，再在 [app.py](app.py) 中 `include_router` |
| 启动/关闭初始化流程（顺序严格：DB → Store → EventBus → Agent → SSE） | [app.py](app.py) 的 `lifespan` |
| 认证逻辑、Token 有效期、密码哈希算法 | [auth.py](auth.py) |
| SSE 推送逻辑、事件缓冲大小（默认 500）、客户端队列大小（默认 200） | [sse.py](sse.py) 的 `SSEManager` |
| 子代理完成/失败/等待事件触发父 Agent | [completion_notifier.py](completion_notifier.py) 的 `CompletionNotifier` |
| 全局运行时对象（访问或增减单例变量） | [state.py](state.py)（`agent_instances` 替代旧 `agent_pools`） |
| 注册 Sub-Agent 实例与配置 | [app.py](app.py) 的 `_initialize_agent_instances()` |
| 创建 Sub-Agent session（懒启动） | `POST /api/v1/agents/{type}/sessions`（routes/sessions.py） |
| 查看 session 最近消息与状态 | `GET /api/v1/sessions/{id}/recent`（routes/sessions.py） |
| 获取 session 完整历史（含 timeline_items 和 messages 向后兼容） | `GET /api/v1/sessions/{id}`（routes/sessions.py） |
| 首次启动初始化向导（owner 账号、secret key） | [setup/setup_routes.py](setup/setup_routes.py) |
| 手动触发上下文压缩 | `POST /api/v1/sessions/{id}/compact`（routes/sessions.py） |
| 查询 session 压缩状态 | `GET /api/v1/sessions/{id}/compaction/status`（routes/sessions.py） |
| LLM Account / Catalog / Custom Model / Binding 管理 | [routes/llm_accounts.py](routes/llm_accounts.py) |

## 子模块

- [routes/](routes/README.md) — HTTP 路由处理层，涵盖认证、会话、消息、SSE、审批、Agent 查询、LLM 配置、调试等端点
- [setup/](setup/README.md) — 首次启动初始化向导，生成 secret key 并创建 owner 账号

## 公开接口（其他模块如何使用）

```python
# 访问全局运行时状态（仅在路由处理函数内调用）
import sebastian.gateway.state as state
state.session_store.get_session(session_id)      # SessionStore（SQLite backed）
state.session_store.list_sessions(agent_type)    # 替代旧 IndexStore.list_by_agent_type
state.event_bus.publish(event)
state.sebastian                        # 主管家 Sebastian 实例
state.agent_instances["forge"]         # Sub-Agent 实例
state.agent_registry["forge"]          # Sub-Agent 配置元数据
state.conversation.request_approval(...)
state.db_factory                       # SQLAlchemy async session factory
state.llm_registry                     # LLMProviderRegistry 实例
state.memory_extractor                 # MemoryExtractor 实例（memory_save 后台任务使用；None 表示未初始化）
state.get_owner_store()                # OwnerStore（需要 DB session）
# 注：state.todo_store 和 state.index_store 已从运行时移除

# 认证依赖
from sebastian.gateway.auth import require_auth
@router.get("/foo")
async def foo(_auth: dict = Depends(require_auth)): ...
```

### SubAgent Session Client IDs

`POST /agents/{agent_type}/sessions` accepts an optional `session_id` field in the request body:

- **Not provided**: backend generates a new session id (existing behavior).
- **Provided, session does not exist**: creates the session with that id and starts the initial turn.
- **Provided, session exists with same `agent_type` and `content`**: idempotent — returns `200` with existing `session_id` and no duplicate initial turn.
- **Provided, session exists but different agent or content**: returns `409 Conflict`.

## 上下文压缩接口

### `POST /api/v1/sessions/{session_id}/compact`

手动触发对指定 session 的上下文压缩。

- **请求体**（可选，全部有默认值）：
  ```json
  { "mode": "manual", "retain_recent_exchanges": 8, "dry_run": false }
  ```
- **返回**：`CompactionResult` 序列化为 JSON，字段包括 `status`（`"compacted"` / `"skipped"`）、`reason`、`summary_item_id`、`source_seq_start`、`source_seq_end`、`archived_item_count`、`source_token_estimate`、`summary_token_estimate`。
- **409 语义**：若 session 当前存在活跃的 streaming turn（`_active_streams` 中有未完成 task），返回 HTTP 409，错误消息说明需等待 turn 完成后重试。这是为了避免与正在写入 context items 的 LLM 调用产生竞争。

### `GET /api/v1/sessions/{session_id}/compaction/status`

查询 session 的当前压缩状态，无副作用。

- **返回字段**：
  - `token_estimate`：当前 context 的本地 token 估算值。
  - `last_summary_seq`：最近一条 `context_summary` 的 seq（无则为 null）。
  - `compactable_exchange_count`：可压缩的 exchange 数（总 exchange 数减去保留窗口，最小为 0）。
  - `retained_recent_exchanges`：保留窗口大小（固定为 8）。

路由均位于 `sebastian/gateway/routes/sessions.py`，均需 JWT 认证（`require_auth` 依赖）。

## 注意事项

- `state.py` 中的变量名**不可随意重命名**——全项目通过模块导入直接访问，重命名会导致全局 `NameError`
- `app.py` 的 `lifespan` 初始化顺序有严格要求，不可调换：`DB → Store → EventBus → Agent → SSE`
- `state.context_compaction_worker` 在 lifespan 初始化时赋值，在路由中通过 `state.context_compaction_worker.compact_session(...)` 调用

---

> 修改本目录或模块后，请同步更新此 README。
