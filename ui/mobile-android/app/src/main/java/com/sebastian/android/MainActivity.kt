package com.sebastian.android

import android.content.Intent
import android.graphics.drawable.ColorDrawable
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.zIndex
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.data.remote.ConnectionState
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.data.sync.AppStateReconciler
import kotlinx.coroutines.launch
import com.sebastian.android.ui.chat.ChatScreen
import com.sebastian.android.ui.common.GlobalApprovalBanner
import com.sebastian.android.ui.common.ToastCenter
import com.sebastian.android.ui.common.glass.rememberGlassState
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.ui.settings.AgentBindingEditorPage
import com.sebastian.android.ui.settings.AgentBindingsPage
import com.sebastian.android.ui.settings.AppearancePage
import com.sebastian.android.ui.settings.DebugLoggingPage
import com.sebastian.android.ui.settings.MemorySettingsPage
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
    @Inject lateinit var sseDispatcher: GlobalSseDispatcher
    @Inject lateinit var stateReconciler: AppStateReconciler

    private val requestNotificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {
            // 拒绝时不做处理；Settings 页提供重新打开入口
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        maybeRequestNotificationPermission()
        enableEdgeToEdge()
        setContent {
            val themeMode by settingsDataStore.theme.collectAsState(initial = "system")
            SebastianTheme(themeMode = themeMode) {
                // Sync window background with Compose surface to prevent flash on navigation
                val surfaceColor = MaterialTheme.colorScheme.surface
                SideEffect {
                    window.setBackgroundDrawable(ColorDrawable(surfaceColor.toArgb()))
                }
                val startSessionId = remember {
                    intent?.data?.takeIf { it.scheme == "sebastian" && it.host == "session" }
                        ?.pathSegments?.firstOrNull()
                }
                SebastianNavHost(
                    sseDispatcher = sseDispatcher,
                    stateReconciler = stateReconciler,
                    startSessionId = startSessionId,
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        // singleTask 模式下通知点击会走这里；最简方案：recreate 让 Compose 重新读 intent.data
        recreate()
    }

    private fun maybeRequestNotificationPermission() {
        if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.TIRAMISU) return
        val perm = android.Manifest.permission.POST_NOTIFICATIONS
        if (checkSelfPermission(perm) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestNotificationPermission.launch(perm)
        }
    }
}

@Composable
fun SebastianNavHost(
    sseDispatcher: GlobalSseDispatcher,
    stateReconciler: AppStateReconciler,
    startSessionId: String? = null,
) {
    val navController = rememberNavController()
    // Deep link: 若外部带 sebastian://session/{id} 进入，首次组合后切到对应 Chat
    androidx.compose.runtime.LaunchedEffect(startSessionId) {
        if (!startSessionId.isNullOrBlank()) {
            navController.navigate(Route.Chat(sessionId = startSessionId)) {
                popUpTo<Route.Chat> { inclusive = false }
                launchSingleTop = true
            }
        }
    }
    val globalApprovalViewModel: GlobalApprovalViewModel = hiltViewModel()
    val approvalState by globalApprovalViewModel.uiState.collectAsState()
    val animDuration = 300
    val context = LocalContext.current
    // 记录当前真实显示的 session（ChatScreen 通过回调实时上报，含面板手动切换）
    var currentViewingSessionId by remember { mutableStateOf<String?>(null) }

    // Attach reconciler 到 globalApprovalViewModel（chat 消息 reconcile 留作后续 task）
    DisposableEffect(Unit) {
        val scope = kotlinx.coroutines.CoroutineScope(
            kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main.immediate
        )
        stateReconciler.attach(
            scope = scope,
            approvalViewModelProvider = { globalApprovalViewModel },
        )
        onDispose { scope.coroutineContext[kotlinx.coroutines.Job]?.cancel() }
    }

    // 进程级生命周期：ON_START 启动 SSE + reconcile；ON_STOP 停止 SSE；Connected 时 reconcile
    DisposableEffect(Unit) {
        val owner = ProcessLifecycleOwner.get()
        val scope = kotlinx.coroutines.CoroutineScope(
            kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main.immediate
        )
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> {
                    sseDispatcher.start(scope)
                    stateReconciler.reconcile()
                }
                Lifecycle.Event.ON_STOP -> sseDispatcher.stop()
                else -> Unit
            }
        }
        owner.lifecycle.addObserver(observer)
        val connectionJob = scope.launch {
            sseDispatcher.connectionState.collect { state ->
                if (state == ConnectionState.Connected) stateReconciler.reconcile()
            }
        }
        onDispose {
            owner.lifecycle.removeObserver(observer)
            connectionJob.cancel()
            scope.coroutineContext[kotlinx.coroutines.Job]?.cancel()
        }
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
                ChatScreen(
                    navController = navController,
                    sessionId = route.sessionId,
                    onActiveSessionChanged = { currentViewingSessionId = it },
                )
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
                    onActiveSessionChanged = { currentViewingSessionId = it },
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
            composable<Route.SettingsMemory> {
                MemorySettingsPage(navController = navController)
            }
            composable<Route.SettingsProvidersNew> {
                ProviderFormPage(navController = navController, providerId = null)
            }
            composable<Route.SettingsProvidersEdit> { backStackEntry ->
                val route = backStackEntry.toRoute<Route.SettingsProvidersEdit>()
                ProviderFormPage(navController = navController, providerId = route.providerId)
            }
            composable<Route.SettingsAgentBindings> {
                AgentBindingsPage(navController = navController)
            }
            composable<Route.SettingsAgentBindingEditor> { backStackEntry ->
                val route = backStackEntry.toRoute<Route.SettingsAgentBindingEditor>()
                AgentBindingEditorPage(
                    agentType = route.agentType,
                    navController = navController,
                )
            }
        }

        // Global approval banner — floats above all screens
        GlobalApprovalBanner(
            approval = approvalState.approvals.firstOrNull(),
            glassState = glassState,
            onGrant = globalApprovalViewModel::grantApproval,
            onDeny = globalApprovalViewModel::denyApproval,
            onNavigateToSession = { approval ->
                // 用 ChatScreen 实时上报的 activeSessionId 做精确判断，
                // 覆盖用户通过面板手动切换 session 后 route 参数已过时的情况
                if (approval.sessionId == currentViewingSessionId) {
                    ToastCenter.show(context, "已在目标会话")
                    return@GlobalApprovalBanner
                }

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
