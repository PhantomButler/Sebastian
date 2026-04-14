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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
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
import com.sebastian.android.data.model.ToolStatus
import com.sebastian.android.ui.common.AnimationTokens

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

    Card(
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
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
                when (block.status) {
                    ToolStatus.PENDING, ToolStatus.RUNNING -> CircularProgressIndicator(
                        modifier = Modifier
                            .size(20.dp)
                            .alpha(if (block.status == ToolStatus.RUNNING) pulseAlpha.value else 1f),
                        strokeWidth = 2.dp,
                    )
                    ToolStatus.DONE -> Icon(
                        Icons.Default.Check,
                        contentDescription = "完成",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(20.dp),
                    )
                    ToolStatus.FAILED -> Icon(
                        Icons.Default.Close,
                        contentDescription = "失败",
                        tint = MaterialTheme.colorScheme.error,
                        modifier = Modifier.size(20.dp),
                    )
                }

                Spacer(Modifier.width(8.dp))

                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = block.name,
                        style = MaterialTheme.typography.labelLarge,
                    )
                    block.resultSummary?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    block.error?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }

                Icon(
                    imageVector = if (block.expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                    contentDescription = null,
                )
            }

            AnimatedVisibility(
                visible = block.expanded,
                enter = expandVertically(),
                exit = shrinkVertically(),
            ) {
                Text(
                    text = "输入：${block.inputs}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                )
            }
        }
    }
}
