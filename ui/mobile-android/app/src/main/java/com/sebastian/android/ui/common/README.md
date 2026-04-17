# common 模块

> 上级：[ui/README.md](../README.md)

跨领域复用组件，供所有 Screen / Feature 引用，不含页面级业务逻辑。

## 目录结构

```text
common/
├── AnimationTokens.kt      # 全局动画时长常量
├── ApprovalSummary.kt      # 审批摘要生成（summarizeApproval / clipReason）
├── ErrorBanner.kt          # 错误横幅（可选操作按钮）
├── GlobalApprovalBanner.kt # 全局审批横幅（悬浮，覆盖所有页面）
├── MarkdownDefaults.kt     # Markdown 颜色/排版/组件配置（含代码块语法高亮）
├── MarkdownView.kt         # 纯 Compose Markdown 渲染组件
├── SebastianIcons.kt       # 自定义图标集（ImageVector 懒加载）
├── SebastianSwitch.kt      # 苹果风格绿色 Switch（跟随 Light/Dark 自动切换色值）
├── ToastCenter.kt          # 公共 Toast 入口（节流 + 同时刻最多一条）
└── glass/                  → [glass/README.md](glass/README.md)  # 液态玻璃组件库
```

## 模块说明

### `GlobalApprovalBanner`

全局审批横幅，悬浮在所有页面之上（`zIndex(1f)`），显示第一条待审批请求，含拒绝/允许按钮和"查看详情"跳转。由 `GlobalApprovalViewModel` 驱动，审批事件入队，处理后自动弹出下一条。

### `MarkdownDefaults`

集中管理 Markdown 渲染的颜色、排版和组件配置，包括代码块语法高亮主题，供 `MarkdownView` 引用。

### `MarkdownView`

纯 Compose 实现，接受 `text: String`，使用 `rememberMarkdownState(retainState = true) + Markdown()` 渲染（multiplatform-markdown-renderer v0.40.2）。样式通过 `MarkdownDefaults` 注入，无 `AndroidView` 依赖。

### `ErrorBanner`

通用错误横幅，支持可选 `actionLabel` + `onAction` 操作按钮。三态复用于 `ChatScreen`：服务器未配置 / 网络断开 / SSE 连接失败（含重试按钮）。

### `ApprovalSummary`

审批摘要生成工具，将 tool 名 + inputs JSON 转换成供 `GlobalApprovalBanner` 展示的可读标题与详情：

- `summarizeApproval(toolName, toolInputJson)` — 按 tool 类型（bash/write/read/delete/http/其他）返回 `ApprovalSummary(title, detail)`，detail 最长 120 字符
- `clipReason(reason)` — 裁剪后端 reason 字符串到第一个意义子句（截止 `（` / `，` / `,` / `。`）

### `SebastianSwitch`

苹果风格绿色 Switch，签名与 Material3 `Switch` 完全一致（`checked` / `onCheckedChange` / `modifier` / `enabled`）。跟随系统 Dark/Light 模式自动切换绿色色值（`SwitchCheckedDark` / `SwitchCheckedLight`）。

> 所有设置页的开关应使用 `SebastianSwitch` 替代原生 `Switch`，以保持视觉一致。

### `AnimationTokens`

统一管理全局动画时长常量（`Fast` / `Normal` / `Slow`），避免各处硬编码毫秒值。

### `SebastianIcons`

从 React Native 版本（`ui/mobile/`）迁移的自定义图标集，每个图标为懒加载 `ImageVector`，与 Material Icons 用法一致。

### `ToastCenter`

统一的一次性 Toast 入口。内置两层防抖：

1. **节流**：同 `key`（默认为 `message` 本身）在 `throttleMs`（默认 1500ms）内重复调用被丢弃
2. **同时刻最多一条**：进程范围内只持有一个 Toast 引用，新调用先 cancel 再显示

```kotlin
import com.sebastian.android.ui.common.ToastCenter

// 最简：同文案 1.5s 内只弹一次
ToastCenter.show(context, "已在目标会话")

// 同文案不同语义，用 key 区分
ToastCenter.show(context, "已在目标会话", key = "already-in-session")

// 自定义节流窗口
ToastCenter.show(context, message = "...", throttleMs = 3000L)
```

非 Composable 处（ViewModel / 回调）也可直接调用，内部只持 `applicationContext`，不泄漏 Activity。

**禁止直接 `Toast.makeText(...).show()`**——所有一次性提示走 ToastCenter，以保证节流和单例显示。

### `glass/`

基于 `io.github.kyant0:backdrop` 封装的液态玻璃组件库（`GlassKit` / `GlassSurface` / `GlassButton`）。详见 [glass/README.md](glass/README.md)。

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改全局审批横幅逻辑 | `GlobalApprovalBanner.kt` + `viewmodel/GlobalApprovalViewModel.kt` |
| 改审批摘要显示（标题/详情抽取规则） | `ApprovalSummary.kt` |
| 改错误横幅样式/状态 | `ErrorBanner.kt` |
| 改 Markdown 渲染样式/配置 | `MarkdownDefaults.kt` |
| 改 Markdown 渲染逻辑 | `MarkdownView.kt` |
| 新增/修改自定义图标 | `SebastianIcons.kt` |
| 改动画时长全局常量 | `AnimationTokens.kt` |
| 改设置页开关样式/颜色 | `SebastianSwitch.kt` |
| 弹一次性 Toast 提示（防重复 + 同时刻最多一条） | `ToastCenter.kt` |
| 改液态玻璃组件 API | `glass/` → [glass/README.md](glass/README.md) |

---

> 新增复用组件后，请同步更新本 README 与上级 [ui/README.md](../README.md)。
