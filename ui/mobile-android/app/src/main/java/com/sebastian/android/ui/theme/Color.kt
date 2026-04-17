package com.sebastian.android.ui.theme

import androidx.compose.ui.graphics.Color

// Material3 动态颜色优先（Android 12+），以下为 fallback
val PrimaryLight = Color(0xFF1A73E8)
val OnPrimaryLight = Color(0xFFFFFFFF)
val SurfaceLight = Color(0xFFFFFFFF)
val OnSurfaceLight = Color(0xFF202124)
val BackgroundLight = Color(0xFFFFFFFF)
val SurfaceVariantLight = Color(0xFFF1F3F4)
val OnSurfaceVariantLight = Color(0xFF444746)

val PrimaryDark = Color(0xFF8AB4F8)
val OnPrimaryDark = Color(0xFF1A3A5C)
val SurfaceDark = Color(0xFF202124)
val OnSurfaceDark = Color(0xFFE8EAED)
val BackgroundDark = Color(0xFF171717)
val SurfaceVariantDark = Color(0xFF2D2F31)
val OnSurfaceVariantDark = Color(0xFFC4C7C5)

// 用户消息气泡
val UserBubbleLight = Color(0xFF96EFA0)
val OnUserBubbleLight = Color(0xFF1A3A1A)
val UserBubbleDark = Color(0xFF2E2E2E)
val OnUserBubbleDark = Color(0xFFE0E0E0)
val UserBubbleBorderDark = Color(0xFF505050)

// ── 补全 M3 token（日间）──────────────────────────────────────────────────────
val SurfaceContainerLight = Color(0xFFF1F3F4)       // 卡片背景
val SurfaceContainerHighestLight = Color(0xFFE8EAED) // 输入框容器
val SurfaceContainerLowLight = Color(0xFFF8F9FA)     // 低层级容器
val PrimaryContainerLight = Color(0xFFD3E3FD)        // 蓝色浅容器
val ErrorLight = Color(0xFFB00020)                   // 错误红
val OnErrorLight = Color(0xFFFFFFFF)                 // 错误上文字
val ErrorContainerLight = Color(0xFFFFDAD6)          // 错误浅容器
val OnErrorContainerLight = Color(0xFF410002)        // 错误容器上文字
val OutlineVariantLight = Color(0xFFC7C7CC)          // 分割线

// ── 补全 M3 token（夜间）──────────────────────────────────────────────────────
val SurfaceContainerDark = Color(0xFF292B2D)
val SurfaceContainerHighestDark = Color(0xFF36393B)
val SurfaceContainerLowDark = Color(0xFF252729)
val PrimaryContainerDark = Color(0xFF0A3266)
val ErrorDark = Color(0xFFCF6679)
val OnErrorDark = Color(0xFF690005)
val ErrorContainerDark = Color(0xFF93000A)
val OnErrorContainerDark = Color(0xFFFFDAD6)
val OutlineVariantDark = Color(0xFF3C3F41)

// ── SebastianSwitch 苹果绿 ───────────────────────────────────────────────────
// 不进入 colorScheme，由 SebastianSwitch 直接引用
val SwitchCheckedLight = Color(0xFF34C759)  // 日间苹果绿
val SwitchCheckedDark = Color(0xFF30D158)   // 夜间苹果绿（更亮）

// ── Agent 活动指示器（Jarvis 蓝）────────────────────────────────
// 不进入 colorScheme，由 AgentPill 直接引用（参考 SwitchChecked 的 pattern）
val AgentAccentLight = Color(0xFF6FC3FF)
val AgentAccentDark = Color(0xFF9FD6FF)

// Rainbow breathing halo for PENDING state.
val AgentRainbowPurpleLight = Color(0xFF9F7BFF)
val AgentRainbowPurpleDark = Color(0xFFB79BFF)
val AgentRainbowCyanLight = Color(0xFF7BE0D1)
val AgentRainbowCyanDark = Color(0xFF9BEAE0)
