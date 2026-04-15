package com.sebastian.android.ui.common

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.spring
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.sebastian.android.ui.common.glass.GlassState
import com.sebastian.android.ui.common.glass.GlassSurface
import com.sebastian.android.viewmodel.GlobalApproval

private val CardShape = RoundedCornerShape(28.dp)
private val PillShape = RoundedCornerShape(50.dp)

@Composable
fun GlobalApprovalBanner(
    approval: GlobalApproval?,
    glassState: GlassState,
    onGrant: (String) -> Unit,
    onDeny: (String) -> Unit,
    onNavigateToSession: (GlobalApproval) -> Unit,
    modifier: Modifier = Modifier,
) {
    AnimatedVisibility(
        visible = approval != null,
        enter = fadeIn() + scaleIn(spring(dampingRatio = 0.7f, stiffness = 400f), initialScale = 0.9f),
        exit = fadeOut() + scaleOut(targetScale = 0.92f),
        modifier = modifier,
    ) {
        approval?.let { current ->
            val summary = remember(current.toolName, current.toolInputJson) {
                summarizeApproval(current.toolName, current.toolInputJson)
            }
            val clippedReason = remember(current.reason) { clipReason(current.reason) }
            val lastDetailsClickMs = remember { mutableLongStateOf(0L) }

            Box(
                modifier = Modifier
                    .statusBarsPadding()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                GlassSurface(
                    state = glassState,
                    shape = CardShape,
                    shadowElevation = 16.dp,
                    shadowCornerRadius = 28.dp,
                    shadowColor = Color.Black.copy(alpha = 0.22f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                    ) {
                        // Header: color bar + agent name + action title
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(
                                modifier = Modifier
                                    .size(width = 3.dp, height = 16.dp)
                                    .clip(RoundedCornerShape(2.dp))
                                    .background(MaterialTheme.colorScheme.primary),
                            )
                            Spacer(Modifier.size(8.dp))
                            Text(
                                text = current.agentType,
                                style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.primary,
                            )
                            Spacer(Modifier.size(6.dp))
                            Text(
                                text = "requests · ${summary.title}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }

                        Spacer(Modifier.height(10.dp))

                        // Detail card: tool name + main param
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f))
                                .padding(horizontal = 12.dp, vertical = 8.dp),
                        ) {
                            Column {
                                if (current.toolName.isNotBlank()) {
                                    Text(
                                        text = current.toolName,
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    Spacer(Modifier.height(2.dp))
                                }
                                Text(
                                    text = summary.detail,
                                    style = MaterialTheme.typography.bodySmall.copy(
                                        fontFamily = FontFamily.Monospace,
                                    ),
                                    color = MaterialTheme.colorScheme.onSurface,
                                    maxLines = 3,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }

                        if (clippedReason.isNotBlank()) {
                            Spacer(Modifier.height(6.dp))
                            Text(
                                text = "Reason: $clippedReason",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }

                        // Actions
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            TextButton(onClick = {
                                val now = System.currentTimeMillis()
                                if (now - lastDetailsClickMs.longValue < 500L) return@TextButton
                                lastDetailsClickMs.longValue = now
                                onNavigateToSession(current)
                            }) {
                                Text("Details")
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                GlassPillButton(
                                    text = "Deny",
                                    onClick = { onDeny(current.approvalId) },
                                    containerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.82f),
                                    contentColor = Color.White,
                                )
                                GlassPillButton(
                                    text = "Allow",
                                    onClick = { onGrant(current.approvalId) },
                                    containerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.88f),
                                    contentColor = Color.White,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun GlassPillButton(
    text: String,
    onClick: () -> Unit,
    containerColor: Color,
    contentColor: Color,
    modifier: Modifier = Modifier,
) {
    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier
            .widthIn(min = 80.dp)
            .clip(PillShape)
            .background(containerColor)
            .border(0.5.dp, Color.White.copy(alpha = 0.18f), PillShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 20.dp, vertical = 10.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelLarge,
            color = contentColor,
        )
    }
}
