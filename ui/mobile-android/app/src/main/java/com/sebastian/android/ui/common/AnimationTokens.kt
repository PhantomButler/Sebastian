package com.sebastian.android.ui.common

import androidx.compose.animation.core.FastOutSlowInEasing

object AnimationTokens {
    // Thinking：慢呼吸光晕
    const val THINKING_PULSE_DURATION_MS = 2000
    const val THINKING_PULSE_MIN_ALPHA = 0.4f
    const val THINKING_PULSE_MAX_ALPHA = 1.0f
    val THINKING_PULSE_EASING = FastOutSlowInEasing

    // Streaming：新 chunk 淡入
    const val STREAMING_CHUNK_FADE_IN_MS = 200

    // Working（工具调用进行中）：脉冲
    const val WORKING_PULSE_DURATION_MS = 1200
    const val WORKING_PULSE_MIN_ALPHA = 0.5f

    // 状态切换 crossfade
    const val STATE_TRANSITION_DURATION_MS = 300
}
