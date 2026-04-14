package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.ToolStatus
import com.sebastian.android.ui.common.AnimationTokens

// 状态色（与 RN 版对齐，不走主题色以保持跨主题一致辨识度）
private val DOT_PENDING = Color(0xFF9AA0A6)
private val DOT_RUNNING = Color(0xFFF5A623)
private val DOT_DONE = Color(0xFF66BB6A)
private val DOT_FAILED = Color(0xFFF44336)

private fun dotColor(status: ToolStatus): Color = when (status) {
    ToolStatus.PENDING -> DOT_PENDING
    ToolStatus.RUNNING -> DOT_RUNNING
    ToolStatus.DONE -> DOT_DONE
    ToolStatus.FAILED -> DOT_FAILED
}

private fun statusLabel(status: ToolStatus): String = when (status) {
    ToolStatus.PENDING -> "等待中"
    ToolStatus.RUNNING -> "执行中"
    ToolStatus.DONE -> "已完成"
    ToolStatus.FAILED -> "失败"
}

@Composable
fun ToolCallCard(
    block: ContentBlock.ToolBlock,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val pulseAlpha = remember { Animatable(AnimationTokens.WORKING_PULSE_MIN_ALPHA) }

    LaunchedEffect(block.status) {
        if (block.status == ToolStatus.RUNNING) {
            while (true) {
                pulseAlpha.animateTo(
                    targetValue = 1f,
                    animationSpec = tween(durationMillis = AnimationTokens.WORKING_PULSE_DURATION_MS),
                )
                pulseAlpha.animateTo(
                    targetValue = AnimationTokens.WORKING_PULSE_MIN_ALPHA,
                    animationSpec = tween(durationMillis = AnimationTokens.WORKING_PULSE_DURATION_MS),
                )
            }
        } else {
            pulseAlpha.snapTo(1f)
        }
    }

    val mutedColor = MaterialTheme.colorScheme.onSurfaceVariant
    val interactionSource = remember { MutableInteractionSource() }
    val summary = remember(block.name, block.inputs) {
        ToolCallInputExtractor.extractInputSummary(block.name, block.inputs)
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                onClick = onToggle,
            ),
    ) {
        // === Header ===
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 24.dp)
                .padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            val statusAlpha = if (block.status == ToolStatus.RUNNING) pulseAlpha.value else 1f
            val statusText = statusLabel(block.status)
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .alpha(statusAlpha)
                    .background(dotColor(block.status), CircleShape)
                    .semantics { contentDescription = "工具 ${block.name} $statusText" },
            )

            Text(
                text = block.name,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Medium,
                color = mutedColor,
            )

            if (summary.isNotEmpty()) {
                Text(
                    text = summary,
                    style = MaterialTheme.typography.bodySmall,
                    color = mutedColor.copy(alpha = 0.7f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
            } else {
                Spacer(Modifier.weight(1f))
            }

            if (block.expanded) {
                Icon(
                    imageVector = Icons.Default.KeyboardArrowDown,
                    contentDescription = "折叠",
                    tint = mutedColor,
                    modifier = Modifier.size(16.dp),
                )
            }
        }

        // === Expanded body ===
        AnimatedVisibility(
            visible = block.expanded,
            enter = fadeIn(animationSpec = tween(durationMillis = 200)) +
                expandVertically(animationSpec = tween(durationMillis = 260)),
            exit = fadeOut(animationSpec = tween(durationMillis = 160)) +
                shrinkVertically(animationSpec = tween(durationMillis = 220)),
        ) {
            ExpandedBody(block = block, mutedColor = mutedColor)
        }
    }
}

@Composable
private fun ExpandedBody(
    block: ContentBlock.ToolBlock,
    mutedColor: Color,
) {
    val params = remember(block.name, block.inputs) {
        ToolCallInputExtractor.extractKeyParams(block.name, block.inputs)
    }
    val hasResult = !block.resultSummary.isNullOrBlank()
    val hasError = !block.error.isNullOrBlank()
    val showOutput = block.status == ToolStatus.RUNNING || hasResult || hasError

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min),
    ) {
        // 左侧 gutter：与 ThinkingCard 一致的「小圆点 + 细竖线」
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .width(20.dp)
                .fillMaxHeight()
                .padding(top = 10.dp, bottom = 2.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(6.dp)
                    .background(mutedColor.copy(alpha = 0.45f), CircleShape),
            )
            Spacer(Modifier.height(8.dp))
            Box(
                modifier = Modifier
                    .width(1.dp)
                    .weight(1f)
                    .background(mutedColor.copy(alpha = 0.25f)),
            )
        }

        Column(
            modifier = Modifier
                .weight(1f)
                .padding(start = 10.dp, top = 6.dp, bottom = 6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (params.isNotBlank()) {
                SectionLabel(text = "参数", color = mutedColor)
                CollapsibleContent(content = params)
            }

            if (showOutput) {
                SectionLabel(text = "输出", color = mutedColor)
                when {
                    block.status == ToolStatus.RUNNING -> RunningIndicator(mutedColor = mutedColor)
                    hasError -> Text(
                        text = block.error ?: "",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                    hasResult -> CollapsibleContent(content = block.resultSummary ?: "")
                }
            }
        }
    }
}

@Composable
private fun SectionLabel(text: String, color: Color) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.SemiBold,
        color = color,
    )
}

@Composable
private fun RunningIndicator(mutedColor: Color) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier
                .size(6.dp)
                .background(DOT_RUNNING, CircleShape),
        )
        Text(
            text = "执行中…",
            style = MaterialTheme.typography.bodySmall,
            color = mutedColor,
        )
    }
}
