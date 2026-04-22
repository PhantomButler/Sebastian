package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.DragInteraction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.ui.common.glass.GlassState
import com.sebastian.android.ui.common.glass.GlassSurface
import com.sebastian.android.ui.common.glass.pressScale
import kotlinx.coroutines.launch

/**
 * 消息列表 + 滚动跟随 + 回到底部 FAB。
 *
 * 滚动语义由 UI 层自己维护，不经过 ViewModel（滚动是纯 UI 行为，ViewModel 推不出 atBottom）：
 *
 *   事实层 `atBottom`：从 LazyListState 派生 —— 当前视口是否贴近底部
 *   中介层 `isUserDragging`：从 DragInteraction 派生 —— 手指是否正在拖拽
 *   意图层 `userAway`：是否应暂停自动跟随
 *     规则：
 *       atBottom 为 true → 恒等于 false（回到底部即放弃"离开"意图）
 *       atBottom 为 false 且 isUserDragging → true（用户主动拖离底部）
 *       其余情形保持不变（fling / programmatic 不改变意图）
 *
 *   UI 映射：
 *     FAB 显示 = userAway （意图：用户主动上滑才显示；
 *                           流式中 atBottom 会因 "新内容到达→auto-scroll" 的 50ms 缝隙频繁抖动，
 *                           不能直接绑 !atBottom，否则 FAB 会跟着闪烁）
 *     自动跟随 = !userAway && !isUserDragging （避免打断用户手势）
 *
 * 用户发新消息（messages 末尾出现 USER role）时立即清除 userAway，
 * 保证能立刻跟上 AI 响应。
 */
@Composable
fun MessageList(
    messages: List<Message>,
    flushTick: Long,
    onToggleThinking: (String, String) -> Unit,
    onToggleTool: (String, String) -> Unit,
    onToggleSummary: (String, String) -> Unit,
    glassState: GlassState,
    contentPadding: PaddingValues = PaddingValues(),
    fabBottomOffset: Dp = 16.dp,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()

    // 事实：当前是否已滚到底部。
    // 不能用 visibleItemsInfo.last.index ≥ totalItemsCount-2 —— 流式中最后一条气泡很长，
    // 它的顶部出现在视口里 lastOrNull().index 就会等于 messages.size，导致判定永远为 true。
    // canScrollForward 直接反映「底部还有没有可滚动距离」，是真正的事实层。
    val atBottom by remember {
        derivedStateOf { !listState.canScrollForward }
    }

    // 中介：用户是否正在拖拽（DragInteraction 只对真实触摸触发，scrollToItem 不触发）。
    var isUserDragging by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        listState.interactionSource.interactions.collect { interaction ->
            isUserDragging = when (interaction) {
                is DragInteraction.Start -> true
                is DragInteraction.Stop, is DragInteraction.Cancel -> false
                else -> isUserDragging
            }
        }
    }

    // 意图：是否暂停自动跟随。
    var userAway by remember { mutableStateOf(false) }
    LaunchedEffect(atBottom, isUserDragging) {
        if (atBottom) {
            userAway = false
        } else if (isUserDragging) {
            userAway = true
        }
    }

    // 发送新消息（messages 末尾出现 USER）→ 清除 userAway，保证跟上 AI 响应。
    val lastUserMsgId = messages.lastOrNull()?.takeIf { it.role == MessageRole.USER }?.id
    LaunchedEffect(lastUserMsgId) {
        if (lastUserMsgId != null) userAway = false
    }

    // 自动跟随：内容变化时滚到底部 spacer（index = messages.size + 1）。
    // LazyColumn 会将超过最大滚动量的请求 clamp 到列表末端，
    // 即便最后一条消息在流式增长也能始终显示底部。
    LaunchedEffect(messages.size, messages.lastOrNull()?.blocks?.size, flushTick) {
        if (!userAway && !isUserDragging && messages.isNotEmpty()) {
            listState.scrollToItem(messages.size + 1)
        }
    }

    Box(modifier = modifier) {
        // contentModifier 必须只包住 LazyColumn，不能包住 FAB：
        // FAB 自身是 GlassSurface，如果被 contentModifier 捕获到 backdrop 里，
        // 会采样"包含自己的层" → RenderNode transform 无限递归 → RenderThread 爆栈。
        LazyColumn(
            state = listState,
            contentPadding = contentPadding,
            modifier = Modifier
                .fillMaxSize()
                .then(glassState.contentModifier),
        ) {
            item { Spacer(Modifier.height(16.dp)) }
            items(messages, key = { it.id }) { message ->
                MessageBubble(
                    message = message,
                    onToggleThinking = onToggleThinking,
                    onToggleTool = onToggleTool,
                    onToggleSummary = onToggleSummary,
                    modifier = Modifier.padding(vertical = 4.dp),
                )
            }
            item { Spacer(Modifier.height(8.dp)) }
        }

        // FAB：用户主动离开底部时显示；居中悬浮在输入框上方；
        // 与顶部按钮统一用 GlassSurface 玻璃材质；原位置淡入淡出（不走默认滑动动画）。
        val fabInteraction = remember { MutableInteractionSource() }
        AnimatedVisibility(
            visible = userAway,
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = fabBottomOffset),
        ) {
            GlassSurface(
                state = glassState,
                shape = CircleShape,
                shadowCornerRadius = 22.dp,
                modifier = Modifier
                    .size(44.dp)
                    .pressScale(fabInteraction),
            ) {
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier
                        .fillMaxSize()
                        .clickable(
                            interactionSource = fabInteraction,
                            indication = null,
                        ) {
                            userAway = false
                            scope.launch {
                                listState.animateScrollToItem(index = messages.size + 1)
                            }
                        },
                ) {
                    Icon(
                        imageVector = Icons.Default.KeyboardArrowDown,
                        contentDescription = "回到底部",
                        tint = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}
