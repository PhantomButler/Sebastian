# components/subagents/

> 上级：[components/](../README.md)

## 目录职责

Sub-Agent 浏览链路的 UI 组件集合，覆盖从 Agent 列表 → Session 列表 → Session 详情的完整三级导航视图。

## 目录结构

```
subagents/
├── AgentList.tsx          # Sub-Agent 列表页（名称、描述、状态徽章）
├── AgentStatusBadge.tsx   # Agent 运行状态徽章（online/offline/busy 等）
├── SessionList.tsx        # 某个 Agent 下的 Session 列表
└── SessionDetailView.tsx  # Session 详情页（消息与任务双视图）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改 Agent 列表样式或点击行为 | [AgentList.tsx](AgentList.tsx) |
| 修改 Agent 状态徽章颜色或文字 | [AgentStatusBadge.tsx](AgentStatusBadge.tsx) |
| 修改 Session 列表项展示或排序 | [SessionList.tsx](SessionList.tsx) |
| 修改 Session 详情视图（消息/任务切换） | [SessionDetailView.tsx](SessionDetailView.tsx) |

---

> 修改本目录后，请同步更新此 README。
