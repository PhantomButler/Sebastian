package com.sebastian.android.data.model

data class Provider(
    val id: String,
    val name: String,
    val type: String,         // "anthropic" | "openai" | "ollama"
    val baseUrl: String?,
    val model: String? = null,
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

enum class ThinkingEffort {
    OFF, ON, LOW, MEDIUM, HIGH, MAX;

    companion object {
        fun fromString(value: String?): ThinkingEffort = when (value) {
            "off" -> OFF
            "on" -> ON
            "low" -> LOW
            "medium" -> MEDIUM
            "high" -> HIGH
            "max" -> MAX
            else -> OFF
        }
    }
}
