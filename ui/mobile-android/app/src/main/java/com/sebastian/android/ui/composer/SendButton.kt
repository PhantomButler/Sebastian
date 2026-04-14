// com/sebastian/android/ui/composer/SendButton.kt
package com.sebastian.android.ui.composer

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.foundation.layout.size
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.ui.common.AnimationTokens
import com.sebastian.android.ui.common.SebastianIcons
import com.sebastian.android.ui.common.glass.GlassButtonTint
import com.sebastian.android.ui.common.glass.GlassCircleButton
import com.sebastian.android.viewmodel.ComposerState

/**
 * 发送 / 停止 按钮（液态玻璃风格）
 *
 * | state       | 外观                      | 可点击 |
 * |-------------|--------------------------|-------|
 * | IDLE_EMPTY  | Neutral 玻璃圆（禁用）      | 否    |
 * | IDLE_READY  | Primary 玻璃圆 + 发送图标   | 是    |
 * | SENDING     | Neutral 玻璃圆 + 进度环     | 否    |
 * | STREAMING   | Primary 玻璃圆 + 停止图标   | 是    |
 * | CANCELLING  | Neutral 玻璃圆 + 进度环     | 否    |
 *
 * [onLongPress] Phase 3 预留：全双工语音入口，默认 null。
 */
@Composable
fun SendButton(
    state: ComposerState,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onLongPress: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val isEnabled = state == ComposerState.IDLE_READY || state == ComposerState.STREAMING
    val tint = if (state == ComposerState.IDLE_READY || state == ComposerState.STREAMING)
        GlassButtonTint.Primary
    else
        GlassButtonTint.Neutral

    val onClick: () -> Unit = when (state) {
        ComposerState.IDLE_READY -> onSend
        ComposerState.STREAMING -> onStop
        else -> ({})
    }

    GlassCircleButton(
        onClick = onClick,
        tint = tint,
        enabled = isEnabled,
        onLongClick = onLongPress,
        modifier = modifier,
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
                    imageVector = SebastianIcons.SendAction,
                    contentDescription = "发送",
                    tint = if (targetState == ComposerState.IDLE_READY)
                        MaterialTheme.colorScheme.onPrimary
                    else
                        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f),
                )
                ComposerState.STREAMING -> Icon(
                    imageVector = SebastianIcons.StopAction,
                    contentDescription = "停止",
                    tint = MaterialTheme.colorScheme.onPrimary,
                )
                ComposerState.SENDING, ComposerState.CANCELLING -> CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
            }
        }
    }
}
