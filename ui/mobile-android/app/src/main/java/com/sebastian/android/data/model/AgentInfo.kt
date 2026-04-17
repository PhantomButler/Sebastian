package com.sebastian.android.data.model

data class AgentInfo(
    val agentType: String,
    val displayName: String,
    val description: String,
    val isOrchestrator: Boolean = false,
    val boundProviderId: String? = null,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
    val activeSessionCount: Int = 0,
    val maxChildren: Int = 0,
) {
    val isActive: Boolean get() = activeSessionCount > 0
}
