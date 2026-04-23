---
version: "1.0"
last_updated: 2026-04-23
status: implemented
---

# AgentPill 灵动岛式动画

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 概述

主对话页顶部的 agent 名称悬浮组件从静态 `GlassSurface(CircleShape) { Text }` 升级为灵动岛式动画胶囊。Agent 处于非 IDLE 状态时，胶囊从尾部向右展开动画区域显示运行动画，状态结束收回原样。

动画视觉走"贾维斯 / 赛博朋克 AI 活动指示器"方向。

---

## 2. 非目标

- 不改后端 / 不改 stream event 协议
- 不引入 Lottie 或任何第三方动画库（用 Compose `Canvas` + `rememberInfiniteTransition`）
- 不改 `AgentAnimState` 的值及其触发时机
- 不做 iOS 端变更

---

## 3. 状态映射

`AgentAnimState`（5 值）映射到 `AgentPillMode`（4 值）：

| `AgentAnimState` | `AgentPillMode` | 渲染 |
|---|---|---|
| `IDLE` | `COLLAPSED` | 只显示 Text，胶囊收起 |
| `PENDING` | `BREATHING` | Text + BreathingHalo（彩虹渐变旋转环） |
| `THINKING` | `THINKING` | Text + OrbsAnimation（4 光团漂移） |
| `STREAMING` | `ACTIVE` | Text + HudAnimation（Jarvis HUD） |
| `WORKING` | `ACTIVE` | Text + HudAnimation（同上） |

> **实现增强**：代码比 spec 多了 `PENDING` → `BREATHING` 映射和 `BreathingHalo` 动画，用于 agent 等待 turn 开始时的呼吸指示。

`STREAMING` 与 `WORKING` 合并为同一 `ACTIVE` 模式，此类切换对 AgentPill 不可见，动画不重启。

---

## 4. 组件结构

| 文件 | 职责 |
|---|---|
| `ui/chat/AgentPill.kt` | 胶囊壳：GlassSurface + Row{Text, AnimatedVisibility{Tail}}，消费 `AgentAnimState`，处理展开/收起与防抖 |
| `ui/chat/AgentPillAnimations.kt` | 三种尾部动画：`OrbsAnimation`、`HudAnimation`、`BreathingHalo`；轨迹常量 |
| `ui/theme/Color.kt` | `AgentAccentLight / AgentAccentDark`（Jarvis 蓝 token） |

AgentPill.kt 约 152 行；AgentPillAnimations.kt 约 401 行。

---

## 5. 展开机制

胶囊宽度由 Compose 根据内容自适应 + spring：

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
        // Tail 动画区域
    }
}
```

Spring 参数 `dampingRatio = 0.7f, stiffness = 400f`：约 400–500ms 到位，轻微回弹。

---

## 6. 快速切换处理

三层防护：

**第一层 · 语义级合并（零成本）**
`STREAMING ↔ WORKING` 映射到同一 `ACTIVE`，动画不重启。

**第二层 · 80ms 短驻留防抖**
```kotlin
val targetMode = chatState.agentAnimState.toPillMode()
val stableMode by produceState(initialValue = COLLAPSED, key1 = targetMode) {
    delay(80L)
    value = targetMode
}
```
80ms 内新 mode 来了重置计时器，只有稳定住 80ms 的值推给动画层。

**第三层 · Compose 原生打断**
`animateContentSize(spring)` 与 `AnimatedContent` 支持从当前插值位置继续到新目标。

---

## 7. 视觉参数

### 颜色

`ui/theme/Color.kt`：

```kotlin
val AgentAccentLight = Color(0xFF6FC3FF)
val AgentAccentDark = Color(0xFF9FD6FF)
```

AgentPill 读 `isSystemInDarkTheme()` 选色。

### Tail 区域尺寸

| 模式 | Tail 宽 | Tail 高 |
|---|---|---|
| BREATHING（彩虹环） | 32.dp | 22.dp |
| THINKING（光团） | 32.dp | 22.dp |
| ACTIVE（HUD） | 28.dp | 20.dp |

---

## 8. 动画实现

### OrbsAnimation（THINKING · 4 光团漂移）

容器 `32.dp × 22.dp`，4 颗 `7.dp` 光团，独立周期漂移（3.8s–5.0s）。

每颗光团画 3 层（外辉 → 中辉 → 核心），用 `BlendMode.Plus` 模拟 screen 混合。避免 `Modifier.blur`（离屏渲染）。

轨迹常量使用 `EaseInOutQuad` 插值。

### HudAnimation（ACTIVE · Jarvis HUD）

容器 `28.dp × 20.dp`。

- 外环：断弧旋转（-360°/1400ms）
- 内环：断弧反向旋转（360°/900ms）
- Ping 扩散：半径线性扩张 + alpha 渐隐
- 核心脉冲：正弦缩放 + 透明度变化

每个描边先画 alpha 0.5 模糊底再画本体（模拟 halo）。

### BreathingHalo（PENDING · 彩虹渐变旋转环）

> **实现增强**：spec 原文未包含此动画。代码额外实现了彩虹渐变旋转环，用于 PENDING 状态的呼吸指示。

---

## 9. 生命周期与省电

- `rememberInfiniteTransition` 只在 Tail Canvas 进入组合树时 tick
- IDLE 下 `AnimatedVisibility(false)` 让 Canvas 离开组合树，InfiniteTransition 自动停
- 系统"动画时长缩放"为 0 时渲染单帧静态图，胶囊宽度用 `snap()` 直切

---

## 10. 无障碍

```kotlin
semantics {
    contentDescription = agentName ?: "Sebastian"
    stateDescription = when (stableMode) {
        COLLAPSED -> ""
        BREATHING -> "等待中"
        THINKING -> "正在思考"
        ACTIVE -> "正在响应"
    }
}
```

---

## 11. 测试

单元测试 `AgentPillStateMapperTest.kt` 覆盖 AgentAnimState → AgentPillMode 映射逻辑。

Compose UI 测试覆盖：
- IDLE 仅显示文本
- THINKING 显示光团
- STREAMING/WORKING 显示 HUD
- 快速状态切换防抖（连续 push 间隔 < 80ms）
- semantics 随状态变化

动画帧数/颜色断言不做（视觉稳定性人工过目）。

---

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
