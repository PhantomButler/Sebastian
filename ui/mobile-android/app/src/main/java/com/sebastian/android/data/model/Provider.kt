package com.sebastian.android.data.model

// ── Legacy provider model (kept until UI migration in Task 7) ──────────

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

// ── New account / catalog / binding domain models ──────────────────────

data class LlmAccount(
    val id: String,
    val name: String,
    val catalogProviderId: String,
    val providerType: String,
    val baseUrlOverride: String?,
    val hasApiKey: Boolean,
)

data class CatalogProvider(
    val id: String,
    val displayName: String,
    val providerType: String,
    val baseUrl: String,
    val models: List<CatalogModel>,
)

data class CatalogModel(
    val id: String,
    val displayName: String,
    val contextWindowTokens: Long,
    val thinkingCapability: ThinkingCapability,
    val thinkingFormat: String?,
)

data class CustomModel(
    val id: String,
    val accountId: String,
    val modelId: String,
    val displayName: String,
    val contextWindowTokens: Long,
    val thinkingCapability: ThinkingCapability,
    val thinkingFormat: String?,
)

data class ResolvedBinding(
    val accountName: String?,
    val providerDisplayName: String?,
    val modelDisplayName: String?,
    val contextWindowTokens: Long?,
    val thinkingCapability: ThinkingCapability?,
)

data class AgentBinding(
    val agentType: String,
    val accountId: String?,
    val modelId: String?,
    val thinkingEffort: String?,
    val resolved: ResolvedBinding?,
)
