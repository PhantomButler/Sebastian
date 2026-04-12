// com/sebastian/android/ui/composer/SendButton.kt
package com.sebastian.android.ui.composer

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
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
 */
@Composable
fun SendButton(
    state: ComposerState,
    onSend: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isEnabled = state == ComposerState.IDLE_READY || state == ComposerState.STREAMING
    val containerColor = if (state == ComposerState.IDLE_EMPTY)
        MaterialTheme.colorScheme.surfaceVariant
    else
        MaterialTheme.colorScheme.primary

    FilledIconButton(
        onClick = when (state) {
            ComposerState.IDLE_READY -> onSend
            ComposerState.STREAMING -> onStop
            else -> { {} }
        },
        enabled = isEnabled,
        colors = IconButtonDefaults.filledIconButtonColors(
            containerColor = containerColor,
            disabledContainerColor = containerColor,
        ),
        modifier = modifier.size(44.dp),
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
                )
                ComposerState.STREAMING -> Icon(
                    imageVector = Icons.Default.Stop,
                    contentDescription = "停止",
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
