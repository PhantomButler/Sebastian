# chat 模块

> 上级：[ui/README.md](../README.md)

主对话入口，基于 `NavigableListDetailPaneScaffold` 实现三栏自适应布局（手机竖屏单栏，宽屏/折叠屏多栏）。

## 目录结构

```text
chat/
├── ChatScreen.kt             # 主对话 Screen（三栏脚手架 + GlassSurface Composer）
├── SlidingThreePaneLayout.kt # 手势驱动三面板滑动容器
├── MessageList.kt            # 消息列表（LazyColumn + 滚动跟随逻辑）
├── SessionPanel.kt           # 左栏：Session 列表面板（List Pane）
├── StreamingMessage.kt       # 流式消息气泡（逐块渲染）
├── ThinkingCard.kt           # 思考块卡片（可展开/折叠）
├── TodoPanel.kt              # 右栏：Todo 面板（Extra Pane）
└── ToolCallCard.kt           # 工具调用块卡片（含状态 badge）
```

## 模块说明

### `ChatScreen`

使用 `NavigableListDetailPaneScaffold` 组合三栏布局，并通过 `GlassSurface` 实现液态玻璃输入框悬浮效果：

- **List Pane**（左栏）：`SessionPanel` — Session 列表 + 导航入口（Settings / SubAgents）
- **Detail Pane**（中栏）：`MessageList` + `Composer`（GlassSurface 悬浮） + 三态 `ErrorBanner`
- **Extra Pane**（右栏）：`TodoPanel`

### `SlidingThreePaneLayout`

手势驱动的三面板滑动容器，用于手机竖屏单栏模式：

- 侧边栏占屏幕宽度的 `paneFraction`（默认 75%），主内容同步推出
- 整个内容区均可横向拖拽触发侧栏（不限于边缘）
- 使用 `awaitHorizontalTouchSlopOrCancellation` 区分横/纵向手势，纵向滑动自动交给 `LazyColumn`
- 若子组件已消费横向手势（如 Markdown 代码块横向滚动），本层不介入
- `SidePane` 枚举：`NONE` / `LEFT` / `RIGHT`

### `MessageList`

管理滚动跟随状态（`FOLLOWING` / `DETACHED` / `NEAR_BOTTOM`），由 `flushTick` 驱动每帧滚动更新。

### `StreamingMessage`

按 `ContentBlock` 类型分发渲染：

| Block 类型 | 渲染组件 |
|-----------|---------|
| `TextBlock` | `MarkdownView` |
| `ThinkingBlock` | `ThinkingCard` |
| `ToolBlock` | `ToolCallCard` |

### `ThinkingCard`

可展开/折叠的思考块卡片，流式传输过程中持续追加内容。

### `ToolCallCard`

工具调用块卡片，含状态 badge（`RUNNING` / `SUCCESS` / `ERROR`）。

### `SessionPanel`

左栏 Session 列表面板，提供历史 Session 切换、新建对话、跳转 Settings / SubAgents 入口。

### `TodoPanel`

右栏 Todo 面板，显示当前对话中 Agent 任务的 checklist 状态。

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改三栏布局（脚手架结构） | `ChatScreen.kt` |
| 改手机单栏手势滑动逻辑 | `SlidingThreePaneLayout.kt` |
| 改消息列表滚动行为 | `MessageList.kt` |
| 改消息渲染分发逻辑 | `StreamingMessage.kt` |
| 改思考块展开/折叠 | `ThinkingCard.kt` |
| 改工具调用块样式/状态 | `ToolCallCard.kt` |
| 改 Session 列表面板 | `SessionPanel.kt` |
| 改 Todo 面板 | `TodoPanel.kt` |

---

> 新增消息类型或改动三栏结构后，请同步更新本 README 与上级 [ui/README.md](../README.md)。
