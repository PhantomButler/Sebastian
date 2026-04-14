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
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
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

    val mutedColor = MaterialTheme.colorScheme.onSurfaceVariant
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
            if (!block.done) {
                Box(
                    modifier = Modifier
                        .size(6.dp)
                        .alpha(pulseAlpha.value)
                        .background(Color(0xFF22C55E), CircleShape),
                )
                Spacer(Modifier.width(8.dp))
            }

            val titleColor = mutedColor.copy(alpha = 0.6f)
            Text(
                text = label,
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
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(IntrinsicSize.Min),
            ) {
                // 左侧：小圆点 + 竖线
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

                Text(
                    text = block.text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = mutedColor,
                    modifier = Modifier
                        .padding(start = 10.dp, top = 6.dp, bottom = 4.dp),
                )
            }
        }
    }
}
