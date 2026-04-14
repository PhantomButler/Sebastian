// com/sebastian/android/ui/common/glass/GlassKit.kt
package com.sebastian.android.ui.common.glass

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.kyant.backdrop.backdrops.LayerBackdrop
import com.kyant.backdrop.backdrops.layerBackdrop
import com.kyant.backdrop.backdrops.rememberLayerBackdrop

/**
 * 液态玻璃默认参数。可在调用 [GlassSurface] 时逐项覆盖。
 */
object GlassDefaults {
    /** 背景模糊半径 */
    const val BlurRadius: Float = 20f

    /** 表面半透明叠加层的默认 alpha */
    const val SurfaceAlpha: Float = 0.5f
}

/**
 * 液态玻璃状态。由 [rememberGlassState] 创建，在同一 Box 层级内共享。
 *
 * 使用方式：
 * 1. 用 [contentModifier] 标记被采样的内容层
 * 2. 把此对象传给 [GlassSurface] 等玻璃组件
 */
@Stable
class GlassState internal constructor(
    internal val backdrop: LayerBackdrop,
) {
    /**
     * 应用到玻璃框**背后**的内容层，使该层内容可被玻璃采样与模糊。
     *
     * ```kotlin
     * MessageList(modifier = Modifier.fillMaxSize().then(glassState.contentModifier))
     * ```
     */
    val contentModifier: Modifier = Modifier.layerBackdrop(backdrop)
}

/**
 * 创建 [GlassState]。每个需要玻璃效果的视图层调用一次。
 *
 * @param backgroundColor 采样底图的填充色，通常传 [MaterialTheme.colorScheme.background]
 */
@Composable
fun rememberGlassState(backgroundColor: Color): GlassState {
    val bg = backgroundColor
    val backdrop = rememberLayerBackdrop {
        drawRect(bg)
        drawContent()
    }
    return remember(backdrop) { GlassState(backdrop) }
}
