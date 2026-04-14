package com.sebastian.android.ui.chat

import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.ui.Alignment
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.graphics.luminance
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.ui.common.AnimationTokens
import com.sebastian.android.ui.common.MarkdownView
import com.sebastian.android.ui.theme.OnUserBubbleDark
import com.sebastian.android.ui.theme.OnUserBubbleLight
import com.sebastian.android.ui.theme.UserBubbleBorderDark
import com.sebastian.android.ui.theme.UserBubbleDark
import com.sebastian.android.ui.theme.UserBubbleLight

@Composable
fun MessageBubble(
    message: Message,
    onToggleThinking: (String, String) -> Unit,
    onToggleTool: (String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (message.role == MessageRole.USER) {
        UserMessageBubble(text = message.text, modifier = modifier)
    } else {
        AssistantMessageBlocks(
            msgId = message.id,
            blocks = message.blocks,
            onToggleThinking = onToggleThinking,
            onToggleTool = onToggleTool,
            modifier = modifier,
        )
    }
}

@Composable
private fun UserMessageBubble(text: String, modifier: Modifier = Modifier) {
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val bubbleShape = RoundedCornerShape(16.dp, 4.dp, 16.dp, 16.dp)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 48.dp, end = 16.dp),
        contentAlignment = Alignment.CenterEnd,
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyLarge,
            color = if (isDark) OnUserBubbleDark else OnUserBubbleLight,
            modifier = Modifier
                .background(
                    color = if (isDark) UserBubbleDark else UserBubbleLight,
                    shape = bubbleShape,
                )
                .then(
                    if (isDark) Modifier.border(
                        width = 0.5.dp,
                        color = UserBubbleBorderDark,
                        shape = bubbleShape,
                    ) else Modifier
                )
                .padding(horizontal = 12.dp, vertical = 8.dp),
        )
    }
}

@Composable
private fun AssistantMessageBlocks(
    msgId: String,
    blocks: List<ContentBlock>,
    onToggleThinking: (String, String) -> Unit,
    onToggleTool: (String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val knownIds = remember { mutableStateListOf<String>() }
    val alphaMap = remember { mutableStateMapOf<String, Animatable<Float, *>>() }

    LaunchedEffect(blocks.size) {
        val newBlocks = blocks.filter { it.blockId !in knownIds }
        // 顺序淡入（staggered reveal）：每个 block 等前一个完成后再淡入，营造逐步展开感
        // 并行淡入可将 animateTo 改为并发 launch { } 块
        for (block in newBlocks) {
            knownIds.add(block.blockId)
            if (!block.isDone) {
                val anim = Animatable(0f)
                alphaMap[block.blockId] = anim
                anim.animateTo(
                    targetValue = 1f,
                    animationSpec = androidx.compose.animation.core.tween(
                        durationMillis = AnimationTokens.STREAMING_CHUNK_FADE_IN_MS,
                    ),
                )
            }
        }
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
    ) {
        blocks.forEach { block ->
            val alpha = alphaMap[block.blockId]?.value ?: 1f
            when (block) {
                is ContentBlock.ThinkingBlock -> ThinkingCard(
                    block = block,
                    onToggle = { onToggleThinking(msgId, block.blockId) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .alpha(alpha),
                )
                is ContentBlock.ToolBlock -> ToolCallCard(
                    block = block,
                    onToggle = { onToggleTool(msgId, block.blockId) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .alpha(alpha),
                )
                is ContentBlock.TextBlock -> {
                    if (block.done && block.renderedMarkdown != null) {
                        MarkdownView(
                            markdown = block.renderedMarkdown,
                            modifier = Modifier
                                .fillMaxWidth()
                                .alpha(alpha),
                        )
                    } else {
                        // Streaming in progress OR parse pending — show plain text
                        Text(
                            text = block.text,
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier
                                .fillMaxWidth()
                                .alpha(alpha),
                        )
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}
