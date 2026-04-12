package com.sebastian.android.data.model

data class Provider(
    val id: String,
    val name: String,
    val type: String,         // "anthropic" | "openai" | "ollama"
    val baseUrl: String?,
    val isDefault: Boolean,
    val thinkingCapability: ThinkingCapability,
)

enum class ThinkingCapability {
    NONE, ALWAYS_ON, TOGGLE, EFFORT, ADAPTIVE;

    companion object {
        fun fromString(value: String?): ThinkingCapability = when (value) {
            "none" -> NONE
            "always_on" -> ALWAYS_ON
            "toggle" -> TOGGLE
            "effort" -> EFFORT
            "adaptive" -> ADAPTIVE
            else -> NONE
        }
    }
}

enum class ThinkingEffort { LOW, MEDIUM, HIGH, AUTO }
