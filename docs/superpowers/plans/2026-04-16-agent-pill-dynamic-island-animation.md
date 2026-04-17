# AgentPill 灵动岛式动画 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Android App 主对话页顶部 agent 名称胶囊加入非 IDLE 状态下的尾部动画（THINKING 4 光团 / ACTIVE Jarvis HUD），胶囊 spring 展开收起如 iOS 灵动岛。

**Architecture:** 新增 `AgentPill` composable（含 3 档状态映射 + 80ms 防抖 + AnimatedVisibility 展开 + AnimatedContent 交叉过渡），动画用 Compose `Canvas` + `rememberInfiniteTransition` 纯绘制。状态来源复用 `ChatUiState.agentAnimState`，不改 ViewModel。

**Tech Stack:** Kotlin + Jetpack Compose + Material3 + Canvas DrawScope + JUnit4

**相关 spec:** [2026-04-16-agent-pill-dynamic-island-animation-design.md](../specs/2026-04-16-agent-pill-dynamic-island-animation-design.md)

---

## 前置说明

**工作目录**：命令默认在 `ui/mobile-android/` 下执行，除 git 外。

**测试命令**：
```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest
```

**编译检查命令**（比 full build 快）：
```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```

**Android Studio MCP**：Kotlin 文件符号 / 引用 / 实现查询优先用 `mcp__android-studio-index__*`，避免 ripgrep。

**只加 unit test，不加 Compose UI test** —— 本仓库 `app/src/androidTest/` 目录不存在、Compose test infra 未配置；胶囊视觉需在用户 install 后人工验证。

---

## File Structure

| 路径 | 动作 | 职责 |
|---|---|---|
| `app/src/main/java/com/sebastian/android/ui/theme/Color.kt` | Modify | 追加 `AgentAccentLight / AgentAccentDark` token |
| `app/src/main/java/com/sebastian/android/ui/chat/AgentPill.kt` | Create | `AgentPillMode` enum + `AgentAnimState.toPillMode()` + `AgentPill` composable |
| `app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt` | Create | `Keyframe` / `interpolateTrajectory` / easing + 4 光团轨迹常量 + `OrbsAnimation` + `HudAnimation` |
| `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` | Modify | 第 246-264 行胶囊 Box 内部换成 `AgentPill(...)` |
| `app/src/test/java/com/sebastian/android/ui/chat/AgentPillStateMapperTest.kt` | Create | 4 态映射测试 |
| `app/src/test/java/com/sebastian/android/ui/chat/OrbTrajectoryTest.kt` | Create | 轨迹插值数学测试 |

---

## Task 1: `AgentPillMode` 枚举 + 状态映射

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/chat/AgentPill.kt`（先只放 enum + mapper，composable 后续 Task 填入）
- Test: `app/src/test/java/com/sebastian/android/ui/chat/AgentPillStateMapperTest.kt`

- [ ] **Step 1.1: 写失败的映射测试**

`app/src/test/java/com/sebastian/android/ui/chat/AgentPillStateMapperTest.kt`：

```kotlin
package com.sebastian.android.ui.chat

import com.sebastian.android.viewmodel.AgentAnimState
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * AgentAnimState → AgentPillMode 的 4→3 档映射。
 * STREAMING 和 WORKING 合并为 ACTIVE（同一 HUD 动画）。
 */
class AgentPillStateMapperTest {

    @Test
    fun `IDLE maps to COLLAPSED`() {
        assertEquals(AgentPillMode.COLLAPSED, AgentAnimState.IDLE.toPillMode())
    }

    @Test
    fun `THINKING maps to THINKING`() {
        assertEquals(AgentPillMode.THINKING, AgentAnimState.THINKING.toPillMode())
    }

    @Test
    fun `STREAMING maps to ACTIVE`() {
        assertEquals(AgentPillMode.ACTIVE, AgentAnimState.STREAMING.toPillMode())
    }

    @Test
    fun `WORKING maps to ACTIVE`() {
        assertEquals(AgentPillMode.ACTIVE, AgentAnimState.WORKING.toPillMode())
    }
}
```

- [ ] **Step 1.2: 跑测试确认失败**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.AgentPillStateMapperTest"
```

Expected: FAIL，`AgentPillMode` / `toPillMode` unresolved。

