# ui 层

> 上级：[ui/mobile-android/README.md](../../../../../../../../README.md)

Jetpack Compose UI 层，按功能领域分包，所有 Screen / Page 以 Composable 函数实现。

## 目录结构

```text
ui/
├── chat/       → [chat/README.md](chat/README.md)               # 主对话三栏 Screen
├── common/     → [common/README.md](common/README.md)           # 跨领域复用组件
│   └── glass/  → [common/glass/README.md](common/glass/README.md) # 液态玻璃组件库
├── composer/   → [composer/README.md](composer/README.md)       # 消息输入区
├── navigation/ → [navigation/README.md](navigation/README.md)   # Type-safe 路由
├── settings/   → [settings/README.md](settings/README.md)       # 设置页组
├── subagents/  → [subagents/README.md](subagents/README.md)     # Sub-Agent 列表
└── theme/      → [theme/README.md](theme/README.md)             # Material3 主题
```

## 子模块说明

| 目录 | 职责 |
|------|------|
| [chat/](chat/README.md) | 主对话入口，`NavigableListDetailPaneScaffold` 三栏自适应布局 |
| [common/](common/README.md) | 跨页面复用组件（Glass 组件库、ErrorBanner、审批横幅、Markdown、图标） |
| [composer/](composer/README.md) | 消息输入区（Composer + SendButton，插槽架构） |
| [navigation/](navigation/README.md) | Type-safe 路由定义（`Route` sealed class） |
| [settings/](settings/README.md) | 设置页组（连接/账户、Provider、外观、高级） |
| [subagents/](subagents/README.md) | Sub-Agent 浏览与进入 AgentChat |
| [theme/](theme/README.md) | Material3 主题（品牌色 + Light/Dark） |

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改三栏布局（脚手架结构） | `chat/ChatScreen.kt` → [chat/README.md](chat/README.md) |
| 改手机单栏手势滑动逻辑 | `chat/SlidingThreePaneLayout.kt` |
| 改消息渲染（文本/思考/工具调用） | `chat/StreamingMessage.kt`、`ThinkingCard.kt`、`ToolCallCard.kt` |
| 改消息列表滚动行为 | `chat/MessageList.kt` |
| 改 Session 列表面板 | `chat/SessionPanel.kt` |
| 改 Todo 面板 | `chat/TodoPanel.kt` |
| 改输入框样式/行为 | `composer/Composer.kt` → [composer/README.md](composer/README.md) |
| 改发送/停止按钮状态 | `composer/SendButton.kt` |
| 改 Agent LLM 绑定主列表 | `settings/AgentBindingsPage.kt` |
| 改 Agent LLM 绑定次级页（Provider + Thinking） | `settings/AgentBindingEditorPage.kt` + `settings/components/EffortSlider.kt` + `settings/components/ProviderPickerDialog.kt` |
| 改全局审批横幅 | `common/GlobalApprovalBanner.kt` |
| 改错误横幅 | `common/ErrorBanner.kt` |
| 改 Markdown 渲染视图 | `common/MarkdownView.kt` |
| 弹一次性 Toast 提示 | `common/ToastCenter.kt` |
| 改液态玻璃组件 | `common/glass/` → [glass/README.md](common/glass/README.md) |
| 新增路由 | `navigation/Route.kt` + `MainActivity.kt` → [navigation/README.md](navigation/README.md) |
| 改设置页 | `settings/` → [settings/README.md](settings/README.md) |
| 改 Sub-Agent 列表 | `subagents/AgentListScreen.kt` |
| 改品牌色或主题 | `theme/Color.kt`、`theme/SebastianTheme.kt` → [theme/README.md](theme/README.md) |

---

> 新增 Screen 或重构页面结构后，请同步更新本 README、对应子目录 README 与上级 [ui/mobile-android/README.md](../../../../../../../../README.md)。
