package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.ui.common.AnimationTokens

internal fun formatThinkingDuration(ms: Long): String {
    val s = ms / 1000L
    return if (s < 60L) "${s}s" else "${s / 60L}m ${s % 60L}s"
}

@Composable
fun ThinkingCard(
    block: ContentBlock.ThinkingBlock,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val pulseAlpha = remember { Animatable(AnimationTokens.THINKING_PULSE_MIN_ALPHA) }

    LaunchedEffect(block.done) {
        if (!block.done) {
            while (true) {
                pulseAlpha.animateTo(
                    targetValue = AnimationTokens.THINKING_PULSE_MAX_ALPHA,
                    animationSpec = tween(
                        durationMillis = AnimationTokens.THINKING_PULSE_DURATION_MS,
                        easing = AnimationTokens.THINKING_PULSE_EASING,
                    ),
                )
                pulseAlpha.animateTo(
                    targetValue = AnimationTokens.THINKING_PULSE_MIN_ALPHA,
                    animationSpec = tween(
                        durationMillis = AnimationTokens.THINKING_PULSE_DURATION_MS,
                        easing = AnimationTokens.THINKING_PULSE_EASING,
                    ),
                )
            }
        } else {
            pulseAlpha.snapTo(1f)
        }
    }

    val label = if (block.done) {
        val d = block.durationMs
        if (d != null && d > 0L) "Thought for ${formatThinkingDuration(d)}" else "Thought"
    } else {
        "Thinking"
    }

    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onToggle)
                .padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (!block.done) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .alpha(pulseAlpha.value)
                        .background(MaterialTheme.colorScheme.primary, CircleShape),
                )
                Spacer(Modifier.width(8.dp))
            }

            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )

            Icon(
                imageVector = when {
                    !block.done -> Icons.AutoMirrored.Filled.KeyboardArrowRight
                    block.expanded -> Icons.Default.KeyboardArrowUp
                    else -> Icons.Default.KeyboardArrowDown
                },
                contentDescription = if (block.expanded) "折叠" else "展开",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(16.dp),
            )
        }

        AnimatedVisibility(
            visible = block.expanded,
            enter = expandVertically(),
            exit = shrinkVertically(),
        ) {
            Column {
                HorizontalDivider(
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f),
                    thickness = 1.dp,
                )
                Text(
                    text = block.text,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 8.dp),
                )
            }
        }
    }
}
