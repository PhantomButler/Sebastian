// com/sebastian/android/ui/composer/Composer.kt
package com.sebastian.android.ui.composer

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
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
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.viewmodel.ComposerState

/**
 * Composer 主容器（插槽架构）。
 *
 * 自身无状态：ComposerState 由 ChatViewModel 持有并通过 prop 传入。
 * Phase 2 预留插槽（voiceSlot, attachmentSlot）默认 null，接入时不修改此文件。
 */
@Composable
fun Composer(
    state: ComposerState,
    activeProvider: Provider?,
    effort: ThinkingEffort,
    onEffortChange: (ThinkingEffort) -> Unit,
    onSend: (String) -> Unit,
    onStop: () -> Unit,
    // Phase 2 插槽预留
    voiceSlot: @Composable (() -> Unit)? = null,
    attachmentSlot: @Composable (() -> Unit)? = null,
    attachmentPreviewSlot: @Composable (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    var text by rememberSaveable { mutableStateOf("") }

    // Composer 内部根据文字内容通知父层更新 ComposerState
    // 实际 state 修改在 ChatViewModel，Composer 只读 state prop
    val effectiveState = when {
        state == ComposerState.STREAMING || state == ComposerState.SENDING || state == ComposerState.CANCELLING -> state
        text.isNotBlank() -> ComposerState.IDLE_READY
        else -> ComposerState.IDLE_EMPTY
    }

    Surface(
        shape = RoundedCornerShape(16.dp),
        tonalElevation = 2.dp,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 8.dp),
    ) {
        Column {
            // 附件预览区（Phase 2 填充）
            attachmentPreviewSlot?.let {
                it()
            }

            // 文字输入区
            TextField(
                value = text,
                onValueChange = { newText ->
                    text = newText
                },
                placeholder = {
                    androidx.compose.material3.Text("发消息给 Sebastian")
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

            // 工具栏
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 左侧插槽区
                ThinkButton(
                    activeProvider = activeProvider,
                    currentEffort = effort,
                    onEffortChange = onEffortChange,
                )
                voiceSlot?.let {
                    Spacer(Modifier.width(4.dp))
                    it()
                }
                attachmentSlot?.let {
                    Spacer(Modifier.width(4.dp))
                    it()
                }

                Spacer(Modifier.weight(1f))

                // 右侧发送/停止按钮
                SendButton(
                    state = effectiveState,
                    onSend = {
                        val msg = text.trim()
                        if (msg.isNotEmpty()) {
                            text = ""
                            onSend(msg)
                        }
                    },
                    onStop = onStop,
                )
            }
        }
    }
}
