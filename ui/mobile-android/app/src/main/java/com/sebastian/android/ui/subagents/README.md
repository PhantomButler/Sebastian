# subagents 模块

> 上级：[ui/README.md](../README.md)

Sub-Agent 浏览页，展示可用 Agent 列表，点击直接进入 AgentChat 对话。

## 目录结构

```text
subagents/
└── AgentListScreen.kt   # Sub-Agent 列表页（点击进入 Route.AgentChat）
```

## 模块说明

### `AgentListScreen`

由 `SubAgentViewModel` 驱动，从后端拉取可用 Sub-Agent 列表并展示。点击某个 Agent 直接导航至 `Route.AgentChat(agentId, agentName)`，复用主对话 `ChatScreen` 的三面板布局（SubAgent 模式）。

> `/agents` 后端返回包含主管家 Sebastian（`is_orchestrator = true`），本页在 VM 层通过 `filterNot { isOrchestrator }` 过滤掉，只展示真正的 sub-agent。

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改 Agent 列表样式/交互 | `AgentListScreen.kt` |
| 改 Agent 数据加载逻辑 | `viewmodel/SubAgentViewModel.kt` |
| 改点击后导航行为 | `AgentListScreen.kt` → `Route.AgentChat` 传参 |

---

> 新增 Sub-Agent 相关页面后，请同步更新本 README 与上级 [ui/README.md](../README.md)。
