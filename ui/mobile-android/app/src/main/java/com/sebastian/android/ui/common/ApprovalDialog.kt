package com.sebastian.android.ui.common

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.sebastian.android.viewmodel.PendingApproval

@Composable
fun ApprovalDialog(
    approval: PendingApproval,
    onGrant: (String) -> Unit,
    onDeny: (String) -> Unit,
) {
    AlertDialog(
        onDismissRequest = { /* 不允许点击外部关闭，必须明确操作 */ },
        title = { Text("Sebastian 请求授权") },
        text = { Text(approval.description) },
        confirmButton = {
            Button(onClick = { onGrant(approval.approvalId) }) {
                Text("允许")
            }
        },
        dismissButton = {
            OutlinedButton(
                onClick = { onDeny(approval.approvalId) },
                colors = ButtonDefaults.outlinedButtonColors(
                    contentColor = MaterialTheme.colorScheme.error,
                ),
            ) {
                Text("拒绝")
            }
        },
    )
}
