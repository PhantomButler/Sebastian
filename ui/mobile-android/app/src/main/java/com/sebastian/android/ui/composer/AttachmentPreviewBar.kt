package com.sebastian.android.ui.composer

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedAssistChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.sebastian.android.data.model.AttachmentKind
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
            if (att.kind == AttachmentKind.IMAGE) {
                ImageAttachmentPreview(
                    att = att,
                    onRemove = { onRemove(att.localId) },
                    onRetry = { onRetry(att.localId) },
                )
            } else {
                AttachmentChip(
                    att = att,
                    onRemove = { onRemove(att.localId) },
                    onRetry = { onRetry(att.localId) },
                )
            }
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
        leadingIcon = when (state) {
            is AttachmentUploadState.Uploading -> ({
                CircularProgressIndicator(
                    modifier = Modifier.size(16.dp),
                    strokeWidth = 2.dp,
                )
            })
            is AttachmentUploadState.Failed -> ({
                Icon(
                    Icons.Default.Warning,
                    contentDescription = "上传失败",
                    modifier = Modifier.size(16.dp),
                    tint = MaterialTheme.colorScheme.error,
                )
            })
            else -> null
        },
        trailingIcon = {
            Row {
                if (state is AttachmentUploadState.Failed) {
                    IconButton(
                        onClick = onRetry,
                        modifier = Modifier.size(36.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "重试",
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }
                IconButton(
                    onClick = onRemove,
                    modifier = Modifier.size(36.dp),
                ) {
                    Icon(
                        imageVector = Icons.Default.Close,
                        contentDescription = "移除",
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
        },
    )
}

@Composable
private fun ImageAttachmentPreview(
    att: PendingAttachment,
    onRemove: () -> Unit,
    onRetry: () -> Unit,
) {
    val state = att.uploadState
    val shape = RoundedCornerShape(8.dp)
    Column(
        modifier = Modifier.width(104.dp),
    ) {
        Box(
            modifier = Modifier
                .size(width = 104.dp, height = 78.dp)
                .clip(shape)
                .background(MaterialTheme.colorScheme.surfaceVariant),
        ) {
            AsyncImage(
                model = att.uri,
                contentDescription = att.filename,
                contentScale = ContentScale.Crop,
                modifier = Modifier.matchParentSize(),
            )
            Row(
                modifier = Modifier.align(Alignment.TopEnd),
            ) {
                if (state is AttachmentUploadState.Failed) {
                    IconButton(
                        onClick = onRetry,
                        modifier = Modifier.size(32.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "重试",
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }
                IconButton(
                    onClick = onRemove,
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(
                        imageVector = Icons.Default.Close,
                        contentDescription = "移除",
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
            if (state is AttachmentUploadState.Uploading) {
                CircularProgressIndicator(
                    modifier = Modifier
                        .size(20.dp)
                        .align(Alignment.Center),
                    strokeWidth = 2.dp,
                )
            }
            if (state is AttachmentUploadState.Failed) {
                Icon(
                    Icons.Default.Warning,
                    contentDescription = "上传失败",
                    modifier = Modifier
                        .size(20.dp)
                        .align(Alignment.BottomStart)
                        .padding(2.dp),
                    tint = MaterialTheme.colorScheme.error,
                )
            }
        }
        Text(
            text = att.filename,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}
