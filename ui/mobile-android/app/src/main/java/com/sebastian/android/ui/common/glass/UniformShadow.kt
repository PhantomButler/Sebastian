// com/sebastian/android/ui/common/glass/UniformShadow.kt
package com.sebastian.android.ui.common.glass

import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * 均匀投影（四周含顶部）的 Modifier。
 *
 * 用 `Paint.setShadowLayer(dx=0, dy=0)` 自绘，避开 Android 原生 elevation
 * 光源模型只照亮底部的问题；同时不走 Surface.shadowElevation，避免
 * tonalElevation 色彩叠加导致的白块重影。
 *
 * 适合给玻璃面板、悬浮按钮、卡片等需要四周均匀浮起感的控件使用。
 *
 * @param elevation    阴影模糊半径（0 = 不绘制）
 * @param cornerRadius 阴影圆角，需与控件自身 clip 圆角对齐
 * @param color        阴影颜色（含 alpha）
 */
fun Modifier.uniformShadow(
    elevation: Dp,
    cornerRadius: Dp,
    color: Color = Color.Black.copy(alpha = 0.18f),
): Modifier {
    if (elevation <= 0.dp) return this
    val shadowArgb = color.toArgb()
    return this.drawBehind {
        val radiusPx = elevation.toPx()
        val cornerPx = cornerRadius.toPx()
        val paint = android.graphics.Paint().apply {
            isAntiAlias = true
            this.color = android.graphics.Color.TRANSPARENT
            setShadowLayer(radiusPx, 0f, 0f, shadowArgb)
        }
        drawContext.canvas.nativeCanvas.drawRoundRect(
            0f, 0f, size.width, size.height,
            cornerPx, cornerPx, paint,
        )
    }
}