- [ ] **Step 1.3: 写最小实现**

`app/src/main/java/com/sebastian/android/ui/chat/AgentPill.kt`：

```kotlin
// com/sebastian/android/ui/chat/AgentPill.kt
package com.sebastian.android.ui.chat

import com.sebastian.android.viewmodel.AgentAnimState

/**
 * UI 层胶囊动画档位，合并自 [AgentAnimState]：
 * - IDLE → COLLAPSED（只显示 Text）
 * - THINKING → THINKING（4 光团）
 * - STREAMING / WORKING → ACTIVE（Jarvis HUD）
 */
enum class AgentPillMode { COLLAPSED, THINKING, ACTIVE }

fun AgentAnimState.toPillMode(): AgentPillMode = when (this) {
    AgentAnimState.IDLE -> AgentPillMode.COLLAPSED
    AgentAnimState.THINKING -> AgentPillMode.THINKING
    AgentAnimState.STREAMING, AgentAnimState.WORKING -> AgentPillMode.ACTIVE
}
```

- [ ] **Step 1.4: 跑测试确认通过**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.AgentPillStateMapperTest"
```

Expected: PASS（4 个 test）。

- [ ] **Step 1.5: Commit**

```bash
git add \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPill.kt \
  ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/AgentPillStateMapperTest.kt
git commit -m "$(cat <<'EOF'
feat(android): AgentPillMode 枚举与 AgentAnimState 映射

4→3 档合并：STREAMING 和 WORKING 共用 ACTIVE，为后续
AgentPill 胶囊动画奠定状态层。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `Keyframe` 与 `interpolateTrajectory`（光团轨迹插值）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt`（先只放 Keyframe / interpolate / easing / lerp 辅助，动画 composable 后续 Task 填入）
- Test: `app/src/test/java/com/sebastian/android/ui/chat/OrbTrajectoryTest.kt`

- [ ] **Step 2.1: 写失败的插值测试**

`app/src/test/java/com/sebastian/android/ui/chat/OrbTrajectoryTest.kt`：

```kotlin
package com.sebastian.android.ui.chat

import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 光团轨迹关键帧插值（纯数学，不依赖 Compose runtime）。
 * easeInOutQuad 作为唯一 easing。
 */
class OrbTrajectoryTest {

    private val trajectory = listOf(
        Keyframe(0.0f, DpOffset(0.dp, 0.dp),      alpha = 0.6f),
        Keyframe(0.5f, DpOffset(8.dp, (-4).dp),   alpha = 1.0f),
        Keyframe(1.0f, DpOffset(0.dp, 0.dp),      alpha = 0.6f),
    )

    @Test
    fun `at t=0 returns first keyframe`() {
        val v = interpolateTrajectory(0f, trajectory)
        assertEquals(0f, v.offset.x.value, 0.001f)
        assertEquals(0f, v.offset.y.value, 0.001f)
        assertEquals(0.6f, v.alpha, 0.001f)
    }

    @Test
    fun `at t=1 returns last keyframe`() {
        val v = interpolateTrajectory(1f, trajectory)
        assertEquals(0f, v.offset.x.value, 0.001f)
        assertEquals(0.6f, v.alpha, 0.001f)
    }

    @Test
    fun `at t=0_5 returns middle keyframe exactly`() {
        val v = interpolateTrajectory(0.5f, trajectory)
        assertEquals(8f, v.offset.x.value, 0.001f)
        assertEquals(-4f, v.offset.y.value, 0.001f)
        assertEquals(1.0f, v.alpha, 0.001f)
    }

    @Test
    fun `at t=0_25 interpolates with easeInOutQuad between first and middle`() {
        // raw=(0.25-0)/(0.5-0)=0.5，easeInOutQuad(0.5) = 0.5
        val v = interpolateTrajectory(0.25f, trajectory)
        assertEquals(4f, v.offset.x.value, 0.001f)    // lerp(0, 8, 0.5)
        assertEquals(-2f, v.offset.y.value, 0.001f)   // lerp(0, -4, 0.5)
        assertEquals(0.8f, v.alpha, 0.001f)           // lerp(0.6, 1.0, 0.5)
    }

