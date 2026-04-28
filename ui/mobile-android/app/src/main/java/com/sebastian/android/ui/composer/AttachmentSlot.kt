package com.sebastian.android.ui.composer

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Row
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Image
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.graphics.Color

@Composable
fun AttachmentToolbar(
    onFileClick: () -> Unit,
    onImageClick: () -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val iconTint = if (isSystemInDarkTheme()) Color(0xFF9E9E9E) else Color.Black

    Row(modifier) {
        IconButton(
            onClick = onFileClick,
            enabled = enabled,
            modifier = Modifier.focusProperties { canFocus = false },
        ) {
            Icon(Icons.Default.AttachFile, contentDescription = "选择文件", tint = iconTint)
        }
        IconButton(
            onClick = onImageClick,
            enabled = enabled,
            modifier = Modifier.focusProperties { canFocus = false },
        ) {
            Icon(Icons.Default.Image, contentDescription = "选择图片", tint = iconTint)
        }
    }
}
