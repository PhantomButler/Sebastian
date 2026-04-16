// com/sebastian/android/ui/subagents/AgentListScreen.kt
package com.sebastian.android.ui.subagents

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.PullToRefreshDefaults
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.SubAgentViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentListScreen(
    navController: NavController,
    viewModel: SubAgentViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(Unit) { viewModel.loadAgents() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Sub-Agents") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        }
    ) { innerPadding ->
        when {
            state.agents.isEmpty() && state.isLoading -> Box(
                Modifier.fillMaxSize().padding(innerPadding),
                contentAlignment = Alignment.Center,
            ) { CircularProgressIndicator() }
            state.agents.isEmpty() -> Box(
                Modifier.fillMaxSize().padding(innerPadding),
                contentAlignment = Alignment.Center,
            ) { Text("没有可用的 Sub-Agent") }
            else -> {
                val refreshState = rememberPullToRefreshState()
                PullToRefreshBox(
                    isRefreshing = state.isLoading,
                    onRefresh = { viewModel.refresh() },
                    state = refreshState,
                    modifier = Modifier.fillMaxSize().padding(innerPadding),
                    indicator = {
                        PullToRefreshDefaults.Indicator(
                            modifier = Modifier.align(Alignment.TopCenter),
                            isRefreshing = state.isLoading,
                            state = refreshState,
                            containerColor = MaterialTheme.colorScheme.surface,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    },
                ) {
                LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(state.agents, key = { it.agentType }) { agent ->
                        ListItem(
                            headlineContent = { Text(agent.displayName) },
                            supportingContent = { Text(agent.description) },
                            modifier = Modifier.clickable {
                                navController.navigate(Route.AgentChat(agentId = agent.agentType, agentName = agent.displayName)) { launchSingleTop = true }
                            },
                        )
                    }
                }
                }
            }
        }
    }
}
