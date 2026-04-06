# api/

> 上级：[src/](../README.md)

## 目录职责

与后端 `sebastian/gateway/` 对接的 HTTP / SSE 请求封装层。每个文件对应一类后端资源，统一通过 `client.ts` 的 axios 实例发起请求，由此保证 baseURL、JWT Token 注入和 401 跳转逻辑集中管理。

## 目录结构

```
api/
├── client.ts          # axios 实例、请求拦截（baseURL / JWT）、401 自动跳转
├── auth.ts            # 登录、健康检查、登出
├── turns.ts           # 主对话发送（POST /sessions/:id/turns）
├── sessions.ts        # Session 列表、详情、任务列表
├── agents.ts          # Sub-Agent 列表相关接口
├── approvals.ts       # 审批项查询与操作
├── llmProviders.ts    # LLM Provider 增删改查（CRUD）
├── debug.ts           # 调试日志开关（GET/PATCH /debug/logging）
└── sse.ts             # SSE 连接层（全局事件流 + 会话级流式）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改认证 Token 逻辑 / 401 处理 | [auth.ts](auth.ts)、[client.ts](client.ts) |
| 修改请求 baseURL 或公共 Header | [client.ts](client.ts) |
| 修改主对话发送接口 | [turns.ts](turns.ts) |
| 修改 Session 列表 / 详情 / 消息接口 | [sessions.ts](sessions.ts) |
| 修改 Sub-Agent 列表接口 | [agents.ts](agents.ts) |
| 修改审批流程接口 | [approvals.ts](approvals.ts) |
| 修改 LLM Provider 配置接口 | [llmProviders.ts](llmProviders.ts) |
| 修改 SSE 连接协议 / Last-Event-ID 续接 | [sse.ts](sse.ts) |
| 修改调试日志开关接口 | [debug.ts](debug.ts) |

---

> 修改本目录后，请同步更新此 README。