    @Test
    fun `time out of range clamps to boundaries`() {
        assertEquals(0.6f, interpolateTrajectory(-0.5f, trajectory).alpha, 0.001f)
        assertEquals(0.6f, interpolateTrajectory(1.5f, trajectory).alpha, 0.001f)
    }
}
```

- [ ] **Step 2.2: 跑测试确认失败**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.OrbTrajectoryTest"
```

Expected: FAIL，`Keyframe` / `interpolateTrajectory` unresolved。

- [ ] **Step 2.3: 写最小实现**

`app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt`：

```kotlin
// com/sebastian/android/ui/chat/AgentPillAnimations.kt
package com.sebastian.android.ui.chat

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.DpOffset

/**
 * 光团运行轨迹的一个关键帧。t 范围 0f..1f，归一化时间。
 */
data class Keyframe(
    val t: Float,
    val offset: DpOffset,
    val alpha: Float,
)

data class KeyframeValue(
    val offset: DpOffset,
    val alpha: Float,
)

/**
 * 按归一化时间在关键帧之间做 easeInOutQuad 插值。
 * 时间越界时夹到首/尾关键帧。
 */
fun interpolateTrajectory(time: Float, keyframes: List<Keyframe>): KeyframeValue {
    require(keyframes.isNotEmpty()) { "keyframes must not be empty" }
    val first = keyframes.first()
    val last = keyframes.last()
    if (time <= first.t) return KeyframeValue(first.offset, first.alpha)
    if (time >= last.t) return KeyframeValue(last.offset, last.alpha)
    for (i in 0 until keyframes.size - 1) {
        val a = keyframes[i]
        val b = keyframes[i + 1]
        if (time >= a.t && time <= b.t) {
            val raw = (time - a.t) / (b.t - a.t)
            val eased = easeInOutQuad(raw)
            return KeyframeValue(
                offset = DpOffset(
                    x = lerpDp(a.offset.x, b.offset.x, eased),
                    y = lerpDp(a.offset.y, b.offset.y, eased),
                ),
                alpha = lerpFloat(a.alpha, b.alpha, eased),
            )
        }
    }
    return KeyframeValue(last.offset, last.alpha)
}

internal fun easeInOutQuad(t: Float): Float =
    if (t < 0.5f) 2f * t * t
    else 1f - ((-2f * t + 2f).let { it * it }) / 2f

internal fun lerpDp(a: Dp, b: Dp, t: Float): Dp = a + (b - a) * t
internal fun lerpFloat(a: Float, b: Float, t: Float): Float = a + (b - a) * t
```

- [ ] **Step 2.4: 跑测试确认通过**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.OrbTrajectoryTest"
```

Expected: PASS（5 个 test）。

- [ ] **Step 2.5: Commit**

```bash
git add \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt \
  ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/OrbTrajectoryTest.kt
git commit -m "$(cat <<'EOF'
feat(android): 光团轨迹 Keyframe 数据结构与 easeInOutQuad 插值

纯数学 util，为 OrbsAnimation 的 4 条漂移轨迹提供运行时插值能力。
不引入第三方动画库。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Jarvis 蓝 Color Token

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/ui/theme/Color.kt`

- [ ] **Step 3.1: 追加颜色常量**

打开 `app/src/main/java/com/sebastian/android/ui/theme/Color.kt`，在末尾追加：

```kotlin

// ── Agent 活动指示器（Jarvis 蓝）────────────────────────────────
// 不进入 colorScheme，由 AgentPill 直接引用（参考 SwitchChecked 的 pattern）
val AgentAccentLight = Color(0xFF6FC3FF)
val AgentAccentDark = Color(0xFF9FD6FF)
```

（接续已有 `SwitchCheckedDark = Color(0xFF30D158)` 之后，保持空行分段。）

- [ ] **Step 3.2: 编译检查**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL。

- [ ] **Step 3.3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/Color.kt
git commit -m "$(cat <<'EOF'
feat(android): 新增 AgentAccent 主题色 token

Jarvis 蓝 #6FC3FF / #9FD6FF，不进 colorScheme，
供 AgentPill 活动指示器独立引用。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `OrbsAnimation` — 4 光团漂移动画

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt`

在 Task 2 创建的文件末尾追加 4 条轨迹常量 + `OrbsAnimation` composable。

- [ ] **Step 4.1: 追加轨迹常量与 InfiniteTransition 辅助**

