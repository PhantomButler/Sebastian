# Android 三面板滑动：加阻尼 + 弹簧动画

## Context

Android App 主对话页面（`ChatScreen`）使用 `SlidingThreePaneLayout` 实现左/中/右三面板横向切换。当前实现的动画体感偏机械：

- **拖拽阶段**：`coerceIn(-paneWidthPx, paneWidthPx)` 硬钳制，拖到边界完全卡住，无任何视觉反馈
- **松手回弹**：`tween(200ms, FastOutSlowInEasing)` 线性缓动，丢弃了 `velocityTracker` 算出的 fling 速度
- **按钮触发**：`tween(300ms, FastOutSlowInEasing)`，平直收尾

iOS / 主流 Material 3 App 在类似交互上普遍带 rubberband 阻尼 + spring 回弹，体感更"活"。本次改动让三面板的横向手势/切换具备这两种弹性。

## 非目标

- 不改 `SlidingThreePaneLayout` 对外签名，`ChatScreen` 不动
- 不引入新依赖（全部用 `androidx.compose.animation.core` 已有 API）
- 不调整面板宽度比例 / 触发阈值 / 滑动方向语义
- 不为动画行为本身写 instrumentation test（成本远大于收益），只为新提取的纯函数写单测

## 架构

**单文件改动**：`ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SlidingThreePaneLayout.kt`

变化集中在三处：

1. 拖拽阶段（`horizontalDrag` 块内）替换硬钳制为 rubberband 公式
2. 松手 fling 与按钮触发的 `animateTo` 把 `tween` 换成 `spring`，并把松手时的 `velocity` 透传给 spring
3. 松手时 `onPaneChange(...)` 提前到 spring 启动**之前**调用，让外部 state 与视觉同步

文件预计从 202 行增到约 230 行，远低于 800 行红线。

## 详细设计

### 1. Rubberband 公式

新增文件级 private 纯函数：

```kotlin
internal fun rubberband(distance: Float, dimension: Float): Float {
    if (dimension <= 0f) return 0f
    val k = 0.55f
    return (k * distance * dimension) / (k * distance + dimension)
}
```

性质：
- `rubberband(0, dim) == 0`
- 单调递增
- `f(x) < x` 恒成立（衰减性，无放大区段）
- `lim distance→∞ rubberband(distance, dim) = dim`（渐近线）
- 对应公式与 iOS UIKit UIScrollView 的 overscroll 行为一致，0.55 为社区共识默认系数

### 2. 拖拽阶段应用 rubberband

替换 `SlidingThreePaneLayout.kt` 当前 `horizontalDrag` 内：

```kotlin
val newOffset = (offset.value + dragAmount)
    .coerceIn(-paneWidthPx, paneWidthPx)
```

为：

```kotlin
val maxOver = paneWidthPx * 0.25f   // 越界距离上限
val newRaw = offset.value + dragAmount
val newOffset = when {
    newRaw > paneWidthPx ->
        paneWidthPx + rubberband(newRaw - paneWidthPx, maxOver)
    newRaw < -paneWidthPx ->
        -paneWidthPx - rubberband(-newRaw - paneWidthPx, maxOver)
    else -> newRaw
}
```

中间区段（`|newRaw| <= paneWidthPx`）保持 1:1 跟手；越界时按 rubberband 衰减。`maxOver = 25%` 决定越界距离上限——渐近趋近 `0.25 * paneWidthPx`（约屏宽 19%），需要"无限大"的拖动距离才会接近。在等于 `maxOver` 距离的拖动下实际越界 ≈ `0.355 * 0.25 * paneWidthPx`。

### 3. Spring 替代 tween

定义文件级常量便于统一：

```kotlin
private val PaneSpringSpec = spring<Float>(
    dampingRatio = 0.75f,    // Material LowBouncy
    stiffness = 380f,         // 介于 StiffnessMediumLow(400) 与 Low(200)
)
```

应用到两处。

**位置 A**：`LaunchedEffect(activePane, paneWidthPx)` 块（按钮触发同步）：

```kotlin
if (offset.value != target) {
    offset.animateTo(target, PaneSpringSpec)
}
```

**位置 B**：松手 fling 块：

