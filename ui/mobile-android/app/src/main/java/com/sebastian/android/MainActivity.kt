package com.sebastian.android

import android.graphics.drawable.ColorDrawable
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.graphics.toArgb
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.ui.chat.ChatScreen
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.ui.settings.AppearancePage
import com.sebastian.android.ui.settings.DebugLoggingPage
import com.sebastian.android.ui.settings.ProviderFormPage
import com.sebastian.android.ui.settings.ProviderListPage
import com.sebastian.android.ui.settings.ConnectionPage
import com.sebastian.android.ui.settings.SettingsScreen
import com.sebastian.android.ui.subagents.AgentListScreen
import com.sebastian.android.ui.theme.SebastianTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject lateinit var settingsDataStore: SettingsDataStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val themeMode by settingsDataStore.theme.collectAsState(initial = "system")
            SebastianTheme(themeMode = themeMode) {
                // Sync window background with Compose surface to prevent flash on navigation
                val surfaceColor = MaterialTheme.colorScheme.surface
                SideEffect {
                    window.setBackgroundDrawable(ColorDrawable(surfaceColor.toArgb()))
                }
                SebastianNavHost()
            }
        }
    }
}

@Composable
fun SebastianNavHost() {
    val navController = rememberNavController()
    val animDuration = 300
    NavHost(
        navController = navController,
        startDestination = Route.Chat,
        enterTransition = {
            slideIntoContainer(AnimatedContentTransitionScope.SlideDirection.Left, tween(animDuration)) +
                fadeIn(tween(animDuration))
        },
        exitTransition = {
            slideOutOfContainer(AnimatedContentTransitionScope.SlideDirection.Left, tween(animDuration)) +
                fadeOut(tween(animDuration))
        },
        popEnterTransition = {
            slideIntoContainer(AnimatedContentTransitionScope.SlideDirection.Right, tween(animDuration)) +
                fadeIn(tween(animDuration))
        },
        popExitTransition = {
            slideOutOfContainer(AnimatedContentTransitionScope.SlideDirection.Right, tween(animDuration)) +
                fadeOut(tween(animDuration))
        },
    ) {
        composable<Route.Chat> {
            ChatScreen(navController = navController)
        }
        composable<Route.SubAgents> {
            AgentListScreen(navController = navController)
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
        composable<Route.SettingsAppearance> {
            AppearancePage(navController = navController)
        }
        composable<Route.SettingsDebugLogging> {
            DebugLoggingPage(navController = navController)
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