在 `AgentPillAnimations.kt` 末尾追加：

```kotlin

// ═══════════════════════════════════════════════════════════════
// OrbsAnimation · THINKING · 4 光团漂移
// ═══════════════════════════════════════════════════════════════

import androidx.compose.animation.core.InfiniteTransition
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp

// 4 条独立轨迹，数值等价于 spec 视觉稿 v5 的 CSS keyframes
private val TRAJECTORY_1 = listOf(
    Keyframe(0.00f, DpOffset(0.dp, 0.dp),    alpha = 0.6f),
    Keyframe(0.50f, DpOffset(8.dp, (-4).dp), alpha = 1.0f),
    Keyframe(1.00f, DpOffset(0.dp, 0.dp),    alpha = 0.6f),
)
private val TRAJECTORY_2 = listOf(
    Keyframe(0.00f, DpOffset(0.dp, 0.dp),     alpha = 0.9f),
    Keyframe(0.40f, DpOffset((-4).dp, 5.dp),  alpha = 0.5f),
    Keyframe(0.75f, DpOffset(4.dp, (-3).dp),  alpha = 1.0f),
    Keyframe(1.00f, DpOffset(0.dp, 0.dp),     alpha = 0.9f),
)
private val TRAJECTORY_3 = listOf(
    Keyframe(0.00f, DpOffset(0.dp, 0.dp),        alpha = 0.4f),
    Keyframe(0.50f, DpOffset((-10).dp, (-6).dp), alpha = 1.0f),
    Keyframe(1.00f, DpOffset(0.dp, 0.dp),        alpha = 0.4f),
)
private val TRAJECTORY_4 = listOf(
    Keyframe(0.00f, DpOffset(0.dp, 0.dp),       alpha = 1.0f),
    Keyframe(0.45f, DpOffset((-12).dp, 4.dp),   alpha = 0.5f),
    Keyframe(1.00f, DpOffset(0.dp, 0.dp),       alpha = 1.0f),
)

// 4 颗光团圆心基准（容器 32dp × 22dp；原始 top/left 加半径 3.5dp 得圆心）
private val ORB_BASE_1 = DpOffset(3.5.dp, 11.5.dp)
private val ORB_BASE_2 = DpOffset(13.5.dp, 7.5.dp)
private val ORB_BASE_3 = DpOffset(21.5.dp, 15.5.dp)
private val ORB_BASE_4 = DpOffset(25.5.dp, 9.5.dp)

private const val ORB_RADIUS_DP = 3.5f
private const val ORBS_CONTAINER_W_DP = 32f
private const val ORBS_CONTAINER_H_DP = 22f

@Composable
private fun InfiniteTransition.normalizedTime(periodMs: Int, label: String): State<Float> =
    animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(periodMs, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = label,
    )

/**
 * 4 光团异步漂移 + 各自 alpha 起伏，模拟"思绪打转"。
 * 周期：3.8s / 4.4s / 5.0s / 4.1s（互质，避免同步）。
 */
@Composable
fun OrbsAnimation(
    accent: Color,
    glowAlphaScale: Float = 1f,
    modifier: Modifier = Modifier,
) {
    val t = rememberInfiniteTransition(label = "orbs")
    val p1 by t.normalizedTime(3800, "orb1")
    val p2 by t.normalizedTime(4400, "orb2")
    val p3 by t.normalizedTime(5000, "orb3")
    val p4 by t.normalizedTime(4100, "orb4")

    Canvas(
        modifier
            .size(ORBS_CONTAINER_W_DP.dp, ORBS_CONTAINER_H_DP.dp)
            .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen },
    ) {
        drawOrb(p1, ORB_BASE_1, TRAJECTORY_1, accent, glowAlphaScale)
        drawOrb(p2, ORB_BASE_2, TRAJECTORY_2, accent, glowAlphaScale)
        drawOrb(p3, ORB_BASE_3, TRAJECTORY_3, accent, glowAlphaScale)
        drawOrb(p4, ORB_BASE_4, TRAJECTORY_4, accent, glowAlphaScale)
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawOrb(
    progress: Float,
    basePos: DpOffset,
    trajectory: List<Keyframe>,
    accent: Color,
    glowAlphaScale: Float,
) {
    val v = interpolateTrajectory(progress, trajectory)
    val cx = (basePos.x + v.offset.x).toPx()
    val cy = (basePos.y + v.offset.y).toPx()
    val center = Offset(cx, cy)
    val coreAlpha = v.alpha
    val glowAlpha = v.alpha * glowAlphaScale
    val rPx = ORB_RADIUS_DP.dp.toPx()

    // 外辉
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(accent.copy(alpha = glowAlpha * 0.25f), Color.Transparent),
            center = center,
            radius = rPx * 2.8f,
        ),
        radius = rPx * 2.8f,
        center = center,
        blendMode = BlendMode.Plus,
    )
    // 中辉
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(accent.copy(alpha = glowAlpha * 0.55f), Color.Transparent),
            center = center,
            radius = rPx * 1.6f,
        ),
        radius = rPx * 1.6f,
        center = center,
        blendMode = BlendMode.Plus,
    )
    // 核心
    drawCircle(
        color = accent.copy(alpha = coreAlpha),
        radius = rPx,
        center = center,
        blendMode = BlendMode.Plus,
    )
}
```

