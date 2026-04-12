package com.sebastian.android.ui.chat

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Message
import com.sebastian.android.viewmodel.ScrollFollowState

@Composable
fun MessageList(
    messages: List<Message>,
    scrollFollowState: ScrollFollowState,
    onUserScrolled: () -> Unit,
    onScrolledNearBottom: () -> Unit,
    onScrolledToBottom: () -> Unit,
    onToggleThinking: (String) -> Unit,
    onToggleTool: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()

    val isScrollInProgress by remember { derivedStateOf { listState.isScrollInProgress } }

    val isNearBottom by remember {
        derivedStateOf {
            val info = listState.layoutInfo
            val lastVisible = info.visibleItemsInfo.lastOrNull() ?: return@derivedStateOf true
            lastVisible.index >= info.totalItemsCount - 2
        }
    }

    LaunchedEffect(isScrollInProgress) {
        if (isScrollInProgress && scrollFollowState == ScrollFollowState.FOLLOWING) {
            onUserScrolled()
        }
    }

    LaunchedEffect(isNearBottom) {
        if (isNearBottom) {
            onScrolledToBottom()
        } else if (scrollFollowState == ScrollFollowState.NEAR_BOTTOM) {
            onScrolledNearBottom()
        }
    }

    // 流式时自动滚到底
    LaunchedEffect(messages.size, messages.lastOrNull()?.blocks?.size) {
        if (scrollFollowState == ScrollFollowState.FOLLOWING && messages.isNotEmpty()) {
            listState.scrollToItem(messages.size - 1)
        }
    }

    LazyColumn(
        state = listState,
        modifier = modifier,
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
}
