# gateway — FastAPI HTTP/SSE 网关

> 上级索引：[sebastian/](../README.md)

## 模块职责

对外暴露 REST API 和 SSE 事件流，是 Sebastian 系统唯一的 HTTP 入口。
管理全局运行时单例（`agent_instances`、`agent_registry`、SessionStore、EventBus、SSEManager 等），在 `lifespan` 中按严格顺序完成初始化与清理。
处理 JWT 认证，路由请求至对应业务处理器。

## 目录结构

```
gateway/
├── __init__.py        # 模块入口（空）
├── app.py             # FastAPI 应用创建、lifespan 初始化/关闭、路由注册
├── auth.py            # JWT 认证：token 生成/校验、密码哈希、require_auth 依赖
├── sse.py             # SSEManager：订阅 EventBus，向客户端广播 SSE 事件流
├── state.py           # 全局运行时单例容器（模块级变量，全项目通过 import 访问）
└── routes/            # → [routes/README.md](routes/README.md)
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 REST 路由 | [routes/](routes/README.md) 下选对应文件或新建，再在 [app.py](app.py) 中 `include_router` |
| 启动/关闭初始化流程（顺序严格：DB → Store → EventBus → Agent → SSE） | [app.py](app.py) 的 `lifespan` |
| 认证逻辑、Token 有效期、密码哈希算法 | [auth.py](auth.py) |
| SSE 推送逻辑、事件缓冲大小（默认 500）、客户端队列大小（默认 200） | [sse.py](sse.py) 的 `SSEManager` |
| 全局运行时对象（访问或增减单例变量） | [state.py](state.py)（`agent_instances` 替代旧 `agent_pools`） |
| 注册 Sub-Agent 实例与配置 | [app.py](app.py) 的 `_register_agents()` |
| 创建 Sub-Agent session（懒启动） | `POST /api/v1/agents/{type}/sessions`（routes/sessions.py） |
| 查看 session 最近消息与状态 | `GET /api/v1/sessions/{id}/recent`（routes/sessions.py） |

## 子模块

- [routes/](routes/README.md) — HTTP 路由处理层，涵盖认证、会话、消息、SSE、审批、Agent 查询、LLM 配置、调试等端点

## 公开接口（其他模块如何使用）

```python
# 访问全局运行时状态（仅在路由处理函数内调用）
import sebastian.gateway.state as state
state.session_store.get_session(session_id)
state.event_bus.publish(event)
state.agent_instances["code"]   # Sub-Agent 实例（替代旧 agent_pools）
state.agent_registry["code"]    # Sub-Agent 配置元数据
state.conversation.request_approval(...)

# 认证依赖
from sebastian.gateway.auth import require_auth
@router.get("/foo")
async def foo(_auth: dict = Depends(require_auth)): ...
```

## 注意事项

- `state.py` 中的变量名**不可随意重命名**——全项目通过模块导入直接访问，重命名会导致全局 `NameError`
- `app.py` 的 `lifespan` 初始化顺序有严格要求，不可调换：`DB → Store → EventBus → Agent → SSE`

---

> 修改本目录或模块后，请同步更新此 README。
