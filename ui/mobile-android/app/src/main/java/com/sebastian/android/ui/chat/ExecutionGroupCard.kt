package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ContentBlock

@Composable
fun ExecutionGroupCard(
    group: MessageRenderItem.ExecutionGroup,
    onToggleThinking: (String) -> Unit,
    onToggleTool: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val stateKey = group.blocks.firstOrNull()?.blockId ?: group.id
    var expanded by rememberSaveable(stateKey) { mutableStateOf(false) }
    val activeSummary = remember(group.blocks) { activeExecutionSummary(group.blocks) }

    Column(modifier = modifier.fillMaxWidth()) {
        ExecutionGroupHeader(
            blocks = group.blocks,
            expanded = expanded,
            onToggle = { expanded = !expanded },
        )

        FoldedActiveExecutionSummary(
            summary = if (expanded) null else activeSummary,
        )

        AnimatedVisibility(
            visible = expanded,
            enter = fadeIn(animationSpec = tween(durationMillis = 200)) +
                expandVertically(animationSpec = tween(durationMillis = 260)),
            exit = fadeOut(animationSpec = tween(durationMillis = 160)) +
                shrinkVertically(animationSpec = tween(durationMillis = 220)),
        ) {
            ExecutionGroupDetails(
                blocks = group.blocks,
                onToggleThinking = onToggleThinking,
                onToggleTool = onToggleTool,
            )
        }
    }
}

@Composable
private fun FoldedActiveExecutionSummary(
    summary: ActiveExecutionSummary?,
) {
    AnimatedContent(
        targetState = summary,
        transitionSpec = {
            (fadeIn(animationSpec = tween(durationMillis = 180)) +
                slideInVertically(animationSpec = tween(durationMillis = 220)) { fullHeight -> fullHeight }) togetherWith
                (fadeOut(animationSpec = tween(durationMillis = 140)) +
                    slideOutVertically(animationSpec = tween(durationMillis = 180)) { fullHeight -> -fullHeight })
        },
        label = "active-execution-summary",
    ) { targetSummary ->
        if (targetSummary != null) {
            Text(
                text = targetSummary.text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.66f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 28.dp, top = 1.dp, bottom = 3.dp),
            )
        }
    }
}

@Composable
private fun ExecutionGroupHeader(
    blocks: List<ContentBlock>,
    expanded: Boolean,
    onToggle: () -> Unit,
) {
    val interactionSource = remember { MutableInteractionSource() }
    val mutedColor = MaterialTheme.colorScheme.onSurfaceVariant

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                onClick = onToggle,
            )
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = if (expanded) {
                Icons.Default.KeyboardArrowDown
            } else {
                Icons.AutoMirrored.Filled.KeyboardArrowRight
            },
            contentDescription = if (expanded) "折叠执行步骤" else "展开执行步骤",
            tint = mutedColor.copy(alpha = 0.42f),
            modifier = Modifier.size(18.dp),
        )
        Spacer(Modifier.width(6.dp))
        ExecutionCapsuleTimeline(
            blocks = blocks,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun ExecutionCapsuleTimeline(
    blocks: List<ContentBlock>,
    modifier: Modifier = Modifier,
) {
    val scrollState = rememberScrollState()
    val stepStates = remember(blocks) { blocks.map(::executionStepState) }
    val activeIndex = stepStates.indexOfLast { it == ExecutionStepState.RUNNING }
    val signature = remember(blocks, stepStates) {
        blocks.joinToString("|") { block ->
            "${block.blockId}:${executionStepState(block)}"
        }
    }

    LaunchedEffect(signature, scrollState.maxValue) {
        withFrameNanos { }
        scrollState.scrollTo(scrollState.maxValue)
    }

    Row(
        modifier = modifier
            .height(14.dp)
            .horizontalScroll(scrollState)
            .padding(start = 2.dp, end = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        stepStates.forEachIndexed { index, state ->
            ExecutionCapsule(
                state = state,
                active = index == activeIndex,
            )
            if (index != stepStates.lastIndex) {
                Spacer(Modifier.width(3.dp))
            }
        }
    }
}

@Composable
private fun ExecutionCapsule(
    state: ExecutionStepState,
    active: Boolean,
) {
    val color = when (state) {
        ExecutionStepState.DONE -> Color(0xFF22C55E)
        ExecutionStepState.RUNNING -> Color(0xFF22C55E)
        ExecutionStepState.FAILED -> Color(0xFFEF4444)
    }
    val scaleY = if (active) {
        val infiniteTransition = rememberInfiniteTransition(label = "execution-capsule")
        val runningScale by infiniteTransition.animateFloat(
            initialValue = 0.82f,
            targetValue = 1.08f,
            animationSpec = infiniteRepeatable(
                animation = tween(durationMillis = 920),
                repeatMode = RepeatMode.Reverse,
            ),
            label = "running-scale",
        )
        runningScale
    } else {
        1f
    }

    Box(
        modifier = Modifier
            .width(4.dp)
            .height(9.dp)
            .scale(scaleX = 1f, scaleY = scaleY)
            .background(color = color, shape = RoundedCornerShape(percent = 50)),
    )
}

@Composable
private fun ExecutionGroupDetails(
    blocks: List<ContentBlock>,
    onToggleThinking: (String) -> Unit,
    onToggleTool: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 28.dp, top = 4.dp),
    ) {
        blocks.forEach { block ->
            when (block) {
                is ContentBlock.ThinkingBlock -> ThinkingCard(
                    block = block,
                    onToggle = { onToggleThinking(block.blockId) },
                    modifier = Modifier.fillMaxWidth(),
                )

                is ContentBlock.ToolBlock -> ToolCallCard(
                    block = block,
                    onToggle = { onToggleTool(block.blockId) },
                    modifier = Modifier.fillMaxWidth(),
                )

                else -> {}
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}
