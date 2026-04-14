// com/sebastian/android/ui/common/glass/GlassButton.kt
package com.sebastian.android.ui.common.glass

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * 圆形玻璃按钮的色调。
 *
 * - [Neutral]：中性灰色，用于禁用或次要状态
 * - [Primary]：主题色，用于激活或主要操作
 */
enum class GlassButtonTint { Neutral, Primary }

/**
 * 圆形玻璃风格按钮。
 *
 * 使用半透明背景 + 细描边实现视觉玻璃感，适合放置在 [GlassSurface] 内部。
 * **不**需要 [GlassState]，不做模糊采样——放在玻璃容器内时，
 * 容器已提供模糊背景，按钮只需视觉上与之呼应即可。
 *
 * @param onClick       点击回调
 * @param tint          色调：[GlassButtonTint.Neutral] 或 [GlassButtonTint.Primary]
 * @param size          按钮直径，默认 44dp
 * @param enabled       是否可交互
 * @param onLongClick   长按回调（可选）
 * @param content       按钮内容（通常是 Icon）
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun GlassCircleButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tint: GlassButtonTint = GlassButtonTint.Neutral,
    size: Dp = 44.dp,
    enabled: Boolean = true,
    onLongClick: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    val backgroundColor = when (tint) {
        GlassButtonTint.Neutral -> MaterialTheme.colorScheme.onSurface.copy(
            alpha = if (enabled) 0.10f else 0.05f,
        )
        GlassButtonTint.Primary -> MaterialTheme.colorScheme.primary.copy(
            alpha = if (enabled) 0.85f else 0.4f,
        )
    }
    val borderColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f)

    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .background(backgroundColor)
            .border(width = 0.5.dp, color = borderColor, shape = CircleShape)
            .combinedClickable(
                enabled = enabled,
                onClick = onClick,
                onLongClick = onLongClick,
            ),
    ) {
        content()
    }
}
