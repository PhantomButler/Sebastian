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
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.zIndex
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.ui.chat.ChatScreen
import com.sebastian.android.ui.common.GlobalApprovalBanner
import com.sebastian.android.ui.common.glass.rememberGlassState
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.ui.settings.AppearancePage
import com.sebastian.android.ui.settings.DebugLoggingPage
import com.sebastian.android.ui.settings.ProviderFormPage
import com.sebastian.android.ui.settings.ProviderListPage
import com.sebastian.android.ui.settings.ConnectionPage
import com.sebastian.android.ui.settings.SettingsScreen
import com.sebastian.android.ui.subagents.AgentListScreen
import com.sebastian.android.ui.theme.SebastianTheme
import com.sebastian.android.viewmodel.GlobalApprovalViewModel
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
    val globalApprovalViewModel: GlobalApprovalViewModel = hiltViewModel()
    val approvalState by globalApprovalViewModel.uiState.collectAsState()
    val animDuration = 300

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> globalApprovalViewModel.onAppStart()
                Lifecycle.Event.ON_STOP -> globalApprovalViewModel.onAppStop()
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    val glassState = rememberGlassState(MaterialTheme.colorScheme.background)

    Box(modifier = Modifier.fillMaxSize()) {
        NavHost(
            navController = navController,
            startDestination = Route.Chat(),
            modifier = Modifier.fillMaxSize().then(glassState.contentModifier),
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
            composable<Route.Chat> { backStackEntry ->
                val route = backStackEntry.toRoute<Route.Chat>()
                ChatScreen(navController = navController, sessionId = route.sessionId)
            }
            composable<Route.SubAgents> {
                AgentListScreen(navController = navController)
            }
            composable<Route.AgentChat> { backStackEntry ->
                val route = backStackEntry.toRoute<Route.AgentChat>()
                ChatScreen(
                    navController = navController,
                    agentId = route.agentId,
                    agentName = route.agentName,
                    sessionId = route.sessionId,
                )
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

        // Global approval banner — floats above all screens
        GlobalApprovalBanner(
            approval = approvalState.approvals.firstOrNull(),
            glassState = glassState,
            onGrant = globalApprovalViewModel::grantApproval,
            onDeny = globalApprovalViewModel::denyApproval,
            onNavigateToSession = { approval ->
                // 已在目标 session → 不跳转
                val alreadyInSession = try {
                    if (approval.agentType == "sebastian") {
                        navController.currentBackStackEntry
                            ?.toRoute<Route.Chat>()
                            ?.sessionId == approval.sessionId
                    } else {
                        navController.currentBackStackEntry
                            ?.toRoute<Route.AgentChat>()
                            ?.sessionId == approval.sessionId
                    }
                } catch (_: Exception) { false }
                if (alreadyInSession) return@GlobalApprovalBanner

                if (approval.agentType == "sebastian") {
                    navController.navigate(Route.Chat(sessionId = approval.sessionId)) {
                        // 弹出 Chat 之上的页面（如 Settings），保留 Chat 自身；
                        // launchSingleTop 检测到栈顶是 Chat 则复用实例（触发 LaunchedEffect 切 session），
                        // 不销毁 ViewModel，避免产生空白新对话
                        popUpTo<Route.Chat> { inclusive = false }
                        launchSingleTop = true
                    }
                } else {
                    navController.navigate(
                        Route.AgentChat(
                            agentId = approval.agentType,
                            agentName = approval.agentType,
                            sessionId = approval.sessionId,
                        )
                    ) {
                        // 弹出已有 AgentChat 之上的页面，防止不同 sessionId 导致回栈堆叠
                        popUpTo<Route.AgentChat> { inclusive = false }
                        launchSingleTop = true
                    }
                }
            },
            modifier = Modifier
                .align(Alignment.TopCenter)
                .zIndex(1f),
        )
    }
}
