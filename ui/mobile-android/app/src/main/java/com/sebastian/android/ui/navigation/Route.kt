package com.sebastian.android.ui.navigation

import kotlinx.serialization.Serializable

@Serializable
sealed class Route {
    @Serializable
    data object Chat : Route()

    @Serializable
    data object SubAgents : Route()

    @Serializable
    data class AgentSessions(val agentId: String) : Route()

    @Serializable
    data class SessionDetail(val sessionId: String) : Route()

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
