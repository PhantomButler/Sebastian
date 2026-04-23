package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Alignment
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.graphics.luminance
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
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
    onToggleSummary: (String, String) -> Unit,
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
            onToggleSummary = onToggleSummary,
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
    onToggleSummary: (String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val knownIds = remember { mutableStateListOf<String>() }
    val alphaMap = remember { mutableStateMapOf<String, Animatable<Float, *>>() }
    val scope = rememberCoroutineScope()

    LaunchedEffect(blocks.size) {
        val newBlocks = blocks.filter { it.blockId !in knownIds }
        for (block in newBlocks) {
            knownIds.add(block.blockId)
            if (!block.isDone) {
                val anim = Animatable(0f)
                alphaMap[block.blockId] = anim
                // 在 rememberCoroutineScope 上独立启动，不受 LaunchedEffect 重启影响
                scope.launch {
                    anim.animateTo(
                        targetValue = 1f,
                        animationSpec = tween(durationMillis = AnimationTokens.STREAMING_CHUNK_FADE_IN_MS),
                    )
                }
            }
        }
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
    ) {
        blocks.forEach { block ->
            key(block.blockId) {
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
                    is ContentBlock.TextBlock -> MarkdownView(
                        text = block.text,
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(alpha),
                    )
                    is ContentBlock.SummaryBlock -> SummaryCard(
                        block = block,
                        onToggle = { onToggleSummary(msgId, block.blockId) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(alpha),
                    )
                }
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

@Composable
private fun SummaryCard(
    block: ContentBlock.SummaryBlock,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val mutedColor = MaterialTheme.colorScheme.onSurfaceVariant
    val titleColor = mutedColor.copy(alpha = 0.6f)
    val interactionSource = remember { MutableInteractionSource() }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                onClick = onToggle,
            ),
    ) {
        Row(
            modifier = Modifier.padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "Compressed summary",
                style = MaterialTheme.typography.titleMedium,
                color = titleColor,
            )
            Spacer(Modifier.width(6.dp))
            Icon(
                imageVector = if (block.expanded) {
                    Icons.Default.KeyboardArrowDown
                } else {
                    Icons.AutoMirrored.Filled.KeyboardArrowRight
                },
                contentDescription = if (block.expanded) "折叠" else "展开",
                tint = titleColor,
                modifier = Modifier.size(20.dp),
            )
        }

        AnimatedVisibility(
            visible = block.expanded,
            enter = fadeIn(animationSpec = tween(durationMillis = 360)) +
                expandVertically(animationSpec = tween(durationMillis = 300)),
            exit = fadeOut(animationSpec = tween(durationMillis = 200)) +
                shrinkVertically(animationSpec = tween(durationMillis = 300)),
        ) {
            MarkdownView(
                text = block.text,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 4.dp, top = 4.dp, bottom = 4.dp),
            )
        }
    }
}
