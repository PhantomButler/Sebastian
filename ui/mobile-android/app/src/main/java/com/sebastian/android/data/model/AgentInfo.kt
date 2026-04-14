package com.sebastian.android.data.model

data class AgentInfo(
    val agentType: String,
    val name: String,
    val description: String,
    val activeSessionCount: Int = 0,
    val maxChildren: Int = 0,
) {
    val isActive: Boolean get() = activeSessionCount > 0
}
