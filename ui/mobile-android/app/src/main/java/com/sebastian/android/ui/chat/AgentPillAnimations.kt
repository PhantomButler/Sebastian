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
