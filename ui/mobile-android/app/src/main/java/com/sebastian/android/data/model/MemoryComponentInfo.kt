package com.sebastian.android.data.model

data class MemoryComponentInfo(
    val componentType: String,
    val displayName: String,
    val description: String,
    val boundProviderId: String? = null,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
)
