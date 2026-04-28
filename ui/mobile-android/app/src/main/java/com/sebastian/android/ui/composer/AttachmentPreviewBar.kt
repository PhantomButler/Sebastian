package com.sebastian.android.ui.composer

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedAssistChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.AttachmentUploadState
import com.sebastian.android.data.model.PendingAttachment

@Composable
fun AttachmentPreviewBar(
    attachments: List<PendingAttachment>,
    onRemove: (String) -> Unit,
    onRetry: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (attachments.isEmpty()) return

    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        attachments.forEach { att ->
            AttachmentChip(
                att = att,
                onRemove = { onRemove(att.localId) },
                onRetry = { onRetry(att.localId) },
            )
        }
    }
}

@Composable
private fun AttachmentChip(
    att: PendingAttachment,
    onRemove: () -> Unit,
    onRetry: () -> Unit,
) {
    val state = att.uploadState
    ElevatedAssistChip(
        onClick = {},
        label = { Text(att.filename, maxLines = 1) },
        leadingIcon = {
            when (state) {
                is AttachmentUploadState.Uploading -> CircularProgressIndicator(
                    progress = { state.progress },
                    modifier = Modifier.size(16.dp),
                    strokeWidth = 2.dp,
                )
                is AttachmentUploadState.Failed -> Icon(
                    Icons.Default.Refresh,
                    contentDescription = "重试",
                    modifier = Modifier.size(16.dp),
                )
                else -> null
            }
        },
        trailingIcon = {
            Row {
                if (state is AttachmentUploadState.Failed) {
                    IconButton(
                        onClick = onRetry,
                        modifier = Modifier.size(18.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "重试",
                            modifier = Modifier.size(14.dp),
                        )
                    }
                }
                IconButton(
                    onClick = onRemove,
                    modifier = Modifier.size(18.dp),
                ) {
                    Icon(
                        imageVector = Icons.Default.Close,
                        contentDescription = "移除",
                        modifier = Modifier.size(14.dp),
                    )
                }
            }
        },
    )
}
