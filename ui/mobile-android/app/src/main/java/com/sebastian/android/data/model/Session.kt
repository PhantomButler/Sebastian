package com.sebastian.android.data.model

data class Session(
    val id: String,
    val title: String,
    val agentType: String,
    val status: String = "active",
    val lastActivityAt: String? = null,
    val updatedAt: String? = null,
) {
    val isActive: Boolean get() = status == "active"
}
