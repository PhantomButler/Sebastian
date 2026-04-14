// com/sebastian/android/ui/common/glass/GlassSurface.kt
package com.sebastian.android.ui.common.glass

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.dp
import com.kyant.backdrop.drawBackdrop
import com.kyant.backdrop.effects.blur
import com.kyant.backdrop.effects.vibrancy

/**
 * 带背景模糊采样的液态玻璃容器。
 *
 * 适合大面积玻璃面板（输入框、底部栏、Sheet 等）。
 * 内部封装了 backdrop 库的 `clip → drawBackdrop` 模式，调用方无需了解库 API。
 *
 * **前提**：父容器中必须有 composable 已应用 [GlassState.contentModifier]，
 * 否则采样内容为空，玻璃只显示纯色叠层。
 *
 * @param state         由 [rememberGlassState] 创建的玻璃状态
 * @param shape         玻璃形状，同时用于内容裁剪与模糊边界
 * @param blurRadius    背景模糊半径，值越大越虚化
 * @param surfaceAlpha  表面叠加颜色的透明度（0 = 完全透明，1 = 不透明）
 */
@Composable
fun GlassSurface(
    state: GlassState,
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(24.dp),
    blurRadius: Float = GlassDefaults.BlurRadius,
    surfaceAlpha: Float = GlassDefaults.SurfaceAlpha,
    content: @Composable () -> Unit,
) {
    val surfaceColor = MaterialTheme.colorScheme.surface
    Surface(
        shape = shape,
        color = Color.Transparent,
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
        modifier = modifier
            .clip(shape)
            .drawBackdrop(
                backdrop = state.backdrop,
                shape = { shape },
                effects = {
                    vibrancy()
                    blur(blurRadius)
                },
                shadow = null,
                onDrawSurface = { drawRect(surfaceColor.copy(alpha = surfaceAlpha)) },
            ),
        content = { content() },
    )
}
