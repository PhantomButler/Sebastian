package com.sebastian.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.BugReport
import androidx.compose.material.icons.outlined.CloudSync
import androidx.compose.material.icons.outlined.DarkMode
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material.icons.outlined.Memory
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavController
import com.sebastian.android.ui.common.SebastianIcons
import com.sebastian.android.ui.navigation.Route

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(navController: NavController) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("设置") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        }
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            item { Spacer(Modifier.height(4.dp)) }

            item {
                SettingsGroupCard {
                    SettingsRow(
                        icon = Icons.Outlined.CloudSync,
                        title = "连接与账户",
                        subtitle = "服务器地址、登录状态",
                        onClick = { navController.navigate(Route.SettingsConnection) { launchSingleTop = true } },
                    )
                    SettingsRow(
                        icon = Icons.Outlined.Memory,
                        title = "模型与 Provider",
                        subtitle = "LLM Provider 管理",
                        onClick = { navController.navigate(Route.SettingsProviders) { launchSingleTop = true } },
                    )
                    SettingsRow(
                        icon = Icons.Outlined.Extension,
                        title = "Agent LLM Bindings",
                        subtitle = "为每个 Agent 选择 Provider",
                        onClick = { navController.navigate(Route.SettingsAgentBindings) { launchSingleTop = true } },
                    )
                    SettingsRow(
                        icon = Icons.Outlined.Psychology,
                        title = "记忆功能",
                        subtitle = "长期记忆开关",
                        isLast = true,
                        onClick = { navController.navigate(Route.SettingsMemory) { launchSingleTop = true } },
                    )
                }
            }

            item {
                SettingsGroupCard {
                    SettingsRow(
                        icon = Icons.Outlined.DarkMode,
                        title = "外观",
                        subtitle = "主题模式",
                        onClick = { navController.navigate(Route.SettingsAppearance) { launchSingleTop = true } },
                    )
                    SettingsRow(
                        icon = Icons.Outlined.BugReport,
                        title = "调试日志",
                        subtitle = "LLM Stream、SSE 日志开关",
                        isLast = true,
                        onClick = { navController.navigate(Route.SettingsDebugLogging) { launchSingleTop = true } },
                    )
                }
            }

            item { NotificationPermissionCard() }

            item { Spacer(Modifier.height(16.dp)) }
        }
    }
}

@Composable
private fun SettingsGroupCard(content: @Composable () -> Unit) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 2.dp,
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            content()
        }
    }
}

@Composable
private fun SettingsRow(
    icon: ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
    isLast: Boolean = false,
) {
    val verticalPadding = if (isLast) 14.dp else 12.dp
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = verticalPadding),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(22.dp),
        )
        Column(modifier = Modifier.weight(1f).padding(start = 14.dp)) {
            Text(
                title,
                fontSize = 16.sp,
                fontWeight = FontWeight.Medium,
            )
            Text(
                subtitle,
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 1.dp),
            )
        }
        Icon(
            SebastianIcons.RightArrow,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(16.dp),
        )
    }
    if (!isLast) {
        SettingsDivider()
    }
}

@Composable
private fun SettingsDivider() {
    Surface(
        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f),
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 52.dp)
            .height(0.5.dp),
    ) {}
}

@Composable
private fun NotificationPermissionCard() {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var enabled by remember(context) {
        mutableStateOf(NotificationManagerCompat.from(context).areNotificationsEnabled())
    }
    DisposableEffect(lifecycleOwner, context) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                enabled = NotificationManagerCompat.from(context).areNotificationsEnabled()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    if (enabled) return

    Surface(
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.errorContainer,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "通知权限未开启",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
                Text(
                    "开启后 Sebastian 离线时可通知审批与任务完成",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.8f),
                    modifier = Modifier.padding(top = 1.dp),
                )
            }
            TextButton(onClick = {
                val intent = android.content.Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, context.packageName)
                context.startActivity(intent)
            }) {
                Text("去设置", color = MaterialTheme.colorScheme.error)
            }
        }
    }
}
