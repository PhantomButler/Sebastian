package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.sebastian.android.ui.common.glass.GlassState
import com.sebastian.android.ui.common.glass.GlassSurface
import com.sebastian.android.ui.theme.AgentAccentDark
import com.sebastian.android.ui.theme.AgentAccentLight
import com.sebastian.android.viewmodel.AgentAnimState
import kotlinx.coroutines.delay

/**
 * UI 层胶囊动画档位，合并自 [AgentAnimState]：
 * - IDLE → COLLAPSED（只显示 Text）
 * - PENDING → BREATHING（彩虹渐变旋转光环）
 * - THINKING → THINKING（4 光团）
 * - STREAMING / WORKING → ACTIVE（Jarvis HUD）
 */
enum class AgentPillMode { COLLAPSED, BREATHING, THINKING, ACTIVE }

fun AgentAnimState.toPillMode(): AgentPillMode = when (this) {
    AgentAnimState.IDLE -> AgentPillMode.COLLAPSED
    AgentAnimState.PENDING -> AgentPillMode.BREATHING
    AgentAnimState.THINKING -> AgentPillMode.THINKING
    AgentAnimState.STREAMING, AgentAnimState.WORKING -> AgentPillMode.ACTIVE
}

// ═══════════════════════════════════════════════════════════════
// AgentPill 胶囊壳
// ═══════════════════════════════════════════════════════════════

/**
 * ChatScreen 顶部 agent 名称胶囊。
 *
 * 根据 [agentAnimState] 切换三档显示：
 * - COLLAPSED（IDLE）：只显 Text
 * - THINKING：尾部 4 光团漂移
 * - ACTIVE（STREAMING / WORKING）：尾部 Jarvis 同心 HUD
 *
 * 展开用 spring animateContentSize，THINKING↔ACTIVE 用 AnimatedContent
 * crossfade，额外加 80ms 驻留防抖避免瞬时状态闪烁。
 */
@Composable
fun AgentPill(
    agentName: String?,
    agentAnimState: AgentAnimState,
    glassState: GlassState,
    modifier: Modifier = Modifier,
) {
    val displayName = agentName ?: "Sebastian"
    val isDark = isSystemInDarkTheme()
    val accent = if (isDark) AgentAccentDark else AgentAccentLight
    val glowScale = if (isDark) 1f else 0.7f

    val targetMode = agentAnimState.toPillMode()
    val stableMode by produceState(
        initialValue = AgentPillMode.COLLAPSED,
        key1 = targetMode,
    ) {
        delay(80L)
        value = targetMode
    }

    val stateLabel = when (stableMode) {
        AgentPillMode.COLLAPSED -> null
        AgentPillMode.BREATHING -> "等待响应"
        AgentPillMode.THINKING -> "正在思考"
        AgentPillMode.ACTIVE -> "正在响应"
    }

    GlassSurface(
        state = glassState,
        shape = CircleShape,
        shadowCornerRadius = 100.dp,
        modifier = modifier.semantics {
            contentDescription = displayName
            if (stateLabel != null) stateDescription = stateLabel
        },
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .animateContentSize(
                    animationSpec = spring(dampingRatio = 0.7f, stiffness = 400f),
                )
                .padding(horizontal = 16.dp, vertical = 10.dp),
        ) {
            Text(
                text = displayName,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            AnimatedVisibility(
                visible = stableMode != AgentPillMode.COLLAPSED,
                enter = expandHorizontally() + fadeIn(tween(200)),
                exit = shrinkHorizontally() + fadeOut(tween(200)),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Spacer(Modifier.width(8.dp))
                    AnimatedContent(
                        targetState = stableMode,
                        transitionSpec = {
                            fadeIn(tween(200)) togetherWith fadeOut(tween(200))
                        },
                        label = "agentPillTail",
                    ) { mode ->
                        when (mode) {
                            AgentPillMode.BREATHING -> BreathingHalo(
                                glowAlphaScale = glowScale,
                            )
                            AgentPillMode.THINKING -> OrbsAnimation(
                                accent = accent,
                                glowAlphaScale = glowScale,
                            )
                            AgentPillMode.ACTIVE -> HudAnimation(
                                accent = accent,
                                glowAlphaScale = glowScale,
                            )
                            AgentPillMode.COLLAPSED -> Spacer(Modifier.size(0.dp))
                        }
                    }
                }
            }
        }
    }
}
