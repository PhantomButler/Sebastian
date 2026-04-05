# App 对话 UI 一期优化设计文档

> **给自动化 worker：** 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务执行此计划。

**目标：** 将移动端对话 UI 从伪流式纯文本升级为真实增量渲染，支持思考区折叠、tool 调用展示、Markdown 渲染，并抽为可复用组件供 Sebastian 主页和 subagent session 页共用。

**架构：** 新增共享组件层 `src/components/conversation/`，Zustand store 改为多 session 并行管理，SSE 订阅新增 `turn.delta` / `thinking_delta` / `tool.*` / `block.*` 事件处理，接续流式采用 Timeline-first + Last-Event-ID fence 方案。

**技术栈：** React Native (Expo)、Zustand、react-native-sse、react-native-markdown-display、现有 Sebastian gateway SSE 接口。

---

## 问题

当前状态：
- 后端已全链路流式（`turn.delta`、`turn.thinking_delta`、`tool.running/executed`、`thinking_block.start/stop`、`text_block.start/stop` 均有 block_id/tool_id）
- 前端 `useSSE` 只处理 `turn.response`，等完成后全量刷新，伪流式
- 无 Markdown 渲染，无思考区展示，无 tool 调用展示
- 对话组件耦合在 `app/chat/index.tsx`，subagent session 页无法复用

---

## 组件设计

### 共享组件目录

```
ui/mobile/src/components/conversation/
├── index.ts                  # 统一导出
├── ConversationView.tsx       # 顶层容器，接收 sessionId，消费 store
├── UserBubble.tsx             # 用户消息，右对齐气泡
├── AssistantMessage.tsx       # AI 回复，按 blocks 顺序渲染各子块
├── ThinkingBlock.tsx          # 思考区折叠 accordion pill
├── ToolCallGroup.tsx          # 连续 tool call 列表 + 竖线串联逻辑
├── ToolCallRow.tsx            # 单条 tool call：状态圆点 + name + 参数
└── MarkdownContent.tsx        # react-native-markdown-display 封装
```

**使用方式（两处页面相同）：**

```tsx
// app/chat/index.tsx（Sebastian 主对话）
// app/subagents/[id]/session.tsx（subagent session）
<ConversationView sessionId={sessionId} />
```

### 组件职责

**`ConversationView`**：从 store 读取 `sessions[sessionId]`，渲染消息列表，管理 session 生命周期（进入触发 hydrate + SSE connect，离开触发 pause）。

**`UserBubble`**：纯展示，右对齐气泡，纯文本。

**`AssistantMessage`**：接收 `blocks: RenderBlock[]`，按顺序渲染 `ThinkingBlock` / `ToolCallGroup` / `MarkdownContent`，连续多个 `tool` 类型 block 自动归入同一 `ToolCallGroup`。

**`ThinkingBlock`**：展示为胶囊（pill）按钮，默认收起。展开时 pill header 与内容合并为单一容器（accordion），内容用 `MarkdownContent` 渲染。流式过程中实时追加文本。

**`ToolCallGroup`**：接收连续的 tool block 列表，在每两个 `ToolCallRow` 之间渲染竖线连接符。

**`ToolCallRow`**：一行显示：`● tool_name  target_or_params`。圆点颜色：running = 黄，done = 绿，failed = 红。无外层包装，无折叠。

**`MarkdownContent`**：用 `react-native-markdown-display` 渲染，流式过程中 content prop 随 textChunks 拼接实时更新。

---

## 状态管理

### Store 结构（Zustand）

```ts
// 渲染块类型
type RenderBlock =
  | { type: 'thinking'; blockId: string; text: string; done: boolean }
  | { type: 'text';     blockId: string; text: string; done: boolean }
  | { type: 'tool';     toolId: string;  name: string; input: string;
      status: 'running' | 'done' | 'failed'; result?: string }

interface StreamingTurn {
  turnId: string
  blocks: RenderBlock[]           // 按事件到达顺序，保持交错排列
  blockMap: Map<string, RenderBlock>  // block_id / tool_id → block，O(1) 更新
}

interface SessionState {
  status: 'loading' | 'live' | 'paused'
  lastEventSeq: number            // 用于 SSE 重连的 fence
  messages: Message[]             // 历史完成消息（来自 timeline hydration）
  streamingTurns: Map<string, StreamingTurn>  // turn_id → 当前流式状态
}

interface ConversationStore {
  sessions: Map<string, SessionState>
  activeSessionId: string | null

  // Actions
  hydrateSession(sessionId: string): Promise<void>
  connectSSE(sessionId: string): void
  pauseSession(sessionId: string): void
  evictSession(sessionId: string): void   // LRU 清理

  // SSE 事件处理
  onThinkingBlockStart(sessionId: string, turnId: string, blockId: string): void
  onThinkingDelta(sessionId: string, turnId: string, blockId: string, delta: string): void
  onThinkingBlockStop(sessionId: string, turnId: string, blockId: string): void
  onTextBlockStart(sessionId: string, turnId: string, blockId: string): void
  onTextDelta(sessionId: string, turnId: string, blockId: string, delta: string): void
  onTextBlockStop(sessionId: string, turnId: string, blockId: string): void
  onToolRunning(sessionId: string, turnId: string, toolId: string, name: string, input: string): void
  onToolExecuted(sessionId: string, turnId: string, toolId: string, result: string): void
  onToolFailed(sessionId: string, turnId: string, toolId: string, error: string): void
  onTurnComplete(sessionId: string, turnId: string): void
}
```

