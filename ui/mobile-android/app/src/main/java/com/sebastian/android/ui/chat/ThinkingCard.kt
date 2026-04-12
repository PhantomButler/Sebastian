package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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

    Card(
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClick = onToggle)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = Icons.Default.Psychology,
                    contentDescription = "思考",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = if (!block.done) Modifier.alpha(pulseAlpha.value) else Modifier,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = if (block.done) "思考过程" else "思考中…",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.weight(1f),
                )
                Icon(
                    imageVector = if (block.expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                    contentDescription = if (block.expanded) "折叠" else "展开",
                )
            }

            AnimatedVisibility(
                visible = block.expanded,
                enter = expandVertically(),
                exit = shrinkVertically(),
            ) {
                Text(
                    text = block.text,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                )
            }
        }
    }
}