```kotlin
val velocity = velocityTracker.calculateVelocity().x   // 已经在算，原本被丢弃
// ... target 计算逻辑不变 ...

// 关键改动：先通知外部 state，再启动 spring
onPaneChange(
    when (target) {
        paneWidthPx -> SidePane.LEFT
        -paneWidthPx -> SidePane.RIGHT
        else -> SidePane.NONE
    }
)

scope.launch {
    offset.animateTo(
        targetValue = target,
        animationSpec = PaneSpringSpec,
        initialVelocity = velocity,
    )
}
```

`initialVelocity = velocity` 让 spring 承接拖拽时的 fling 速度——手劲大时回弹也快、过冲更明显，体感上变成"惯性 → 弹簧"的连续动作而不是"惯性 → 突然 spring 从 0 起步"。

### 4. `onPaneChange` 时机调整

**原行为**：`animateTo` 完全结束后才调 `onPaneChange`。spring 收尾要震荡 1-2 次才停，期间 `BackHandler.enabled` 还停留在旧 state，按返回键不会关面板，体感是"卡了一下"。

**新行为**：决定 target 后**立即** `onPaneChange(...)`，再异步启动 spring。

由于 `LaunchedEffect(activePane, paneWidthPx)` 内有 `if (offset.value != target)` 守卫，不会因为 state 变化触发第二次 spring（target 与正在运行的 spring 一致）。

按钮触发路径（位置 A）不需要这个调整——activePane 本来就是按钮 onClick 主动改的。

### 5. 测试策略

**新增** `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/RubberbandTest.kt`，覆盖 `rubberband(d, dim)` 纯函数：

| 用例 | 期望 |
|---|---|
| `rubberband(0, 100)` | `== 0f` |
| `rubberband(50, 100)` | `> 0f && < 50f` |
| `rubberband(10000, 100)` | 趋近 `100f`（渐近线） |
| 单调性 | `d1 < d2 ⇒ rubberband(d1, 100) < rubberband(d2, 100)` |
| `rubberband(d, 0)` | `== 0f`（防御除零，公式天然成立） |

为让纯函数可测，必须把 `rubberband` 放在 `SlidingThreePaneLayout.kt` 的**顶层**（不嵌在 Composable 里），保留 `private` 但使用 `@VisibleForTesting`（或暂时改 `internal`）以便测试。具体可见性策略由实现者按 Kotlin 习惯确定。

**手动验证清单**（无单测覆盖动画行为，必须实机或模拟器跑）：

1. 中间状态向右拖到左面板打开 → 继续右拖 → 阻力可感知地变大、有越界距离上限
2. 拖完松手 → spring 回弹，看到 1 次轻微过冲
3. 中间状态快速向左 fling → spring 速度承接，过冲明显比慢速松手更大
4. 点左上角菜单按钮打开左面板 → spring 收尾带轻微 Q 弹
5. 面板打开后立即按返回键 → 立刻关闭（验证 `onPaneChange` 时机调整后 BackHandler 同步）
6. 打开左面板状态下点击 scrim → 关闭动画也是 spring（走 LaunchedEffect 路径）

## 风险与回退

- **风险 1**：spring 收尾的过冲幅度与 LazyColumn 内容横向对齐有偏差，可能让某些 sticky 元素看起来"抖一下"。回退：把 dampingRatio 从 0.75 调到 0.85 减弱过冲。
- **风险 2**：rubberband 越界时 `offset.value > paneWidthPx`，`Box.offset { IntOffset(offset.value.roundToInt(), 0) }` 会让主内容超出屏幕。这是预期行为（视觉上能看到面板"被拉出来一点"），但 `clipToBounds()` 已在最外层 `BoxWithConstraints` 上设置，超出部分会被裁剪——观感正确。
- **风险 3**：`onPaneChange` 提前调用导致外部 state 和视觉短时不一致。仅影响 `BackHandler` 与 ChatScreen 内部的若干 `derivedStateOf`，无业务副作用。

## 文件变更清单

| 文件 | 改动类型 |
|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SlidingThreePaneLayout.kt` | 修改：rubberband 公式、spring 常量、两处 animateTo、onPaneChange 时机 |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/RubberbandTest.kt` | 新增：rubberband 纯函数单测 |

不影响：
- `ChatScreen.kt`（API 不变）
- 任何 ViewModel / Repository / Data 层
- 任何 README（行为变化不影响导航与模块结构）