**注意**：`import` 必须移到文件顶部 package 声明之后、与 Task 2 的已有 imports 合并。不要放在文件中段。整理好的完整 imports 区块应包含：

```kotlin
import androidx.compose.animation.core.InfiniteTransition
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
```

`drawOrb` 用全限定名 `androidx.compose.ui.graphics.drawscope.DrawScope`，或你也可以在 imports 顶部加 `import androidx.compose.ui.graphics.drawscope.DrawScope` 并把 receiver 改成 `DrawScope`。推荐后者。

- [ ] **Step 4.2: 编译检查**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL。

- [ ] **Step 4.3: 已有单测仍然通过**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest
```

Expected: ALL PASS（含 Task 1 / Task 2 的测试）。

- [ ] **Step 4.4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt
git commit -m "$(cat <<'EOF'
feat(android): OrbsAnimation 4 光团漂移绘制

rememberInfiniteTransition 驱动 4 条互质周期轨迹，Canvas 三层
RadialGradient 叠加模拟 Siri 式柔光色团，BlendMode.Plus 在重叠处加亮。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `HudAnimation` — Jarvis 同心 HUD

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt`

继续在同一文件末尾追加 HUD 实现。

- [ ] **Step 5.1: 追加 `HudAnimation` 与 `drawDashedArcHalo`**

在 `AgentPillAnimations.kt` 末尾追加：

