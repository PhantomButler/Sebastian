package com.sebastian.android.ui.chat

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.awaitHorizontalTouchSlopOrCancellation
import androidx.compose.foundation.gestures.horizontalDrag
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.roundToInt

enum class SidePane { NONE, LEFT, RIGHT }

/**
 * iOS UIKit 风格 rubberband 衰减：越界距离越大阻力越大，最终趋近于 [dimension]。
 *
 * 公式 f(x, D) = (0.55 * x * D) / (0.55 * x + D)
 * - f(0) = 0
 * - f(x) < x 恒成立（衰减性）
 * - lim x→∞ f(x) = D（渐近线）
 *
 * @param distance 越界距离（>= 0）
 * @param dimension 容量参数（决定渐近线 = dimension）
 */
internal fun rubberband(distance: Float, dimension: Float): Float {
    if (dimension <= 0f) return 0f
    val k = 0.55f
    return (k * distance * dimension) / (k * distance + dimension)
}

/**
 * 三面板共用的 spring 动画：dampingRatio 0.75 + stiffness 380，
 * 收尾带 1 次轻微过冲（Material LowBouncy 风格）。
 */
private val PaneSpringSpec = spring<Float>(dampingRatio = 0.75f, stiffness = 380f)

/**
 * 三面板滑动布局：侧边栏占 [paneFraction] 屏幕宽度，主内容同步推出。
 *
 * 手势策略：
 * - 整个内容区域均可横向拖拽触发侧栏（不限于边缘）
 * - 使用 awaitHorizontalTouchSlopOrCancellation 区分横/纵向手势，纵向滑动自动交给 LazyColumn
 * - 若子组件已消费横向手势（如 Markdown 代码块横向滚动），则本层不介入
 */
@Composable
fun SlidingThreePaneLayout(
    activePane: SidePane,
    onPaneChange: (SidePane) -> Unit,
    leftPane: @Composable () -> Unit,
    mainPane: @Composable () -> Unit,
    rightPane: @Composable () -> Unit,
    paneFraction: Float = 0.75f,
    modifier: Modifier = Modifier,
) {
    BackHandler(enabled = activePane != SidePane.NONE) {
        onPaneChange(SidePane.NONE)
    }

    val scope = rememberCoroutineScope()

    BoxWithConstraints(modifier = modifier.fillMaxSize().clipToBounds()) {
        val totalWidthPx = constraints.maxWidth.toFloat()
        val paneWidthPx = totalWidthPx * paneFraction
        val density = LocalDensity.current

        val offset = remember { Animatable(0f) }

        // Sync external state (button clicks) → animation
        LaunchedEffect(activePane, paneWidthPx) {
            val target = when (activePane) {
                SidePane.NONE -> 0f
                SidePane.LEFT -> paneWidthPx
                SidePane.RIGHT -> -paneWidthPx
            }
            if (offset.value != target) {
                offset.animateTo(target, PaneSpringSpec)
            }
        }

        val paneWidthDp = with(density) { paneWidthPx.toDp() }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .pointerInput(paneWidthPx) {
                    awaitEachGesture {
                        val down = awaitFirstDown(requireUnconsumed = false)

                        val velocityTracker = VelocityTracker()
                        velocityTracker.addPosition(down.uptimeMillis, down.position)

                        // 等待横向滑动超过 touch slop；纵向先到 slop 则返回 null → 交给 LazyColumn
                        // 若子组件（如代码块横向滚动）已消费事件，则不介入
                        var childConsumed = false
                        val drag = awaitHorizontalTouchSlopOrCancellation(down.id) { change, _ ->
                            if (change.isConsumed) {
                                childConsumed = true
                            } else {
                                change.consume()
                            }
                            velocityTracker.addPosition(change.uptimeMillis, change.position)
                        }
                        if (drag == null || childConsumed) return@awaitEachGesture

                        // 确认是横向拖拽，停止正在进行的动画
                        scope.launch { offset.stop() }

                        val maxOver = paneWidthPx * 0.25f
                        horizontalDrag(drag.id) { change ->
                            velocityTracker.addPosition(change.uptimeMillis, change.position)
                            val dragAmount = change.positionChange().x
                            change.consume()
                            val newRaw = offset.value + dragAmount
                            val newOffset = when {
                                newRaw > paneWidthPx ->
                                    paneWidthPx + rubberband(newRaw - paneWidthPx, maxOver)
                                newRaw < -paneWidthPx ->
                                    -paneWidthPx - rubberband(-newRaw - paneWidthPx, maxOver)
                                else -> newRaw
                            }
                            scope.launch { offset.snapTo(newOffset) }
                        }

                        // 松手 → 根据速度 / 位置决定目标锚点
                        val velocity = velocityTracker.calculateVelocity().x
                        val current = offset.value
                        val flingThreshold = 500f
                        val positionThreshold = paneWidthPx * 0.4f

                        val target = when {
                            // 快速向右滑 → 打开左面板 或 回到中间
                            velocity > flingThreshold ->
                                if (current >= 0) paneWidthPx else 0f
                            // 快速向左滑 → 打开右面板 或 回到中间
                            velocity < -flingThreshold ->
                                if (current <= 0) -paneWidthPx else 0f
                            // 慢速拖拽 → 按位置阈值判断
                            current > positionThreshold -> paneWidthPx
                            current < -positionThreshold -> -paneWidthPx
                            else -> 0f
                        }

                        // 先通知外部 state（让 BackHandler 等立刻同步），再启动 spring
                        onPaneChange(
                            when (target) {
                                paneWidthPx -> SidePane.LEFT
                                -paneWidthPx -> SidePane.RIGHT
                                else -> SidePane.NONE
                            }
                        )
                        scope.launch {
                            offset.animateTo(
                                targetValue = target,
                                animationSpec = PaneSpringSpec,
                                initialVelocity = velocity,
                            )
                        }
                    }
                },
        ) {
            // Left pane
            Surface(
                modifier = Modifier
                    .fillMaxHeight()
                    .width(paneWidthDp)
                    .offset { IntOffset((offset.value - paneWidthPx).roundToInt(), 0) },
            ) {
                leftPane()
            }

            // Main content + scrim overlay
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .offset { IntOffset(offset.value.roundToInt(), 0) },
            ) {
                mainPane()

                // Dim scrim: opacity follows drag progress, tappable to close
                val scrimAlpha by remember {
                    derivedStateOf { (abs(offset.value) / paneWidthPx).coerceIn(0f, 1f) * 0.5f }
                }
                if (scrimAlpha > 0f) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(Color.Black.copy(alpha = scrimAlpha))
                            .clickable(
                                interactionSource = remember { MutableInteractionSource() },
                                indication = null,
                            ) { onPaneChange(SidePane.NONE) },
                    )
                }
            }

            // Right pane
            Surface(
                modifier = Modifier
                    .fillMaxHeight()
                    .width(paneWidthDp)
                    .offset { IntOffset((totalWidthPx + offset.value).roundToInt(), 0) },
            ) {
                rightPane()
            }
        }
    }
}
