package com.sebastian.android.ui.navigation

import kotlinx.serialization.Serializable

@Serializable
sealed class Route {
    @Serializable
    data class Chat(val sessionId: String? = null) : Route()

    @Serializable
    data object SubAgents : Route()

    @Serializable
    data class AgentChat(val agentId: String, val agentName: String, val sessionId: String? = null) : Route()

    @Serializable
    data object Settings : Route()

    @Serializable
    data object SettingsConnection : Route()

    @Serializable
    data object SettingsProviders : Route()

    @Serializable
    data object SettingsProvidersNew : Route()

    @Serializable
    data class SettingsProvidersEdit(val providerId: String) : Route()

    @Serializable
    data object SettingsAppearance : Route()

    @Serializable
    data object SettingsDebugLogging : Route()
}