```kotlin

// ═══════════════════════════════════════════════════════════════
// HudAnimation · ACTIVE · Jarvis 同心 HUD
// ═══════════════════════════════════════════════════════════════

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate

private const val HUD_CONTAINER_W_DP = 28f
private const val HUD_CONTAINER_H_DP = 20f

/**
 * 双圈断弧反向旋转 + 径向 ping + 核心脉冲，整体"钢铁侠 HUD"意象。
 * 外圈逆时针 1.4s，内圈顺时针 0.9s；ping 1.4s 扩散；核心 0.8s 脉冲。
 */
@Composable
fun HudAnimation(
    accent: Color,
    glowAlphaScale: Float = 1f,
    modifier: Modifier = Modifier,
) {
    val t = rememberInfiniteTransition(label = "hud")
    val outerRot by t.animateFloat(
        initialValue = 0f, targetValue = -360f,
        animationSpec = infiniteRepeatable(tween(1400, easing = LinearEasing)),
        label = "outerRot",
    )
    val innerRot by t.animateFloat(
        initialValue = 0f, targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(900, easing = LinearEasing)),
        label = "innerRot",
    )
    val pingPhase by t.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(1400, easing = CubicBezierEasing(0.2f, 0.8f, 0.2f, 1f)),
        ),
        label = "ping",
    )
    val corePhase by t.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(800),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "core",
    )

    Canvas(
        modifier
            .size(HUD_CONTAINER_W_DP.dp, HUD_CONTAINER_H_DP.dp)
            .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen },
    ) {
        val center = Offset(size.width / 2f, size.height / 2f)

        // Ping：半径 1..10dp，alpha 1..0
        val pingRadius = lerpFloat(1.dp.toPx(), 10.dp.toPx(), pingPhase)
        val pingAlpha = (1f - pingPhase) * glowAlphaScale
        drawCircle(
            color = accent.copy(alpha = pingAlpha * 0.8f),
            radius = pingRadius,
            center = center,
            style = Stroke(width = 1.2.dp.toPx()),
        )

        // 外圈断弧：r=8dp，stroke 1.5dp，dash 22:28
        drawDashedArcHalo(
            center, radius = 8.dp.toPx(), strokeWidth = 1.5.dp.toPx(),
            dashOn = 22f, dashOff = 28f, rotationDeg = outerRot,
            accent = accent, glowAlphaScale = glowAlphaScale,
        )

        // 内圈断弧：r=4.5dp，stroke 1.2dp，dash 8:18
        drawDashedArcHalo(
            center, radius = 4.5.dp.toPx(), strokeWidth = 1.2.dp.toPx(),
            dashOn = 8f, dashOff = 18f, rotationDeg = innerRot,
            accent = accent, glowAlphaScale = glowAlphaScale,
        )

        // 核心：半径 1.8dp，scale 0.8..1.15，alpha 0.5..1.0
        val coreScale = 0.8f + corePhase * 0.35f
        val coreAlpha = 0.5f + corePhase * 0.5f
        drawCircle(
            color = accent.copy(alpha = coreAlpha),
            radius = 1.8.dp.toPx() * coreScale,
            center = center,
        )
    }
}

private fun DrawScope.drawDashedArcHalo(
    center: Offset,
    radius: Float,
    strokeWidth: Float,
    dashOn: Float,
    dashOff: Float,
    rotationDeg: Float,
    accent: Color,
    glowAlphaScale: Float,
) {
    rotate(rotationDeg, center) {
        // Halo（加粗 2 倍，半透明，模拟 drop-shadow）
        drawCircle(
            color = accent.copy(alpha = 0.5f * glowAlphaScale),
            radius = radius,
            center = center,
            style = Stroke(
                width = strokeWidth * 2f,
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(dashOn, dashOff)),
                cap = StrokeCap.Round,
            ),
        )
        // Main
        drawCircle(
            color = accent,
            radius = radius,
            center = center,
            style = Stroke(
                width = strokeWidth,
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(dashOn, dashOff)),
                cap = StrokeCap.Round,
            ),
        )
    }
}
```

**别忘了整合 imports 到文件顶部**。完整新增 import：

```kotlin
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
```

（如果 Task 4 的 `drawOrb` 当时使用了全限定名 `androidx.compose.ui.graphics.drawscope.DrawScope`，现在可以改成 `DrawScope` 接收者，并引入 import。）

- [ ] **Step 5.2: 编译检查**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL。

- [ ] **Step 5.3: 已有单测仍然通过**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest
```

Expected: ALL PASS。

- [ ] **Step 5.4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt
git commit -m "$(cat <<'EOF'
feat(android): HudAnimation Jarvis 同心 HUD 绘制

双圈带缺口断弧（PathEffect dash）反向旋转 + 径向 ping 扩散 +
核心脉冲，模拟钢铁侠 HUD。每根描边加 2× 宽度半透明 halo 做辉光。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `AgentPill` Composable（壳 + 展开 + 防抖 + 语义）

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/ui/chat/AgentPill.kt`

Task 1 创建的文件已经有 enum + mapper。现在追加 composable。

- [ ] **Step 6.1: 追加 `AgentPill` composable**

在 `AgentPill.kt` 末尾追加：

