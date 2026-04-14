package com.sebastian.android.ui.common

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.viewmodel.GlobalApproval

@Composable
fun GlobalApprovalBanner(
    approval: GlobalApproval?,
    onGrant: (String) -> Unit,
    onDeny: (String) -> Unit,
    onNavigateToSession: (GlobalApproval) -> Unit,
    modifier: Modifier = Modifier,
) {
    AnimatedVisibility(
        visible = approval != null,
        enter = slideInVertically { -it },
        exit = slideOutVertically { -it },
        modifier = modifier,
    ) {
        approval?.let { current ->
            Surface(
                shape = RoundedCornerShape(bottomStart = 12.dp, bottomEnd = 12.dp),
                shadowElevation = 8.dp,
                color = MaterialTheme.colorScheme.errorContainer,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier
                        .statusBarsPadding()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                ) {
                    // Row 1: agent name + description
                    Text(
                        text = "${current.agentType} 请求权限审批",
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                    )
                    Text(
                        text = current.description,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.8f),
                        maxLines = 3,
                        modifier = Modifier.padding(top = 4.dp),
                    )

                    // Row 2: actions
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        TextButton(onClick = { onNavigateToSession(current) }) {
                            Text("查看详情")
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                            Button(
                                onClick = { onDeny(current.approvalId) },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = MaterialTheme.colorScheme.error,
                                ),
                                modifier = Modifier.widthIn(min = 80.dp),
                            ) {
                                Text("拒绝")
                            }
                            Button(
                                onClick = { onGrant(current.approvalId) },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = MaterialTheme.colorScheme.primary,
                                ),
                                modifier = Modifier.widthIn(min = 80.dp),
                            ) {
                                Text("允许")
                            }
                        }
                    }
                }
            }
        }
    }
}
