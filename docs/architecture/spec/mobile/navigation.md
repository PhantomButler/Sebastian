---
version: "1.0"
last_updated: 2026-04-11
status: in-progress
---

# 导航架构

*← [Mobile Spec 索引](INDEX.md)*

---

## 1. 三面板布局

主对话页采用「左侧历史会话 + 中间主对话 + 右侧任务进度」三面板结构，通过 `ThreePaneScaffold`（`androidx.compose.material3.adaptive`）实现。

```
┌──────────────┬───────────────────────────────┬────────────────┐
│  SessionPanel│         ChatContent            │   TodoPanel    │
│              │                                │                │
│  历史会话     │  消息列表                       │  任务进度       │
│  + 导航入口   │  + Composer                    │  + Todo 列表   │
│              │                                │                │
│  300dp       │  flex: 1（主内容）              │  300dp         │
└──────────────┴───────────────────────────────┴────────────────┘
```

**面板宽度**：左右两侧面板固定 `300dp`，中间主内容设 `minWidth = 700dp`。

---

## 2. 自适应行为

`ThreePaneScaffold` 基于 `WindowSizeClass` 和可用宽度自动决定布局模式，无需手写条件判断。

### 切换规则

切换阈值 = 侧栏宽度 + 主内容 minWidth = **300 + 700 = 1000dp**

| 场景 | 屏幕宽度（dp）| 模式 | 说明 |
|------|-------------|------|------|
| 手机竖屏 | 360–430 | 滑出推走（Slide-away）| 侧栏滑入，主内容同步向反方向推出屏幕 |
| 手机横屏 | 700–900 | 滑出推走 | 宽度仍不足 1000dp |
| 平板竖屏 | 800–960 | 滑出推走 | 宽度仍不足 1000dp |
| 平板横屏 | 1200–1600 | 常驻（Persistent）| 左右面板固定展开，主内容与侧栏并排 |
| Z Fold 展开横屏 | ~1200 | 常驻 | 铰链处天然分隔左右两栏 |

> 这一规则同时满足：手机和竖屏平板均为滑出推走模式，平板横屏才常驻，不需要监听旋转事件。

### 双侧边栏嵌套

`ThreePaneScaffold` 原生支持三面板，左右两侧独立管理开关状态：

```kotlin
val scaffoldState = rememberThreePaneScaffoldState()

ThreePaneScaffold(
    scaffoldState = scaffoldState,
    listPane = { SessionPanel(...) },          // 左侧
    detailPane = { ChatContent(...) },          // 中间（主）
    extraPane = { TodoPanel(...) },             // 右侧
)
```

左右侧栏互斥打开（手机/竖屏平板滑出推走模式），或同时常驻（横屏平板 Persistent 模式）。

**Slide-away 配置**：`ThreePaneScaffold` 通过 `paneMotion` 参数覆盖默认动画，使侧栏入场时主内容同步退场（`ExitToLeft` / `ExitToRight`），无遮罩（scrim）叠加：

```kotlin
ThreePaneScaffold(
    scaffoldState = scaffoldState,
    paneMotion = ThreePaneScaffoldDefaults.slideMotion,   // 侧栏入 → 主内容同步推出
    listPane = { SessionPanel(...) },
    detailPane = { ChatContent(...) },
    extraPane = { TodoPanel(...) },
)
```

打开侧栏时主内容完全退出屏幕（不露出），关闭时原路滑回，无黑色遮罩层，空间感更强。

---

## 3. 手势与交互

### 手机 / 竖屏平板滑出推走模式

| 手势 | 行为 |
|------|------|
| 从左边缘右滑 | 拉出 SessionPanel，主内容同步向右推出屏幕 |
| 从右边缘左滑 | 拉出 TodoPanel，主内容同步向左推出屏幕 |
| 侧栏展开时向反方向滑动 | 关闭侧栏，主内容滑回 |
| Header 汉堡按钮 | 打开/关闭 SessionPanel |
| Header 右侧按钮（预留）| 打开/关闭 TodoPanel |

### 平板常驻模式

侧栏始终可见，无手势开关逻辑。主内容区始终可交互，无需遮罩层。

### 与 RecyclerView/LazyColumn 的手势冲突

`ThreePaneScaffold` 的横向手势识别基于 `nestedScrollConnection`，与 `LazyColumn` 的纵向滚动天然不冲突——横向滑动优先触发面板切换，纵向滑动由列表消费，无需额外手势拦截代码。

> 这是 RN 版 SwipePager 最大的痛点（Android hit-test 与 transform 不联动）在原生里完全不存在的原因。

---

## 4. 页面路由

使用 Compose Navigation，类型安全路由（`@Serializable` sealed class）。

```kotlin
@Serializable sealed class Route {
    @Serializable object Chat : Route()
    @Serializable object SubAgents : Route()
    @Serializable data class AgentSessions(val agentId: String) : Route()
    @Serializable data class SessionDetail(val sessionId: String) : Route()
    @Serializable object Settings : Route()
    @Serializable object SettingsConnection : Route()
    @Serializable object SettingsProviders : Route()
    @Serializable object SettingsProvidersNew : Route()
    @Serializable data class SettingsProvidersEdit(val providerId: String) : Route()
}
```

**导航栈结构**：

```
NavHost（根）
├── Chat（起始目的地，三面板）
├── SubAgents（Stack push，顶部返回键）
│   └── AgentSessions/{agentId}
│       └── SessionDetail/{sessionId}（三面板，同 Chat 结构）
└── Settings（Stack push）
    ├── SettingsConnection
    ├── SettingsProviders
    │   ├── SettingsProvidersNew
    │   └── SettingsProvidersEdit/{providerId}
    └── （后续：Appearance、Advanced）
```

**无底部 Tab Bar**：导航入口收敛在左侧 SessionPanel 内（Sub-Agents 入口、设置入口），与 RN 版当前结构一致。

---

## 5. 平板布局细节

### 右侧 TodoPanel 的常驻策略

右侧面板在不同屏幕尺寸下的展现策略可独立配置：

- 平板横屏（≥1000dp）：左侧 SessionPanel 常驻，右侧 TodoPanel 按需（有活跃任务时自动展开，否则折叠）
- 超宽屏（≥1400dp，如横屏 12 寸平板）：左右均常驻，三栏同时可见

通过 `WindowSizeClass` 枚举值（`Compact` / `Medium` / `Expanded`）在 ViewModel 中维护每个面板的展开状态。

### Foldable 设备

Samsung Z Fold 等折叠屏展开时，系统报告 `WindowSizeClass.Expanded`，`ThreePaneScaffold` 自动进入常驻模式，铰链自然成为左右两栏分界，无需特殊处理。

---

## 6. 动画

面板开关动画由 `ThreePaneScaffold` 内置提供，基于 `spring` 曲线（速度感知弹性），与系统 Predictive Back 手势动画兼容。

如需定制开关速度或阻尼，可通过 `ThreePaneScaffoldDefaults.paneMotion` 参数覆盖。

---

*← [Mobile Spec 索引](INDEX.md)*
