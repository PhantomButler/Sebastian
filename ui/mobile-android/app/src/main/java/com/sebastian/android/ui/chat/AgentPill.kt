package com.sebastian.android.ui.chat

import com.sebastian.android.viewmodel.AgentAnimState

/**
 * UI 层胶囊动画档位，合并自 [AgentAnimState]：
 * - IDLE → COLLAPSED（只显示 Text）
 * - THINKING → THINKING（4 光团）
 * - STREAMING / WORKING → ACTIVE（Jarvis HUD）
 */
enum class AgentPillMode { COLLAPSED, THINKING, ACTIVE }

fun AgentAnimState.toPillMode(): AgentPillMode = when (this) {
    AgentAnimState.IDLE -> AgentPillMode.COLLAPSED
    AgentAnimState.THINKING -> AgentPillMode.THINKING
    AgentAnimState.STREAMING, AgentAnimState.WORKING -> AgentPillMode.ACTIVE
}
