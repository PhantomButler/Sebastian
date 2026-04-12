package com.sebastian.android.data.model

data class Session(
    val id: String,
    val title: String,
    val agentType: String,
    val lastMessageAt: String?,
    val isActive: Boolean,
)
