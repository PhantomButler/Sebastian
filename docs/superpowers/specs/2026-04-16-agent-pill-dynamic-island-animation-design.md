# AgentPill 灵动岛式动画设计

**日期：** 2026-04-16
**范围：** Android App · ChatScreen 顶部 agent 名称胶囊

---

## Context

主对话页顶部的 agent 名称悬浮组件（[ChatScreen.kt:246-264](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt#L246)）目前是静态 `GlassSurface(CircleShape) { Text }`。Agent 正在工作时没有视觉反馈，用户只能通过消息区的 streaming 文本或 ThinkingCard 推断状态。

目标：Agent 处于非 IDLE 状态时，胶囊从尾部向右"展开"一小块动画区域显示运行动画，状态结束胶囊收回原样 —— 类似 iOS 灵动岛的胶囊变化。动画视觉走"贾维斯 / 赛博朋克 AI 活动指示器"方向。

**已具备的基础**：[ChatViewModel.kt:34](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt#L34) 已定义 `AgentAnimState { IDLE, THINKING, STREAMING, WORKING }`，并在相应 StreamEvent 处理处切换完毕（`ThinkingBlockStart` → THINKING，`TextBlockStart` → STREAMING，`ToolBlockStart` → WORKING，`TurnResponse / TurnInterrupted` → IDLE）。本次改动只消费该状态，不改 ViewModel。

---

## Non-Goals

- 不改后端 / 不改 stream event 协议
- 不引入 Lottie 或任何第三方动画库（用 Compose `Canvas` + `rememberInfiniteTransition`）
- 不改 `AgentAnimState` 的 4 个值及其触发时机
- 不做 iOS 端变更

---

## 状态粒度

4 个状态在 UI 层合并为 3 档：

| `AgentAnimState` | `AgentPillMode` | 渲染 |
|---|---|---|
| `IDLE` | `COLLAPSED` | 只显示 Text，胶囊收起 |
| `THINKING` | `THINKING` | Text + OrbsAnimation（4 光团漂移） |
| `STREAMING` | `ACTIVE` | Text + HudAnimation（Jarvis HUD） |
| `WORKING` | `ACTIVE` | Text + HudAnimation（同上） |

`STREAMING` 与 `WORKING` 合并为同一 `ACTIVE` 模式，因为：
1. 两者对用户心智都是"正在响应"，区分工具调用 vs 吐字已由消息区的 ToolCallCard / TextBlock 承担
2. 合并后 `STREAMING ↔ WORKING` 频繁切换不会重启动画（零成本的第一层防抖）

---

## 组件拆分

| 文件 | 状态 | 职责 |
|---|---|---|
| `ui/chat/AgentPill.kt` | 新增 | 胶囊壳：GlassSurface + Row{Text, AnimatedVisibility{Tail}}，消费 `AgentAnimState`，处理展开/收起与防抖 |
| `ui/chat/AgentPillAnimations.kt` | 新增 | 两种尾部动画绘制：`OrbsAnimation`、`HudAnimation`；轨迹常量与 defaults |
| `ui/theme/Color.kt` | 修改 | 追加 `AgentAccentLight / AgentAccentDark`（Jarvis 蓝 token，不进 colorScheme） |
| `ui/chat/ChatScreen.kt` | 修改 | `ChatScreen.kt:246-264` 原胶囊那段 Box 替换为 `AgentPill(agentName, chatState.agentAnimState, glassState)` |

AgentPill.kt 预期 < 150 行；AgentPillAnimations.kt 含两个动画 + 常量，< 300 行。

---

## 展开机制

胶囊宽度不自己算，交给 Compose 根据内容自适应 + spring：

```kotlin
Row(
    verticalAlignment = Alignment.CenterVertically,
    modifier = Modifier
        .animateContentSize(
            animationSpec = spring(dampingRatio = 0.7f, stiffness = 400f),
        )
        .padding(horizontal = 16.dp, vertical = 10.dp),
) {
    Text(agentName ?: "Sebastian", ...)
    AnimatedVisibility(
        visible = stableMode != COLLAPSED,
        enter = expandHorizontally() + fadeIn(tween(200)),
        exit = shrinkHorizontally() + fadeOut(tween(200)),
    ) {
        Spacer(Modifier.width(8.dp))
        AnimatedContent(
            targetState = stableMode,
            transitionSpec = { fadeIn(tween(200)) togetherWith fadeOut(tween(200)) },
        ) { mode ->
            when (mode) {
                THINKING -> OrbsAnimation(accent)
                ACTIVE -> HudAnimation(accent)
                else -> Spacer(Modifier.size(0.dp))
            }
        }
    }
}
```

Spring 参数 `dampingRatio = 0.7f, stiffness = 400f`：约 400–500ms 到位，轻微回弹 —— 灵动岛观感。

---

## 快速切换处理

三层防护：

**第一层 · 语义级合并（零成本）**
`STREAMING ↔ WORKING` 映射到同一 `ACTIVE`，此类切换对 AgentPill 不可见，动画不重启。

**第二层 · 80ms 短驻留防抖**
AgentPill 内部不直接消费 `chatState.agentAnimState`，过一次稳定化：

```kotlin
val targetMode = chatState.agentAnimState.toPillMode()
val stableMode by produceState(initialValue = COLLAPSED, key1 = targetMode) {
    delay(80L)
    value = targetMode
}
```

- 新 mode 来了，启动 80ms 定时器；80ms 内又来新 mode → 上一次 delay 被 cancel，重新计时
- 只有稳定住 80ms 的值会推给动画层
- 80ms 选值理由：< 动画时长（400–500ms），用户无感；> 典型瞬时中间态

**第三层 · Compose 原生打断**
即便前两层都没挡住，`animateContentSize(spring)` 与 `AnimatedContent` 本身支持"进行中被打断"，会从当前插值位置继续到新目标，不会从头重播。

---

## 视觉参数

### 颜色

`ui/theme/Color.kt` 追加：

```kotlin
// ── Agent 活动指示器（Jarvis 蓝）────────────────────────────────
// 不进入 colorScheme，由 AgentPill 直接引用（参考 SwitchChecked 的 pattern）
val AgentAccentLight = Color(0xFF6FC3FF)
val AgentAccentDark = Color(0xFF9FD6FF)
```

AgentPill 内部读 `isSystemInDarkTheme()` 选色。浅色主题下玻璃底偏白，glow 的 alpha 全乘 0.7 避免过曝。

### 胶囊尺寸

保持现有：
- 文本 padding：`horizontal = 16.dp, vertical = 10.dp`
- 形状：`CircleShape`
- 收起态宽度：Text 内在宽度
- 展开态宽度：Text + 8.dp gap + Tail

### Tail 区域尺寸

| 模式 | Tail 宽 | Tail 高 |
|---|---|---|
| THINKING（光团） | 32.dp | 22.dp |
| ACTIVE（HUD） | 28.dp | 20.dp |

### 节奏

- 胶囊宽度：`animateContentSize(spring(dampingRatio = 0.7f, stiffness = 400f))`
- Tail 出现/消失：`AnimatedVisibility(expandHorizontally + fadeIn(200ms), shrinkHorizontally + fadeOut(200ms))`
- THINKING ↔ ACTIVE Tail 交替：`AnimatedContent(fadeIn(200ms) togetherWith fadeOut(200ms))`

---

## 动画实现

### OrbsAnimation（THINKING · 4 光团漂移）

容器 `32.dp × 22.dp`，4 颗 `7.dp` 光团，独立周期漂移。

```kotlin
@Composable
fun OrbsAnimation(accent: Color, modifier: Modifier = Modifier) {
    val transition = rememberInfiniteTransition(label = "orbs")
    val p1 = transition.normalizedTime(3800, label = "orb1")  // 0f..1f
    val p2 = transition.normalizedTime(4400, label = "orb2")
    val p3 = transition.normalizedTime(5000, label = "orb3")
    val p4 = transition.normalizedTime(4100, label = "orb4")

    Canvas(modifier.size(32.dp, 22.dp)) {
        drawOrb(p1, basePos = Offset(3.5.dp, 11.5.dp), TRAJECTORY_1, accent)
        drawOrb(p2, basePos = Offset(13.5.dp, 7.5.dp), TRAJECTORY_2, accent)
        drawOrb(p3, basePos = Offset(21.5.dp, 15.5.dp), TRAJECTORY_3, accent)
        drawOrb(p4, basePos = Offset(25.5.dp, 9.5.dp), TRAJECTORY_4, accent)
    }
}
```

**轨迹常量**（移植自视觉稿 v5，基准坐标已按 +3.5dp 对齐到光团圆心）：

```kotlin
private val TRAJECTORY_1 = listOf(
    Keyframe(0.00f, Offset(0.dp, 0.dp), alpha = 0.6f),
    Keyframe(0.50f, Offset(8.dp, -4.dp), alpha = 1.0f),
    Keyframe(1.00f, Offset(0.dp, 0.dp), alpha = 0.6f),
)
private val TRAJECTORY_2 = listOf(
    Keyframe(0.00f, Offset(0.dp, 0.dp), alpha = 0.9f),
    Keyframe(0.40f, Offset(-4.dp, 5.dp), alpha = 0.5f),
    Keyframe(0.75f, Offset(4.dp, -3.dp), alpha = 1.0f),
    Keyframe(1.00f, Offset(0.dp, 0.dp), alpha = 0.9f),
)
private val TRAJECTORY_3 = listOf(
    Keyframe(0.00f, Offset(0.dp, 0.dp), alpha = 0.4f),
    Keyframe(0.50f, Offset(-10.dp, -6.dp), alpha = 1.0f),
    Keyframe(1.00f, Offset(0.dp, 0.dp), alpha = 0.4f),
)
private val TRAJECTORY_4 = listOf(
    Keyframe(0.00f, Offset(0.dp, 0.dp), alpha = 1.0f),
    Keyframe(0.45f, Offset(-12.dp, 4.dp), alpha = 0.5f),
    Keyframe(1.00f, Offset(0.dp, 0.dp), alpha = 1.0f),
)
```

插值使用 `EaseInOutQuad`（等价于 CSS 默认 `ease-in-out`）。

**Glow 绘制**：每颗光团画 3 层：
1. 外辉：`drawCircle(radius = 3.5.dp × 2.8)`，`RadialGradient(accent × alpha × 0.25, Transparent)`
2. 中辉：`drawCircle(radius = 3.5.dp × 1.6)`，`RadialGradient(accent × alpha × 0.55, Transparent)`
3. 核心：`drawCircle(radius = 3.5.dp)`，`accent × alpha`，`blendMode = BlendMode.Plus`

用 `BlendMode.Plus` 模拟视觉稿中的 `mix-blend-mode: screen`，在深色背景上光团重叠处会加亮。避免用 `Modifier.blur`（离屏渲染）。

### HudAnimation（ACTIVE · Jarvis HUD）

容器 `28.dp × 20.dp`。

```kotlin
@Composable
fun HudAnimation(accent: Color, modifier: Modifier = Modifier) {
    val t = rememberInfiniteTransition(label = "hud")
    val outerRot = t.animateFloat(0f, -360f, tween(1400, easing = LinearEasing))
    val innerRot = t.animateFloat(0f, 360f, tween(900, easing = LinearEasing))
    val pingPhase = t.animateFloat(0f, 1f, tween(1400, easing = CubicBezierEasing(0.2f, 0.8f, 0.2f, 1f)))
    val corePhase = t.animateFloat(0f, 1f, tween(800, easing = EaseInOutQuad))

    Canvas(modifier.size(28.dp, 20.dp)) {
        val center = Offset(size.width / 2, size.height / 2)
        drawPing(center, pingPhase, accent)
        drawDashedArc(center, radius = 8.dp, rotation = outerRot,
            dash = 22f to 28f, strokeWidth = 1.5.dp, accent)
        drawDashedArc(center, radius = 4.5.dp, rotation = innerRot,
            dash = 8f to 18f, strokeWidth = 1.2.dp, accent)
        drawCore(center, corePhase, accent)
    }
}
```

**断弧绘制**：`drawArc(useCenter = false)` + `PathEffect.dashPathEffect(floatArrayOf(dash1, dash2))`。旋转用 `rotate(angle, center)` block 包裹。

**辉光**：每个描边先画一层 alpha 0.5、`strokeWidth × 2.0` 的模糊底，再画本体（模拟 `drop-shadow` 的 halo）。

**Ping 扩散**：半径从 `1.dp` 线性到 `10.dp`，alpha = `1f - pingPhase`，在弧线下方绘制（最先画）。

**核心脉冲**：半径 `1.8.dp`，`scale = lerp(0.8f, 1.15f, sinLike(corePhase))`，`alpha = lerp(0.5f, 1.0f, sinLike(corePhase))`。

---

## 生命周期与省电

- 顶部栏随 ChatScreen 一起进入/离开组合；ChatScreen 走 `onAppStart / onAppStop` 管 SSE，后台时 `agentAnimState` 稳在最后值
- `rememberInfiniteTransition` 只在 Tail Canvas 进入组合树时 tick；IDLE 下 `AnimatedVisibility(false)` 让 Canvas 离开组合树，InfiniteTransition 自动停
- 不额外加暂停逻辑
- 系统"动画时长缩放"（`Settings.Global.ANIMATOR_DURATION_SCALE`）：读一次，若为 0 则 Tail 渲染单帧静态图，胶囊宽度动画用 `snap()` 直切

---

## Session 切换 / SubAgent / 审批跳转

- `switchSession` 等入口会把 `agentAnimState` 初始化回 IDLE（ViewModel 已处理），AgentPill 自动收回，与正常逻辑一致
- SubAgent 模式下 `agentName` 非 null（如 `"日程管家"`），胶囊显示该名称，动画逻辑不变 —— AgentPill 不区分主管家 / SubAgent

---

## 无障碍

AgentPill 外层加 `Modifier.semantics`：

```kotlin
semantics {
    contentDescription = agentName ?: "Sebastian"
    stateDescription = when (stableMode) {
        COLLAPSED -> ""                    // 无状态播报
        THINKING -> "正在思考"
        ACTIVE -> "正在响应"
    }
}
```

TalkBack 在状态切换时播报。

---

## 测试

### 单元测试（`tests/unit`）

- `AgentPillStateMapperTest`
  - `mapIdle_returnsCollapsed`
  - `mapThinking_returnsThinking`
  - `mapStreaming_returnsActive`
  - `mapWorking_returnsActive`
- `OrbTrajectoryTest`
  - `trajectory1_atStartAndEnd_returnsOrigin`
  - `trajectory1_atMiddle_returnsPeakOffset`
  - `trajectory2_atKeyframeBoundary_matchesExactValue`
  - 纯数学插值，不依赖 Compose runtime

### Compose UI 测试（`tests/androidTest`）

- `AgentPillTest · showsOnlyText_whenIdle`
- `AgentPillTest · showsOrbs_whenThinking`
- `AgentPillTest · showsHud_whenStreaming`
- `AgentPillTest · showsHud_whenWorking`
- `AgentPillTest · debouncesRapidStateChanges`（连续 push `IDLE → THINKING → STREAMING`，间隔 < 80ms，最终只看到 ACTIVE 的 HUD）
- `AgentPillTest · semantics_reflectState`（stateDescription 随状态变化）

动画帧数 / 颜色断言不做（视觉稳定性人工过目）。

---

## 开放项

无。等 implementation plan。