### 多 Session 并行规则

- 同一时刻只有一个 session 处于 `live` 状态（SSE 连接激活）
- 用户切走时：断开 SSE，status → `paused`，state 保留在内存
- 用户切回时：重新走 hydrate + SSE 流程
- 内存优化：超过 N 个 paused session 时按 LRU 清掉最老的，下次进入重新 hydrate
- 非活跃 session 的 SSE 事件（如后台任务进度）仍写入 store，但不触发 UI 渲染

---

## 流式接续方案

用户进入一个 session（含正在运行的任务）时：

```
1. dispatch hydrateSession(sessionId)
   → GET /sessions/{id}/timeline
   → 将历史 messages 写入 store
   → 记录响应中最后一条事件的 event_seq 为 fence

2. dispatch connectSSE(sessionId)
   → 建立 SSE 连接，发送 Last-Event-ID: {fence}
   → 后端从 fence 之后重放缓冲事件，补全 hydration 期间的 gap

3. 后续 SSE 事件实时 append，无需轮询
```

hydration 和 SSE 连接并不需要严格串行：可以先建连接并缓冲事件，hydration 完成后再 replay 缓冲——但利用 `Last-Event-ID` 服务端重放更简单，推荐优先用服务端重放方案。

---

## SSE 事件映射

| SSE 事件 | Store Action |
|---|---|
| `thinking_block.start` | `onThinkingBlockStart(blockId)` → push 新 thinking block |
| `turn.thinking_delta` | `onThinkingDelta(blockId, delta)` → `block.text += delta` |
| `thinking_block.stop` | `onThinkingBlockStop(blockId)` → `block.done = true` |
| `text_block.start` | `onTextBlockStart(blockId)` → push 新 text block |
| `turn.delta` | `onTextDelta(blockId, delta)` → `block.text += delta` |
| `text_block.stop` | `onTextBlockStop(blockId)` → `block.done = true` |
| `tool.running` | `onToolRunning(toolId, name, input)` → push tool block（status: running）|
| `tool.executed` | `onToolExecuted(toolId, result)` → status: done |
| `tool.failed` | `onToolFailed(toolId, error)` → status: failed |
| `turn.response` | `onTurnComplete(turnId)` → 触发 messages 查询刷新，清理 streamingTurn |

---

## 视觉规格

### 消息布局

- **用户消息**：右对齐圆角气泡，背景色 `#7c6af5`，白色文字，最大宽度 75%
- **AI 回复**：左对齐全宽扁平，无外层卡片，无背景色

### ThinkingBlock（思考区）

收起状态：
```
💭  思考过程  1.2s  ▸
```
圆角胶囊（pill），背景 `#1a1a2e`，边框 `#2a2a4e`，字色 `#6060a0`

展开状态（accordion，pill header 与内容连为一体）：
```
┌────────────────────────────────┐
│ 💭  思考过程  1.2s  ▾           │  ← pill header（可点击收起）
├────────────────────────────────┤
│ 思考文本内容（Markdown 渲染）    │
└────────────────────────────────┘
```
同一容器，`border-radius` 顶部 20px，底部 8px，`border: 1px solid #2a2a4e`

### ToolCallRow（tool 调用行）

```
●  read_file  docs/style.md
●  bash  pytest tests/unit/
```

圆点颜色：`#f5a623`（running）/ `#4caf50`（done）/ `#f44336`（failed）

### ToolCallGroup（连续 tool 竖线）

```
●  read_file  docs/style.md
│
●  bash  pytest tests/unit/
│
●  write_file  src/foo.py
```

两个 `ToolCallRow` 之间渲染 1px 竖线，颜色 `#2a2a2a`，左边距与圆点对齐

### MarkdownContent

使用 `react-native-markdown-display`，代码块深色背景 `#111`，行内代码圆角背景，标题加粗，支持有序/无序列表。

---

## 涉及文件

| 文件 | 操作 |
|---|---|
| `ui/mobile/src/components/conversation/` | 新建目录及全部组件 |
| `ui/mobile/src/store/conversation.ts` | 新建（替代原 session store 的流式部分）|
| `ui/mobile/src/hooks/useConversation.ts` | 新建（封装 hydrate + SSE connect/pause 生命周期）|
| `ui/mobile/src/api/sse.ts` | 修改：新增 block/tool 事件处理 |
| `ui/mobile/src/types.ts` | 修改：补充 `turn.delta`、block 事件类型定义 |
| `ui/mobile/app/chat/index.tsx` | 修改：替换为 `<ConversationView>` |
| `ui/mobile/app/subagents/[id]/session.tsx` | 修改：使用 `<ConversationView>`（如已存在）|
| `package.json` | 新增：`react-native-markdown-display` |

## 不在范围内

- 代码块语法高亮（一期先做基础 markdown，高亮后续单独加）
- 消息重试 / 编辑
- 图片 / 文件附件
- 暗色/亮色主题切换（当前固定深色）
- subagent session 页面本身的新建对话按钮（单独跟踪）
