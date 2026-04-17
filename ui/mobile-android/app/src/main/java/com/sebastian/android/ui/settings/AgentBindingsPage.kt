package com.sebastian.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.displayLabel
import com.sebastian.android.ui.common.ToastCenter
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.AgentBindingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentBindingsPage(
    navController: NavController,
    viewModel: AgentBindingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val context = LocalContext.current
    LaunchedEffect(Unit) { viewModel.load() }
    LaunchedEffect(state.errorMessage) {
        val msg = state.errorMessage ?: return@LaunchedEffect
        ToastCenter.show(
            context,
            msg.ifBlank { "Failed to load agent bindings." },
            key = "agent-bindings-load-error",
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Agent LLM Bindings") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        val (orchestrator, subAgents) = state.agents.partition { it.isOrchestrator }
        val defaultProvider = state.providers.firstOrNull { it.isDefault }

        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding)) {
            if (orchestrator.isNotEmpty()) {
                item { SectionHeader("Orchestrator") }
                items(orchestrator, key = { it.agentType }) { agent ->
                    AgentRow(
                        agent = agent,
                        providers = state.providers,
                        defaultProviderName = defaultProvider?.name,
                        icon = Icons.Outlined.AutoAwesome,
                        onClick = {
                            navController.navigate(Route.SettingsAgentBindingEditor(agent.agentType))
                        },
                    )
                }
            }
            if (subAgents.isNotEmpty()) {
                item { SectionHeader("Sub-Agents") }
                items(subAgents, key = { it.agentType }) { agent ->
                    AgentRow(
                        agent = agent,
                        providers = state.providers,
                        defaultProviderName = defaultProvider?.name,
                        icon = Icons.Outlined.Extension,
                        onClick = {
                            navController.navigate(Route.SettingsAgentBindingEditor(agent.agentType))
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 4.dp),
    )
}

@Composable
private fun AgentRow(
    agent: AgentInfo,
    providers: List<com.sebastian.android.data.model.Provider>,
    defaultProviderName: String?,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
) {
    val bound = providers.firstOrNull { it.id == agent.boundProviderId }
    val subtitle = if (bound != null) {
        buildString {
            append(bound.name)
            if (agent.thinkingEffort != ThinkingEffort.OFF) {
                append(" · ")
                append(agent.thinkingEffort.displayLabel())
            }
        }
    } else {
        "Use default · ${defaultProviderName ?: "—"}"
    }

    ElevatedCard(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp)
            .clickable { onClick() },
    ) {
        ListItem(
            leadingContent = { Icon(icon, contentDescription = null) },
            headlineContent = { Text(agent.displayName) },
            supportingContent = { Text(subtitle) },
        )
    }
}