```kotlin

// ═══════════════════════════════════════════════════════════════
// AgentPill 胶囊壳
// ═══════════════════════════════════════════════════════════════

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.sebastian.android.ui.common.glass.GlassState
import com.sebastian.android.ui.common.glass.GlassSurface
import com.sebastian.android.ui.theme.AgentAccentDark
import com.sebastian.android.ui.theme.AgentAccentLight
import com.sebastian.android.viewmodel.AgentAnimState
import kotlinx.coroutines.delay

/**
 * ChatScreen 顶部 agent 名称胶囊。
 *
 * 根据 [agentAnimState] 切换三档显示：
 * - COLLAPSED（IDLE）：只显 Text
 * - THINKING：尾部 4 光团漂移
 * - ACTIVE（STREAMING / WORKING）：尾部 Jarvis 同心 HUD
 *
 * 展开用 spring animateContentSize，THINKING↔ACTIVE 用 AnimatedContent
 * crossfade，额外加 80ms 驻留防抖避免瞬时状态闪烁。
 */
@Composable
fun AgentPill(
    agentName: String?,
    agentAnimState: AgentAnimState,
    glassState: GlassState,
    modifier: Modifier = Modifier,
) {
    val displayName = agentName ?: "Sebastian"
    val isDark = isSystemInDarkTheme()
    val accent = if (isDark) AgentAccentDark else AgentAccentLight
    val glowScale = if (isDark) 1f else 0.7f

    val targetMode = agentAnimState.toPillMode()
    val stableMode by produceState(
        initialValue = AgentPillMode.COLLAPSED,
        key1 = targetMode,
    ) {
        delay(80L)
        value = targetMode
    }

    val stateLabel = when (stableMode) {
        AgentPillMode.COLLAPSED -> null
        AgentPillMode.THINKING -> "正在思考"
        AgentPillMode.ACTIVE -> "正在响应"
    }

    GlassSurface(
        state = glassState,
        shape = CircleShape,
        shadowCornerRadius = 100.dp,
        modifier = modifier.semantics {
            contentDescription = displayName
            if (stateLabel != null) stateDescription = stateLabel
        },
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .animateContentSize(
                    animationSpec = spring(dampingRatio = 0.7f, stiffness = 400f),
                )
                .padding(horizontal = 16.dp, vertical = 10.dp),
        ) {
            Text(
                text = displayName,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            AnimatedVisibility(
                visible = stableMode != AgentPillMode.COLLAPSED,
                enter = expandHorizontally() + fadeIn(tween(200)),
                exit = shrinkHorizontally() + fadeOut(tween(200)),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Spacer(Modifier.width(8.dp))
                    AnimatedContent(
                        targetState = stableMode,
                        transitionSpec = {
                            fadeIn(tween(200)) togetherWith fadeOut(tween(200))
                        },
                        label = "agentPillTail",
                    ) { mode ->
                        when (mode) {
                            AgentPillMode.THINKING -> OrbsAnimation(
                                accent = accent,
                                glowAlphaScale = glowScale,
                            )
                            AgentPillMode.ACTIVE -> HudAnimation(
                                accent = accent,
                                glowAlphaScale = glowScale,
                            )
                            AgentPillMode.COLLAPSED -> Spacer(Modifier.size(0.dp))
                        }
                    }
                }
            }
        }
    }
}
```

**同样整合 imports 到文件顶部**（与 Task 1 的 `AgentAnimState` import 合并）。

- [ ] **Step 6.2: 编译检查**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL。

- [ ] **Step 6.3: 已有单测仍然通过**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest
```

Expected: ALL PASS。

- [ ] **Step 6.4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPill.kt
git commit -m "$(cat <<'EOF'
feat(android): AgentPill 胶囊壳 + 展开 / 收起 / 防抖

GlassSurface(CircleShape) 内包 Row{Text + AnimatedVisibility{Tail}}，
Row.animateContentSize(spring) 驱动灵动岛式展开；produceState + 80ms delay
做瞬时状态防抖；AnimatedContent 在 THINKING / ACTIVE 之间 crossfade。
浅色主题 glow alpha × 0.7 避免过曝。semantics 提供 TalkBack 状态播报。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 把 `AgentPill` 接入 `ChatScreen`

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

- [ ] **Step 7.1: 替换胶囊 Box 内部**

打开 `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`。找到第 246-264 行附近（`// 悬浮顶部栏` 之后、中间 title 那一块）。原代码：

```kotlin
                    Box(
                        contentAlignment = Alignment.CenterStart,
                        modifier = Modifier
                            .weight(1f)
                            .padding(horizontal = 8.dp),
                    ) {
                        GlassSurface(
                            state = glassState,
                            shape = CircleShape,
                            shadowCornerRadius = 100.dp,
                        ) {
                            Text(
                                text = agentName ?: "Sebastian",
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.onSurface,
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                            )
                        }
                    }
```

替换为：

