package com.sebastian.android.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.Provider
import com.sebastian.android.ui.common.SebastianIcons
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.SettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProviderListPage(
    navController: NavController,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    var deleteTarget by remember { mutableStateOf<Provider?>(null) }

    LaunchedEffect(uiState.error) {
        uiState.error?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearError()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("模型与 Provider") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { innerPadding ->
        when {
            uiState.isLoading && uiState.providers.isEmpty() -> {
                Box(
                    Modifier
                        .fillMaxSize()
                        .padding(innerPadding),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
            }
            uiState.providers.isEmpty() -> {
                Box(
                    Modifier
                        .fillMaxSize()
                        .padding(innerPadding)
                        .padding(horizontal = 16.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Surface(
                        shape = RoundedCornerShape(14.dp),
                        color = MaterialTheme.colorScheme.surfaceContainerLow,
                    ) {
                        Column(modifier = Modifier.padding(18.dp)) {
                            Text(
                                "尚未配置模型 Provider",
                                fontSize = 18.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                "添加至少一个 Provider 后，Sebastian 才能正常发起对话。",
                                fontSize = 14.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(top = 8.dp),
                            )
                            Spacer(Modifier.height(16.dp))
                            Surface(
                                onClick = {
                                    navController.navigate(Route.SettingsProvidersNew) { launchSingleTop = true }
                                },
                                shape = RoundedCornerShape(12.dp),
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(46.dp),
                            ) {
                                Box(contentAlignment = Alignment.Center) {
                                    Text(
                                        "添加 Provider",
                                        fontSize = 17.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = MaterialTheme.colorScheme.onPrimary,
                                    )
                                }
                            }
                        }
                    }
                }
            }
            else -> {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(innerPadding)
                        .padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    item {
                        Text(
                            "管理默认模型与各 Provider 配置。左滑可删除。",
                            fontSize = 14.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(bottom = 4.dp),
                        )
                    }

                    items(
                        items = uiState.providers,
                        key = { it.id },
                    ) { provider ->
                        SwipeToDeleteProviderCard(
                            provider = provider,
                            onClick = {
                                navController.navigate(Route.SettingsProvidersEdit(provider.id)) {
                                    launchSingleTop = true
                                }
                            },
                            onDelete = { deleteTarget = provider },
                        )
                    }

                    // "+ 添加 Provider" 按钮
                    item {
                        Surface(
                            onClick = {
                                navController.navigate(Route.SettingsProvidersNew) { launchSingleTop = true }
                            },
                            shape = RoundedCornerShape(14.dp),
                            color = MaterialTheme.colorScheme.surfaceContainerLow,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(48.dp),
                        ) {
                            Box(contentAlignment = Alignment.Center) {
                                Text(
                                    "+ 添加 Provider",
                                    fontSize = 17.sp,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }

                    item { Spacer(Modifier.height(16.dp)) }
                }
            }
        }
    }

    // 删除确认弹窗
    deleteTarget?.let { provider ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("删除 Provider") },
            text = { Text("确认删除 \"${provider.name}\"？") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.deleteProvider(provider.id)
                    deleteTarget = null
                }) {
                    Text("删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) {
                    Text("取消")
                }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SwipeToDeleteProviderCard(
    provider: Provider,
    onClick: () -> Unit,
    onDelete: () -> Unit,
) {
    val dismissState = rememberSwipeToDismissBoxState(
        confirmValueChange = { value ->
            if (value == SwipeToDismissBoxValue.EndToStart) {
                onDelete()
                false // 不真正 dismiss，让弹窗确认后再删
            } else {
                false // 禁止右滑
            }
        },
    )

    SwipeToDismissBox(
        state = dismissState,
        enableDismissFromStartToEnd = false, // 禁止右滑
        backgroundContent = {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clip(RoundedCornerShape(14.dp))
                    .background(MaterialTheme.colorScheme.error)
                    .padding(end = 24.dp),
                contentAlignment = Alignment.CenterEnd,
            ) {
                Icon(
                    imageVector = SebastianIcons.Delete,
                    contentDescription = "删除",
                    tint = MaterialTheme.colorScheme.onError,
                )
            }
        },
    ) {
        ProviderCard(provider = provider, onClick = onClick)
    }
}

@Composable
private fun ProviderCard(
    provider: Provider,
    onClick: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surfaceContainerLow,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            Text(
                text = buildString {
                    append(provider.name)
                    if (provider.isDefault) append(" ★")
                },
                fontSize = 17.sp,
                fontWeight = FontWeight.Medium,
            )
            Text(
                text = buildString {
                    append(provider.type)
                    if (!provider.model.isNullOrBlank()) {
                        append(" · ")
                        append(provider.model)
                    }
                },
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}
