# gateway — FastAPI HTTP/SSE 网关

## 职责

对外暴露 REST API 和 SSE 事件流；管理全局运行时单例（Agent 池、SessionStore、EventBus 等）；处理认证。

## 关键文件

| 文件 | 职责 |
|---|---|
| `app.py` | FastAPI 应用入口：`lifespan` 负责启动/关闭时初始化/清理全局状态，`include_router` 注册所有路由，启动时自动发现 agents/ 目录下的 agent 类型 |
| `state.py` | 全局运行时单例容器（模块级变量）：`sebastian`、`event_bus`、`session_store`、`agent_pools`、`sse_manager` 等，路由中通过 `import sebastian.gateway.state as state` 访问 |
| `auth.py` | JWT 认证：`create_access_token()`、`require_auth`（FastAPI Depends）、`hash_password()`/`verify_password()` |
| `sse.py` | `SSEManager`：订阅 EventBus 所有事件，维护客户端连接队列，通过 `stream()` async generator 向客户端推送 SSE |
| `routes/sessions.py` | Session 增删查 + Task 查询/取消路由 |
| `routes/turns.py` | 登录（`POST /auth/login`）+ 发送消息（`POST /sessions/{id}/turns`）|
| `routes/agents.py` | 查询 Agent 类型和 Worker 状态 |
| `routes/stream.py` | SSE 事件流端点（`GET /events`）|
| `routes/approvals.py` | Approval 查询与处理（grant/deny）|

## 公开接口（其他模块如何使用）

```python
# 访问全局运行时状态（仅在路由处理函数内调用）
import sebastian.gateway.state as state
state.session_store.get_session(session_id)
state.event_bus.publish(event)
state.agent_pools["sebastian"]

# 认证依赖
from sebastian.gateway.auth import require_auth
@router.get("/foo")
async def foo(_auth: dict = Depends(require_auth)): ...
```

## 不要修改

- `state.py` 中的变量名（全项目通过模块导入直接访问，重命名会导致全局 NameError）
- `app.py` 的 lifespan 顺序（依赖初始化顺序有严格要求：DB → Store → EventBus → Agent → SSE）

## 常见任务入口

- **新增 REST 路由** → 在 `routes/` 下选对应文件或新建，在 `app.py` 中 `include_router`
- **修改认证逻辑/Token 有效期** → `auth.py`
- **修改 SSE 推送逻辑/缓冲大小** → `sse.py` 的 `SSEManager`
- **修改启动时初始化流程** → `app.py` 的 `lifespan`
- **调整 Agent Worker 数量** → `app.py` 的 `_initialize_runtime_agent_state()`
- **访问或修改全局运行时对象** → `state.py`
