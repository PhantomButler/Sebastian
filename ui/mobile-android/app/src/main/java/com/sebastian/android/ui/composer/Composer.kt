// com/sebastian/android/ui/composer/Composer.kt
package com.sebastian.android.ui.composer

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.PendingAttachment
import com.sebastian.android.ui.common.glass.GlassState
import com.sebastian.android.ui.common.glass.GlassSurface
import com.sebastian.android.viewmodel.ComposerState

/**
 * Composer 主容器（插槽架构）。
 *
 * 自身无状态：ComposerState 由 ChatViewModel 持有并通过 prop 传入。
 * 玻璃效果由外部传入的 [glassState] 驱动，内容层采样标记由 ChatScreen 负责。
 */
@Composable
fun Composer(
    state: ComposerState,
    glassState: GlassState,
    onSend: (String, List<PendingAttachment>) -> Unit,
    onStop: () -> Unit,
    pendingAttachments: List<PendingAttachment> = emptyList(),
    // Phase 2 插槽
    voiceSlot: @Composable (() -> Unit)? = null,
    attachmentSlot: @Composable (() -> Unit)? = null,
    attachmentPreviewSlot: @Composable (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    var text by rememberSaveable { mutableStateOf("") }

    val effectiveState = when {
        state == ComposerState.STREAMING || state == ComposerState.PENDING || state == ComposerState.CANCELLING -> state
        text.isNotBlank() || pendingAttachments.isNotEmpty() -> ComposerState.IDLE_READY
        else -> ComposerState.IDLE_EMPTY
    }

    GlassSurface(
        state = glassState,
        shape = RoundedCornerShape(24.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column {
            // 附件预览区
            AnimatedVisibility(visible = attachmentPreviewSlot != null) {
                attachmentPreviewSlot?.invoke()
            }

            // 文字输入区
            TextField(
                value = text,
                onValueChange = { text = it },
                placeholder = {
                    androidx.compose.material3.Text(
                        text = "Message Sebastian…",
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.35f),
                    )
                },
                maxLines = 6,
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            // 工具栏（ThinkButton 已下线，用等高 Spacer 占位保持整体高度不变）
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 4.dp, end = 4.dp, top = 2.dp, bottom = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 原 ThinkButton 位置空出，用与 ThinkButton 等高的 Spacer 占位（48dp 高度）
                Spacer(Modifier.size(width = 0.dp, height = 48.dp))
                voiceSlot?.let {
                    Spacer(Modifier.width(4.dp))
                    it()
                }
                attachmentSlot?.let {
                    it()
                }

                Spacer(Modifier.weight(1f))

                SendButton(
                    state = effectiveState,
                    onSend = {
                        val msg = text.trim()
                        if (msg.isNotEmpty() || pendingAttachments.isNotEmpty()) {
                            text = ""
                            onSend(msg, pendingAttachments)
                        }
                    },
                    onStop = onStop,
                )
            }
        }
    }
}
