package com.sebastian.android.data.model

data class AgentInfo(
    val agentType: String,
    val description: String,
    val activeSessionCount: Int = 0,
    val maxChildren: Int = 0,
    val boundProviderId: String? = null,
) {
    val isActive: Boolean get() = activeSessionCount > 0
}

val AgentInfo.displayName: String
    get() = agentType.replaceFirstChar { it.uppercase() }
