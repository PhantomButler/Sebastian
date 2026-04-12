// com/sebastian/android/ui/composer/SendButton.kt
package com.sebastian.android.ui.composer

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.ui.common.AnimationTokens
import com.sebastian.android.viewmodel.ComposerState

/**
 * 发送 / 停止 按钮
 *
 * | state       | 外观                      | 可点击 |
 * |-------------|--------------------------|-------|
 * | IDLE_EMPTY  | 灰色发送图标（禁用）         | 否    |
 * | IDLE_READY  | 激活色发送图标              | 是    |
 * | SENDING     | CircularProgressIndicator | 否    |
 * | STREAMING   | 停止图标 ■                 | 是    |
 * | CANCELLING  | CircularProgressIndicator | 否    |
 *
 * [onLongPress] Phase 3 预留：全双工语音入口，默认 null（不注册长按手势）。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SendButton(
    state: ComposerState,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onLongPress: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val isEnabled = state == ComposerState.IDLE_READY || state == ComposerState.STREAMING
    val containerColor = if (state == ComposerState.IDLE_EMPTY)
        MaterialTheme.colorScheme.surfaceVariant
    else
        MaterialTheme.colorScheme.primary

    val onClick: () -> Unit = when (state) {
        ComposerState.IDLE_READY -> onSend
        ComposerState.STREAMING -> onStop
        else -> ({})
    }

    Surface(
        shape = CircleShape,
        color = containerColor,
        modifier = modifier.size(44.dp),
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .fillMaxSize()
                .combinedClickable(
                    enabled = isEnabled,
                    onClick = onClick,
                    onLongClick = onLongPress,
                ),
        ) {
            AnimatedContent(
                targetState = state,
                transitionSpec = {
                    fadeIn(tween(AnimationTokens.STATE_TRANSITION_DURATION_MS)) togetherWith
                        fadeOut(tween(AnimationTokens.STATE_TRANSITION_DURATION_MS))
                },
                label = "send_button_state",
            ) { targetState ->
                when (targetState) {
                    ComposerState.IDLE_EMPTY, ComposerState.IDLE_READY -> Icon(
                        imageVector = Icons.Default.Send,
                        contentDescription = "发送",
                        tint = if (targetState == ComposerState.IDLE_EMPTY)
                            MaterialTheme.colorScheme.onSurfaceVariant
                        else
                            MaterialTheme.colorScheme.onPrimary,
                    )
                    ComposerState.STREAMING -> Icon(
                        imageVector = Icons.Default.Stop,
                        contentDescription = "停止",
                        tint = MaterialTheme.colorScheme.onPrimary,
                    )
                    ComposerState.SENDING, ComposerState.CANCELLING -> CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                }
            }
        }
    }
}