```kotlin
                    Box(
                        contentAlignment = Alignment.CenterStart,
                        modifier = Modifier
                            .weight(1f)
                            .padding(horizontal = 8.dp),
                    ) {
                        AgentPill(
                            agentName = agentName,
                            agentAnimState = chatState.agentAnimState,
                            glassState = glassState,
                        )
                    }
```

外层 Box 不动（保留 weight + padding + CenterStart，让胶囊从左侧按内容宽度 spring 展开）。

- [ ] **Step 7.2: 清理可能不再用到的 import**

`ChatScreen.kt` 顶部 imports 里，若 `CircleShape` / `MaterialTheme` / `Text` 在文件别处仍有使用，保留；否则删除。先跑编译靠编译器提示。

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL（如果有 "unused import" 警告，把对应 import 删掉再编译一次）。

- [ ] **Step 7.3: 全仓单测通过**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest
```

Expected: ALL PASS。

- [ ] **Step 7.4: 更新 ChatScreen 模块 README 的修改导航表**

打开 `app/src/main/java/com/sebastian/android/ui/chat/README.md`。找到"修改导航"表（或类似表格），在合适位置追加一行：

```markdown
| 改顶部 agent 胶囊 / 活动指示器动画 | `AgentPill.kt` + `AgentPillAnimations.kt` |
```

如果表没有或格式不同，按现有风格对齐补一条。

- [ ] **Step 7.5: Commit**

```bash
git add \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md
git commit -m "$(cat <<'EOF'
feat(android): ChatScreen 顶部胶囊接入 AgentPill 动画

替换 ChatScreen.kt 原静态 GlassSurface + Text 为 AgentPill 组合
组件，消费 chatState.agentAnimState 驱动展开收起。README 导航
表同步补条目。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 终局验证 + push

- [ ] **Step 8.1: 一次完整 lint + build + test**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin :app:testDebugUnitTest
```

Expected: BUILD SUCCESSFUL，全部 test PASS。

- [ ] **Step 8.2: 确认 git 状态干净（只剩无关的其它工作区改动）**

```bash
git status
```

Expected：本次计划相关文件都已 commit，只剩用户原本就在改的 thinking-migration 等无关修改。

- [ ] **Step 8.3: Push 到 dev**

```bash
git push
```

（`dev` 已 track `origin/dev`，无需 `-u`。若被 reject 提示 non-fast-forward，按 CLAUDE.md "提交前准备" rebase 一次：`git fetch origin main && git rebase origin/main && git push --force-with-lease`。）

- [ ] **Step 8.4: 收手，交给用户在模拟器上装包肉眼验收**

按 CLAUDE.md + 用户偏好：Android 改动跑完单测即收手，`./gradlew installDebug` 由用户自己执行。实现人只需告知："后端不需要重启，App 重装即可看到顶部胶囊在思考 / 响应时的动画。"

---

## Self-Review Checklist（实现人完成后自查）

**Spec coverage**：
- [x] 状态映射 4→3 档 → Task 1
- [x] Keyframe 插值 → Task 2
- [x] 颜色 token → Task 3
- [x] OrbsAnimation（4 光团、v5 轨迹、Plus blend）→ Task 4
- [x] HudAnimation（双圈断弧、ping、核心）→ Task 5
- [x] 展开 / 收起 spring animateContentSize → Task 6
- [x] 80ms 防抖 produceState → Task 6
- [x] THINKING ↔ ACTIVE crossfade → Task 6
- [x] 浅色主题 glow × 0.7 → Task 6
- [x] semantics 播报 → Task 6
- [x] 接入 ChatScreen → Task 7
- [x] 单元测试（mapper + trajectory）→ Task 1 / 2
- [x] 生命周期（交给 AnimatedVisibility 停 InfiniteTransition，无需手动暂停）→ spec 已决策，Task 6 实现自然满足

**人工验证项**（emulator install 后走一遍）：
- 收到第一条 Assistant 消息前，胶囊从 "Sebastian" 展开 + 4 光团
- 模型开始吐字，胶囊切到 Jarvis HUD（crossfade 平滑无闪）
- 工具调用中保持 HUD（STREAMING ↔ WORKING 不引起动画重启）
- Turn 结束胶囊 spring 收回
- 新对话按钮点击后胶囊立即收回
- 深色 / 浅色两个主题下观感合理（浅色不过曝、深色不过暗）
- 快速连发两轮 turn：中间态不闪
