package com.sebastian.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.sebastian.android.ui.chat.ChatScreen
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.ui.settings.ProviderFormPage
import com.sebastian.android.ui.settings.ProviderListPage
import com.sebastian.android.ui.settings.ConnectionPage
import com.sebastian.android.ui.settings.SettingsScreen
import com.sebastian.android.ui.subagents.AgentListScreen
import com.sebastian.android.ui.subagents.SessionDetailScreen
import com.sebastian.android.ui.subagents.SessionListScreen
import com.sebastian.android.ui.theme.SebastianTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SebastianTheme {
                SebastianNavHost()
            }
        }
    }
}

@Composable
fun SebastianNavHost() {
    val navController = rememberNavController()
    NavHost(navController = navController, startDestination = Route.Chat) {
        composable<Route.Chat> {
            ChatScreen(navController = navController)
        }
        composable<Route.SubAgents> {
            AgentListScreen(navController = navController)
        }
        composable<Route.AgentSessions> { backStackEntry ->
            val route = backStackEntry.toRoute<Route.AgentSessions>()
            SessionListScreen(agentId = route.agentId, navController = navController)
        }
        composable<Route.SessionDetail> { backStackEntry ->
            val route = backStackEntry.toRoute<Route.SessionDetail>()
            SessionDetailScreen(sessionId = route.sessionId, navController = navController)
        }
        composable<Route.Settings> {
            SettingsScreen(navController = navController)
        }
        composable<Route.SettingsConnection> {
            ConnectionPage(navController = navController)
        }
        composable<Route.SettingsProviders> {
            ProviderListPage(navController = navController)
        }
        composable<Route.SettingsProvidersNew> {
            ProviderFormPage(navController = navController, providerId = null)
        }
        composable<Route.SettingsProvidersEdit> { backStackEntry ->
            val route = backStackEntry.toRoute<Route.SettingsProvidersEdit>()
            ProviderFormPage(navController = navController, providerId = route.providerId)
        }
    }
}
