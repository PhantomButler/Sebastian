package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.interaction.DragInteraction
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Icon
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Message
import com.sebastian.android.viewmodel.ScrollFollowState
import kotlinx.coroutines.launch

@Composable
fun MessageList(
    messages: List<Message>,
    scrollFollowState: ScrollFollowState,
    flushTick: Long,
    onUserScrolled: () -> Unit,
    onScrolledNearBottom: () -> Unit,
    onScrolledToBottom: () -> Unit,
    onScrollToBottom: () -> Unit,
    onToggleThinking: (String) -> Unit,
    onToggleTool: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()

    val isNearBottom by remember {
        derivedStateOf {
            val info = listState.layoutInfo
            val lastVisible = info.visibleItemsInfo.lastOrNull() ?: return@derivedStateOf true
            lastVisible.index >= info.totalItemsCount - 2
        }
    }

    val showFab by remember {
        derivedStateOf { scrollFollowState == ScrollFollowState.DETACHED }
    }

    // Use DragInteraction.Start to detect ONLY real user touch drags.
    // Unlike isScrollInProgress, this does NOT fire for programmatic scrollToItem() calls.
    LaunchedEffect(Unit) {
        listState.interactionSource.interactions.collect { interaction ->
            if (interaction is DragInteraction.Start &&
                scrollFollowState == ScrollFollowState.FOLLOWING
            ) {
                onUserScrolled()
            }
        }
    }

    // Near-bottom detection for restoring FOLLOWING
    LaunchedEffect(isNearBottom) {
        if (isNearBottom) {
            onScrolledToBottom()
        } else if (scrollFollowState == ScrollFollowState.NEAR_BOTTOM) {
            onScrolledNearBottom()
        }
    }

    // Auto-scroll when FOLLOWING: triggered by message count, block count, or delta flush
    LaunchedEffect(messages.size, messages.lastOrNull()?.blocks?.size, flushTick) {
        if (scrollFollowState == ScrollFollowState.FOLLOWING && messages.isNotEmpty()) {
            listState.scrollToItem(messages.size - 1)
        }
    }

    Box(modifier = modifier) {
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize(),
        ) {
            item { Spacer(Modifier.height(16.dp)) }
            items(messages, key = { it.id }) { message ->
                MessageBubble(
                    message = message,
                    onToggleThinking = onToggleThinking,
                    onToggleTool = onToggleTool,
                    modifier = Modifier.padding(vertical = 4.dp),
                )
            }
            item { Spacer(Modifier.height(8.dp)) }
        }

        AnimatedVisibility(
            visible = showFab,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(16.dp),
        ) {
            SmallFloatingActionButton(
                onClick = {
                    scope.launch {
                        listState.animateScrollToItem(
                            index = (messages.size - 1).coerceAtLeast(0)
                        )
                    }
                    onScrollToBottom()
                }
            ) {
                Icon(Icons.Default.KeyboardArrowDown, contentDescription = "回到底部")
            }
        }
    }
}
