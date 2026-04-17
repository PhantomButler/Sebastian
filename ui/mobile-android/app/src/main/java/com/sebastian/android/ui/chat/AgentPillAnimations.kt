package com.sebastian.android.ui.chat

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.InfiniteTransition
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import com.sebastian.android.ui.theme.AgentAccentDark
import com.sebastian.android.ui.theme.AgentAccentLight
import com.sebastian.android.ui.theme.AgentRainbowCyanDark
import com.sebastian.android.ui.theme.AgentRainbowCyanLight
import com.sebastian.android.ui.theme.AgentRainbowPurpleDark
import com.sebastian.android.ui.theme.AgentRainbowPurpleLight

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

// ═══════════════════════════════════════════════════════════════
// OrbsAnimation · THINKING · 4 光团漂移
// ═══════════════════════════════════════════════════════════════

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
            repeatMode = RepeatMode.Restart, // must be Restart: 0 → 1 normalized time wraps each cycle
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

private fun DrawScope.drawOrb(
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

// ═══════════════════════════════════════════════════════════════
// HudAnimation · ACTIVE · Jarvis 同心 HUD
// ═══════════════════════════════════════════════════════════════

private const val HUD_CONTAINER_W_DP = 28f
private const val HUD_CONTAINER_H_DP = 20f

/**
 * 双圈带缺口断弧（PathEffect dash）反向旋转 + 径向 ping 扩散 +
 * 核心脉冲，模拟钢铁侠 HUD。
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
        animationSpec = infiniteRepeatable(
            tween(1400, easing = LinearEasing),
            repeatMode = RepeatMode.Restart, // must be Restart: 0 → -360 wraps seamlessly
        ),
        label = "outerRot",
    )
    val innerRot by t.animateFloat(
        initialValue = 0f, targetValue = 360f,
        animationSpec = infiniteRepeatable(
            tween(900, easing = LinearEasing),
            repeatMode = RepeatMode.Restart, // must be Restart: 0 → 360 wraps seamlessly
        ),
        label = "innerRot",
    )
    val pingPhase by t.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(1400, easing = CubicBezierEasing(0.2f, 0.8f, 0.2f, 1f)),
            repeatMode = RepeatMode.Restart, // must be Restart: ping snaps back to radius 1dp each cycle
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

    // Hoist PathEffect allocations out of the draw callback to avoid per-frame GC pressure
    val outerEffect = remember { PathEffect.dashPathEffect(floatArrayOf(22f, 28f)) }
    val innerEffect = remember { PathEffect.dashPathEffect(floatArrayOf(8f, 18f)) }

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
            pathEffect = outerEffect, rotationDeg = outerRot,
            accent = accent, glowAlphaScale = glowAlphaScale,
        )

        // 内圈断弧：r=4.5dp，stroke 1.2dp，dash 8:18
        drawDashedArcHalo(
            center, radius = 4.5.dp.toPx(), strokeWidth = 1.2.dp.toPx(),
            pathEffect = innerEffect, rotationDeg = innerRot,
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
    pathEffect: PathEffect,
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
                pathEffect = pathEffect,
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
                pathEffect = pathEffect,
                cap = StrokeCap.Round,
            ),
        )
    }
}

// ═══════════════════════════════════════════════════════════════
// BreathingHalo · PENDING · 彩虹渐变旋转光环 + 呼吸 alpha
// ═══════════════════════════════════════════════════════════════

private const val BREATHING_CONTAINER_DP = 24

/**
 * PENDING state halo: rotating rainbow gradient ring + alpha breathing.
 * - Three-color sweep (blue → purple → cyan → blue), rotates 360° in 2.4s
 * - Alpha breathes 0.35 ↔ 0.75 in 1.6s
 * - Same size as AgentPill pill area — no radius increase
 */
@Composable
fun BreathingHalo(
    modifier: Modifier = Modifier,
    glowAlphaScale: Float = 1f,
) {
    val isDark = isSystemInDarkTheme()
    val primary = if (isDark) AgentAccentDark else AgentAccentLight
    val purple = if (isDark) AgentRainbowPurpleDark else AgentRainbowPurpleLight
    val cyan = if (isDark) AgentRainbowCyanDark else AgentRainbowCyanLight

    val infinite = rememberInfiniteTransition(label = "breathing_halo")
    val rotation by infinite.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2400, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "rotation",
    )
    val alpha by infinite.animateFloat(
        initialValue = 0.35f,
        targetValue = 0.75f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "alpha",
    )

    Canvas(modifier = modifier.size(BREATHING_CONTAINER_DP.dp)) {
        val brush = Brush.sweepGradient(
            listOf(primary, purple, cyan, primary),
        )
        rotate(rotation) {
            drawCircle(
                brush = brush,
                radius = size.minDimension / 2f,
                alpha = alpha * glowAlphaScale,
                style = Stroke(width = 4.dp.toPx()),
            )
        }
    }
}
