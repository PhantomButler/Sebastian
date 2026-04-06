# store/

> 上级：[src/](../README.md)

## 目录职责

Zustand 本地 UI 状态层。只存放前端所需的瞬态与持久化配置状态，不作为业务真数据源（业务真相来自后端，通过 React Query 获取）。敏感配置（serverUrl、jwtToken）通过 `expo-secure-store` 加密持久化到设备本地。

## 目录结构

```
store/
├── conversation.ts    # 每个 session 的实时对话状态（流式 block、工具调用、消息历史）
├── session.ts         # 当前 session、草稿 session、流式消息 delta（最多缓存 20 条）
├── agents.ts          # Sub-Agent 相关 UI 状态
├── approval.ts        # 待审批项队列
├── llmProviders.ts    # LLM Provider 本地 UI 状态
└── settings.ts        # serverUrl、jwtToken、llmProvider 等配置（SecureStore 持久化）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改流式响应渲染状态（thinking/text/tool block） | [conversation.ts](conversation.ts) |
| 修改当前 session 切换 / 草稿 session 逻辑 | [session.ts](session.ts) |
| 修改 Sub-Agent UI 状态 | [agents.ts](agents.ts) |
| 修改审批弹窗状态 | [approval.ts](approval.ts) |
| 修改 LLM Provider 本地状态 | [llmProviders.ts](llmProviders.ts) |
| 修改 serverUrl / Token 持久化逻辑 | [settings.ts](settings.ts) |

---

> 修改本目录后，请同步更新此 README。
