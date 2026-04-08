# routes

> 上级索引：[gateway/](../README.md)

## 目录职责

所有 FastAPI 路由模块均在此目录下按功能领域拆分。每个文件对应一组相关 API，通过独立的 `APIRouter` 实例注册，最终由 `gateway/app.py` 统一挂载到应用。全部接口均需 JWT 认证（`require_auth` 依赖），`/auth/login` 和 `/health` 除外。

## 目录结构

```
routes/
├── __init__.py        # 空文件，包标识
├── agents.py          # Agent 状态查询与健康检查（GET /agents, GET /health）
├── approvals.py       # 高危操作审批流（列出/批准/拒绝 pending approval）
├── debug.py           # 运行时调试接口（查询/动态修改日志级别）
├── llm_providers.py   # LLM Provider 配置管理（CRUD）
├── sessions.py        # 会话与 Task 生命周期管理（创建/查询/暂停/取消）
├── stream.py          # SSE 事件流推送（全局流 + 单会话流）
└── turns.py           # 主对话入口（登录、发送消息触发 Sebastian 对话轮次）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| `GET /agents` — 查询所有 Agent 运行状态 | [agents.py](agents.py) |
| `GET /health` — 健康检查 | [agents.py](agents.py) |
| `GET /approvals` — 列出待审批操作 | [approvals.py](approvals.py) |
| `POST /approvals/{id}/grant` — 批准操作 | [approvals.py](approvals.py) |
| `POST /approvals/{id}/deny` — 拒绝操作 | [approvals.py](approvals.py) |
| `GET /debug/logging` — 查询日志状态 | [debug.py](debug.py) |
| `PATCH /debug/logging` — 动态开关 LLM stream / SSE 日志 | [debug.py](debug.py) |
| `GET /llm-providers` — 列出所有 LLM Provider（含 `thinking_capability`） | [llm_providers.py](llm_providers.py) |
| `POST /llm-providers` — 新增 LLM Provider（支持 `thinking_capability`） | [llm_providers.py](llm_providers.py) |
| `PUT /llm-providers/{id}` — 更新 LLM Provider（`exclude_unset` 语义：省略字段保留原值，显式 `null` 清空） | [llm_providers.py](llm_providers.py) |
| `DELETE /llm-providers/{id}` — 删除 LLM Provider | [llm_providers.py](llm_providers.py) |
| `GET /sessions` — 列出会话（支持过滤/分页） | [sessions.py](sessions.py) |
| `GET /sessions/{id}` — 查询单个会话及其消息 | [sessions.py](sessions.py) |
| `DELETE /sessions/{id}` — 删除会话 | [sessions.py](sessions.py) |
| `POST /sessions/{id}/turns` — 向已有会话发送消息（支持 `thinking_effort`） | [sessions.py](sessions.py) |
| `POST /agents/{agent_type}/sessions` — 创建 sub-agent 会话（首条消息即透传 `thinking_effort`，无需先建会话再发 turn） | [sessions.py](sessions.py) |
| `GET /sessions/{id}/tasks` — 列出会话下的 Task | [sessions.py](sessions.py) |
| `POST /sessions/{id}/tasks/{tid}/pause` — 暂停 Task | [sessions.py](sessions.py) |
| `DELETE /sessions/{id}/tasks/{tid}` — 取消 Task（DELETE）| [sessions.py](sessions.py) |
| `POST /sessions/{id}/tasks/{tid}/cancel` — 取消 Task（POST）| [sessions.py](sessions.py) |
| `GET /stream` — 订阅全局 SSE 事件流 | [stream.py](stream.py) |
| `GET /sessions/{id}/stream` — 订阅单会话 SSE 事件流 | [stream.py](stream.py) |
| `POST /auth/login` — 密码登录，获取 JWT | [turns.py](turns.py) |
| `POST /turns` — 发送消息，触发主对话轮次（支持 `thinking_effort`） | [turns.py](turns.py) |

---

> 修改本目录或模块后，请同步更新此 README。
