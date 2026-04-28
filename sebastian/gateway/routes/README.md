# routes

> 上级索引：[gateway/](../README.md)

## 目录职责

所有 FastAPI 路由模块均在此目录下按功能领域拆分。每个文件对应一组相关 API，通过独立的 `APIRouter` 实例注册，最终由 `gateway/app.py` 统一挂载到应用。全部接口均需 JWT 认证（`require_auth` 依赖），`/auth/login` 和 `/health` 除外。

## 目录结构

```
routes/
├── __init__.py              # 空文件，包标识
├── agents.py                # Agent 状态查询与 LLM 绑定管理（GET /agents, PUT/DELETE /agents/{type}/llm-binding, GET /health）
├── approvals.py             # 高危操作审批流（列出/批准/拒绝 pending approval）
├── debug.py                 # 运行时调试接口（查询/动态修改日志级别）
├── llm_accounts.py          # LLM Account 管理（Account CRUD + Custom Model CRUD + Catalog 查询 + Default Binding）
├── memory_components.py     # 记忆组件 LLM 绑定管理（GET/PUT/DELETE /memory/components）
├── memory_settings.py       # 记忆功能运行时开关（GET/PUT /memory/settings）
├── attachments.py           # 附件上传/下载（POST /attachments、GET /attachments/{id}/content）
├── sessions.py              # 会话与 Task 生命周期管理（创建/查询/暂停/取消）
├── stream.py                # SSE 事件流推送（全局流 + 单会话流）
└── turns.py                 # 主对话入口（登录、发送消息触发 Sebastian 对话轮次）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| `GET /agents` — 查询所有 Agent 运行状态（含 `bound_account_id` + `bound_model_id` 字段） | [agents.py](agents.py) |
| `PUT /agents/{agent_type}/llm-binding` — 为 Agent 绑定指定 LLM Account + Model（`account_id + model_id`） | [agents.py](agents.py) |
| `DELETE /agents/{agent_type}/llm-binding` — 清除 Agent 的 LLM 绑定 | [agents.py](agents.py) |
| `GET /health` — 健康检查 | [agents.py](agents.py) |
| `GET /approvals` — 列出待审批操作 | [approvals.py](approvals.py) |
| `POST /approvals/{id}/grant` — 批准操作 | [approvals.py](approvals.py) |
| `POST /approvals/{id}/deny` — 拒绝操作 | [approvals.py](approvals.py) |
| `GET /debug/logging` — 查询日志状态 | [debug.py](debug.py) |
| `PATCH /debug/logging` — 动态开关 LLM stream / SSE 日志 | [debug.py](debug.py) |
| `GET /memory/components` — 列出所有记忆组件及其 LLM 绑定 | [memory_components.py](memory_components.py) |
| `GET /memory/components/{type}/llm-binding` — 查询指定记忆组件的 LLM 绑定 | [memory_components.py](memory_components.py) |
| `PUT /memory/components/{type}/llm-binding` — 为记忆组件绑定 LLM Account + Model | [memory_components.py](memory_components.py) |
| `DELETE /memory/components/{type}/llm-binding` — 清除记忆组件的 LLM 绑定 | [memory_components.py](memory_components.py) |
| `GET /memory/settings` — 获取记忆功能运行时设置（含 enabled 开关） | [memory_settings.py](memory_settings.py) |
| `PUT /memory/settings` — 更新记忆功能运行时设置 | [memory_settings.py](memory_settings.py) |
| `GET /llm/catalog` — 获取内置 Provider/Model 目录 | [llm_accounts.py](llm_accounts.py) |
| `GET /llm/accounts` — 列出所有 LLM Account | [llm_accounts.py](llm_accounts.py) |
| `POST /llm/accounts` — 创建 LLM Account（绑定 catalog provider + API key） | [llm_accounts.py](llm_accounts.py) |
| `PUT /llm/accounts/{id}` — 更新 Account（exclude_unset 语义） | [llm_accounts.py](llm_accounts.py) |
| `DELETE /llm/accounts/{id}` — 删除 Account 及关联 Custom Models 和 Bindings | [llm_accounts.py](llm_accounts.py) |
| `GET /llm/accounts/{id}/custom-models` — 列出 Account 的自定义模型 | [llm_accounts.py](llm_accounts.py) |
| `POST /llm/accounts/{id}/custom-models` — 创建自定义模型 | [llm_accounts.py](llm_accounts.py) |
| `PUT /llm/custom-models/{id}` — 更新自定义模型 | [llm_accounts.py](llm_accounts.py) |
| `DELETE /llm/custom-models/{id}` — 删除自定义模型 | [llm_accounts.py](llm_accounts.py) |
| `GET /llm/bindings/default` — 获取默认绑定 | [llm_accounts.py](llm_accounts.py) |
| `PUT /llm/bindings/default` — 设置默认绑定（account_id + model_id） | [llm_accounts.py](llm_accounts.py) |
| `POST /attachments` — 上传附件（图片 / 文本文件）| [attachments.py](attachments.py) |
| `GET /attachments/{id}/content` — 下载附件内容 | [attachments.py](attachments.py) |
| `GET /sessions` — 列出会话（支持过滤/分页） | [sessions.py](sessions.py) |
| `GET /sessions/{id}` — 查询单个会话及其消息 | [sessions.py](sessions.py) |
| `DELETE /sessions/{id}` — 删除会话 | [sessions.py](sessions.py) |
| `POST /sessions/{id}/turns` — 向已有会话发送消息 | [sessions.py](sessions.py) |
| `POST /agents/{agent_type}/sessions` — 创建 sub-agent 会话（首条消息即透传，无需先建会话再发 turn） | [sessions.py](sessions.py) |
| `GET /sessions/{id}/tasks` — 列出会话下的 Task | [sessions.py](sessions.py) |
| `POST /sessions/{id}/tasks/{tid}/pause` — 暂停 Task | [sessions.py](sessions.py) |
| `DELETE /sessions/{id}/tasks/{tid}` — 取消 Task（DELETE）| [sessions.py](sessions.py) |
| `POST /sessions/{id}/tasks/{tid}/cancel` — 取消 Task（POST）| [sessions.py](sessions.py) |
| `POST /sessions/{id}/cancel` — 取消 session 当前 turn（含未登记流的预取消兜底）| [sessions.py](sessions.py) |
| `POST /sessions/{id}/compact` — 手动触发上下文压缩（409 if active stream）| [sessions.py](sessions.py) |
| `GET /sessions/{id}/compaction/status` — 查询 session 压缩状态（token 估算、summary seq 等）| [sessions.py](sessions.py) |
| `GET /stream` — 订阅全局 SSE 事件流 | [stream.py](stream.py) |
| `GET /sessions/{id}/stream` — 订阅单会话 SSE 事件流 | [stream.py](stream.py) |
| `POST /auth/login` — 密码登录，获取 JWT | [turns.py](turns.py) |
| `POST /turns` — 发送消息，触发主对话轮次（effort 由 binding 决定） | [turns.py](turns.py) |

---

> 修改本目录或模块后，请同步更新此 README。
