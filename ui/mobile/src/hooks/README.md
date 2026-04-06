# hooks/

> 上级：[src/](../README.md)

## 目录职责

面向页面的 React Query 查询封装与 SSE 订阅封装层。Hooks 将数据获取、缓存失效和状态订阅逻辑从页面组件中抽离，组件只需调用对应 hook，无需关心底层请求或事件处理细节。

## 目录结构

```
hooks/
├── useConversation.ts  # 单个 session 的 hydrate + per-session SSE 生命周期管理
├── useSSE.ts           # 全局 SSE 连接（task 事件、审批事件、App 前后台切换管理）
├── useSessions.ts      # React Query：Session 列表查询
├── useMessages.ts      # React Query：会话消息查询
└── useAgents.ts        # React Query：Sub-Agent 列表查询
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改会话消息 hydrate 逻辑 / SSE 续接策略 | [useConversation.ts](useConversation.ts) |
| 修改全局 SSE 事件处理（task/审批/前后台） | [useSSE.ts](useSSE.ts) |
| 修改 Session 列表数据获取 / 缓存失效 | [useSessions.ts](useSessions.ts) |
| 修改消息列表查询逻辑 | [useMessages.ts](useMessages.ts) |
| 修改 Sub-Agent 列表查询逻辑 | [useAgents.ts](useAgents.ts) |

---

> 修改本目录后，请同步更新此 README。
