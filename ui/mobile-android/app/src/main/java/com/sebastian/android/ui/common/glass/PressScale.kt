// com/sebastian/android/ui/common/glass/PressScale.kt
package com.sebastian.android.ui.common.glass

import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale

/**
 * 按压缩放反馈（iOS 式）。
 *
 * 按下时缩放至 [pressedScale]，松开用 spring 弹回 1f。仅影响绘制，不影响布局。
 * 搭配 `Modifier.clickable(interactionSource = ..., indication = null)` 使用。
 *
 * @param interactionSource 与 clickable 共用的交互源
 * @param pressedScale      按下状态的缩放系数，0.94 ≈ 轻按感
 */
@Composable
fun Modifier.pressScale(
    interactionSource: InteractionSource,
    pressedScale: Float = 0.94f,
): Modifier {
    val isPressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (isPressed) pressedScale else 1f,
        animationSpec = spring(stiffness = Spring.StiffnessMediumLow),
        label = "pressScale",
    )
    return this.scale(scale)
}
