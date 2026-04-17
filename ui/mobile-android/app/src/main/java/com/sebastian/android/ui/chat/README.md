# chat 模块

> 上级：[ui/README.md](../README.md)

主对话入口，基于 `NavigableListDetailPaneScaffold` 实现三栏自适应布局（手机竖屏单栏，宽屏/折叠屏多栏）。

## 目录结构

```text
chat/
├── AgentPill.kt              # 顶部 agent 名称胶囊（灵动岛展开/收起 + THINKING/ACTIVE 动画）
├── AgentPillAnimations.kt    # 4 光团 OrbsAnimation + Jarvis HUD 动画 Canvas 实现
├── ChatScreen.kt             # 主对话 Screen（三栏脚手架 + GlassSurface Composer）
├── CollapsibleContent.kt     # 工具调用展开区的二次折叠容器（≤5行直展，>5行折叠+最多30行）
├── MessageList.kt            # 消息列表（LazyColumn + 滚动跟随逻辑）
├── SessionGrouping.kt        # Session 按时间分桶逻辑（今天/昨天/7天内/30天内/年月）
├── SessionPanel.kt           # 左栏：Session 列表面板（List Pane）
├── SlidingThreePaneLayout.kt # 手势驱动三面板滑动容器
├── StreamingMessage.kt       # 流式消息气泡（逐块渲染）
├── ThinkingCard.kt           # 思考块卡片（可展开/折叠）
├── TodoPanel.kt              # 右栏：Todo 面板（Extra Pane）
├── ToolCallCard.kt           # 工具调用块卡片（含状态 badge）
├── ToolCallInputExtractor.kt # 从 tool inputs JSON 抽 summary / 参数列表
└── ToolDisplayName.kt        # tool 名 → 卡片 header (title, summary) 的自定义映射
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

工具调用块卡片，含状态 badge（`RUNNING` / `SUCCESS` / `ERROR`）。header 显示的标题与右侧一行 summary 由 [`ToolDisplayName`](ToolDisplayName.kt) 根据 tool 名决定，展开区的参数列表由 [`ToolCallInputExtractor`](ToolCallInputExtractor.kt) 从 inputs JSON 抽取。

### `ToolDisplayName`

tool 名 → 卡片 header 显示的集中映射。默认规则：`title = toolName`、`summary = ToolCallInputExtractor.extractInputSummary(...)`，对少数工具做自定义覆盖：

| Tool | Title | Summary |
|------|-------|---------|
| `delegate_to_agent` | `Agent: <子代理名>` | 空（信息已并入 title） |
| `spawn_sub_agent` | `Worker` | goal（inputs.goal） |
| 其他 | 原 tool 名 | `ToolCallInputExtractor` 抽取结果 |

新增映射：
1. 如需用到的 inputs 字段不在 [`ToolCallInputExtractor.KEY_PRIORITY`](ToolCallInputExtractor.kt) 里，先加进去，保证抽取顺序确定。
2. 在 `ToolDisplayName.resolve` 的 `when` 里追加 case，返回 `Display(title, summary)`。
3. 仅做展示层改动；如需依赖非 inputs 字段，请先扩展 `ContentBlock.ToolBlock`。

### `ToolCallInputExtractor`

从 tool inputs JSON 抽 header 右侧一行 summary 和展开态参数列表。`KEY_PRIORITY` 指定每个 tool 的字段优先级；未命中时走 `GENERIC_KEYS` 兜底；JSON 解析失败时回退成原文截断到 80 字。

### `CollapsibleContent`

工具调用展开区内的二次折叠容器，行为对齐 RN 侧 `CollapsibleContent.tsx`：

- `lines ≤ 5`：直接展示全部内容
- `lines > 5`：折叠态只显示第一行 + 右箭头；展开态最多显示 30 行，超出追加 `… (共 N 行)`，点击任意处收起
- 使用 `rememberSaveable` 管理展开状态，流式增量更新不会坍塌已展开的状态

### `SessionGrouping`

Session 按时间分桶的纯函数逻辑，不含 UI。提供：

- `groupSessions(sessions, now, zone)` — 将 Session 列表分为「今天/昨天/7天内/30天内」近期桶 + 年月历史桶，返回 `GroupedSessions`
- `defaultExpanded(grouped, now)` — 初始展开状态：近期桶默认展开，历史月份桶默认折叠，当年年份桶展开
- `SessionBucket` sealed class：`Recent` / `Month` / `Year`

### `SessionPanel`

左栏 Session 列表面板，提供历史 Session 切换、删除会话（`onDeleteSession` 回调，实际删除由上层 `ChatScreen` 弹确认框后调用 `SessionViewModel.deleteSession`）、跳转 Settings / SubAgents 入口。`agentName` 非空时进入精简模式（隐藏功能区）。

> 「新建对话」按钮已移至 [`ChatScreen`](ChatScreen.kt) 顶部右侧胶囊内，直接调 `ChatViewModel.newSession()`。

### `TodoPanel`

右栏 Todo 面板，显示当前对话中 Agent 任务的 checklist 状态。

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改顶部 agent 胶囊 / 活动指示器动画 | `AgentPill.kt` + `AgentPillAnimations.kt` |
| 改三栏布局（脚手架结构） | `ChatScreen.kt` |
| 改手机单栏手势滑动逻辑 | `SlidingThreePaneLayout.kt` |
| 改消息列表滚动行为 | `MessageList.kt` |
| 改消息渲染分发逻辑 | `StreamingMessage.kt` |
| 改思考块展开/折叠 | `ThinkingCard.kt` |
| 改工具调用块样式/状态 | `ToolCallCard.kt` |
| 改工具调用展开区内二次折叠行为 | `CollapsibleContent.kt` |
| 新增/修改 tool 名在卡片 header 的显示规则 | `ToolDisplayName.kt` |
| 改 tool inputs 摘要字段优先级 | `ToolCallInputExtractor.kt` |
| 改 Session 时间分桶/排序逻辑 | `SessionGrouping.kt` |
| 改 Session 列表面板 | `SessionPanel.kt` |
| 改 Todo 面板 | `TodoPanel.kt` |

---

> 新增消息类型或改动三栏结构后，请同步更新本 README 与上级 [ui/README.md](../README.md)。
