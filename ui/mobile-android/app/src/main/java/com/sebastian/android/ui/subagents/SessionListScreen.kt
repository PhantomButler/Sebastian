// com/sebastian/android/ui/subagents/SessionListScreen.kt
package com.sebastian.android.ui.subagents

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.SubAgentViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionListScreen(
    agentId: String,
    navController: NavController,
    viewModel: SubAgentViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(agentId) { viewModel.loadAgentSessions(agentId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("$agentId 会话") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = {
                // 创建新会话后导航进入
            }) {
                Icon(Icons.Default.Add, contentDescription = "新建会话")
            }
        },
    ) { innerPadding ->
        when {
            state.isLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            state.agentSessions.isEmpty() -> Box(Modifier.fillMaxSize().padding(innerPadding), contentAlignment = Alignment.Center) {
                Text("还没有会话，点击 + 新建")
            }
            else -> LazyColumn(modifier = Modifier.padding(innerPadding)) {
                items(state.agentSessions, key = { it.id }) { session ->
                    ListItem(
                        headlineContent = {
                            Text(session.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        },
                        supportingContent = session.lastActivityAt?.let { { Text(it.take(16)) } },
                        modifier = Modifier.clickable {
                            navController.navigate(Route.SessionDetail(session.id)) { launchSingleTop = true }
                        },
                    )
                }
            }
        }
    }
}
