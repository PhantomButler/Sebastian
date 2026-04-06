# components/conversation/

> 上级：[components/](../README.md)

## 目录职责

Sub-Agent Session 详情页的对话视图组件集合，负责渲染 assistant 消息（含 Markdown、思考块、工具调用）、用户消息气泡以及完整的会话视图容器。

## 目录结构

```
conversation/
├── ConversationView.tsx   # 完整会话视图容器（组合消息列表与各类 block）
├── AssistantMessage.tsx   # assistant 消息（含 thinking block / tool call / 文本）
├── UserBubble.tsx         # 用户消息气泡
├── MarkdownContent.tsx    # Markdown 渲染组件（支持代码块、列表等）
├── ThinkingBlock.tsx      # 思考过程折叠块（可展开 / 收起）
├── ToolCallGroup.tsx      # 工具调用组（多个 ToolCallRow 的分组容器）
├── ToolCallRow.tsx        # 单条工具调用行（名称、输入、结果、状态）
└── index.ts               # 公共导出汇总
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改整体会话布局或滚动逻辑 | [ConversationView.tsx](ConversationView.tsx) |
| 修改 assistant 消息整体结构 | [AssistantMessage.tsx](AssistantMessage.tsx) |
| 修改用户消息气泡样式 | [UserBubble.tsx](UserBubble.tsx) |
| 修改 Markdown 渲染样式或支持语法 | [MarkdownContent.tsx](MarkdownContent.tsx) |
| 修改思考块展开/收起交互 | [ThinkingBlock.tsx](ThinkingBlock.tsx) |
| 修改工具调用分组显示逻辑 | [ToolCallGroup.tsx](ToolCallGroup.tsx) |
| 修改单条工具调用行样式或状态展示 | [ToolCallRow.tsx](ToolCallRow.tsx) |
| 修改对外导出接口 | [index.ts](index.ts) |

---

> 修改本目录后，请同步更新此 README。
