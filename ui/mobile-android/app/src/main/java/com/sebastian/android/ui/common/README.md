# common 模块

> 上级：[ui/README.md](../README.md)

跨领域复用组件，供所有 Screen / Feature 引用，不含页面级业务逻辑。

## 目录结构

```text
common/
├── AnimationTokens.kt      # 全局动画时长常量
├── ErrorBanner.kt          # 错误横幅（可选操作按钮）
├── GlobalApprovalBanner.kt # 全局审批横幅（悬浮，覆盖所有页面）
├── MarkdownView.kt         # AndroidView 封装 Markwon 渲染
├── SebastianIcons.kt       # 自定义图标集（ImageVector 懒加载）
└── glass/                  → [glass/README.md](glass/README.md)  # 液态玻璃组件库
```

## 模块说明

### `GlobalApprovalBanner`

全局审批横幅，悬浮在所有页面之上（`zIndex(1f)`），显示第一条待审批请求，含拒绝/允许按钮和"查看详情"跳转。由 `GlobalApprovalViewModel` 驱动，审批事件入队，处理后自动弹出下一条。

### `MarkdownView`

`AndroidView` 包裹 `Markwon`，接受预渲染的 `CharSequence`（`renderedMarkdown`）。Markwon 实例由外部传入以便复用，避免每次 recomposition 重建。

### `ErrorBanner`

通用错误横幅，支持可选 `actionLabel` + `onAction` 操作按钮。三态复用于 `ChatScreen`：服务器未配置 / 网络断开 / SSE 连接失败（含重试按钮）。

### `AnimationTokens`

统一管理全局动画时长常量（`Fast` / `Normal` / `Slow`），避免各处硬编码毫秒值。

### `SebastianIcons`

从 React Native 版本（`ui/mobile/`）迁移的自定义图标集，每个图标为懒加载 `ImageVector`，与 Material Icons 用法一致。

### `glass/`

基于 `io.github.kyant0:backdrop` 封装的液态玻璃组件库（`GlassKit` / `GlassSurface` / `GlassButton`）。详见 [glass/README.md](glass/README.md)。

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改全局审批横幅逻辑 | `GlobalApprovalBanner.kt` + `viewmodel/GlobalApprovalViewModel.kt` |
| 改错误横幅样式/状态 | `ErrorBanner.kt` |
| 改 Markdown 渲染 | `MarkdownView.kt` |
| 新增/修改自定义图标 | `SebastianIcons.kt` |
| 改动画时长全局常量 | `AnimationTokens.kt` |
| 改液态玻璃组件 API | `glass/` → [glass/README.md](glass/README.md) |

---

> 新增复用组件后，请同步更新本 README 与上级 [ui/README.md](../README.md)。
