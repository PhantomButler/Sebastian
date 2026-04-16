package com.sebastian.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.ui.common.ToastCenter
import com.sebastian.android.viewmodel.AgentBindingsEvent
import com.sebastian.android.viewmodel.AgentBindingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentBindingsPage(
    navController: NavController,
    viewModel: AgentBindingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val context = LocalContext.current

    var pickerAgent by remember { mutableStateOf<AgentInfo?>(null) }

    LaunchedEffect(Unit) { viewModel.load() }

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                AgentBindingsEvent.BindingUpdated -> {
                    ToastCenter.show(
                        context,
                        "Binding will take effect on next message.",
                        key = "agent-binding-updated",
                    )
                }
                is AgentBindingsEvent.Error -> {
                    ToastCenter.show(
                        context,
                        event.message.ifBlank { "Failed to update binding." },
                        key = "agent-binding-error",
                    )
                }
            }
        }
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
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            Text(
                text = "Select a provider for each agent, or use the global default.",
                modifier = Modifier.padding(16.dp),
                style = MaterialTheme.typography.bodyMedium,
            )
            HorizontalDivider()
            LazyColumn(modifier = Modifier.fillMaxSize()) {
                items(state.agents, key = { it.agentType }) { agent ->
                    val boundProvider = state.providers.firstOrNull { it.id == agent.boundProviderId }
                    ListItem(
                        headlineContent = { Text(agent.displayName) },
                        supportingContent = {
                            Column {
                                Text(agent.description)
                                Text(
                                    text = "Provider: " + (boundProvider?.name ?: "Use Default"),
                                    style = MaterialTheme.typography.labelMedium,
                                )
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { pickerAgent = agent },
                    )
                    HorizontalDivider()
                }
            }
        }
    }

    val sheetState = rememberModalBottomSheetState()
    pickerAgent?.let { agent ->
        ModalBottomSheet(
            onDismissRequest = { pickerAgent = null },
            sheetState = sheetState,
        ) {
            ProviderPickerContent(
                currentProviderId = agent.boundProviderId,
                providers = state.providers,
                onUseDefault = {
                    viewModel.useDefault(agent.agentType)
                    pickerAgent = null
                },
                onSelect = { providerId ->
                    viewModel.bind(agent.agentType, providerId)
                    pickerAgent = null
                },
            )
        }
    }
}

@Composable
private fun ProviderPickerContent(
    currentProviderId: String?,
    providers: List<Provider>,
    onUseDefault: () -> Unit,
    onSelect: (String) -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        ListItem(
            headlineContent = { Text("Use Default") },
            supportingContent = { Text("Follow global default provider") },
            trailingContent = if (currentProviderId == null) {
                { Icon(Icons.Default.Check, contentDescription = "selected") }
            } else null,
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onUseDefault() },
        )
        HorizontalDivider()
        providers.forEach { provider ->
            ListItem(
                headlineContent = { Text(provider.name) },
                supportingContent = {
                    Text(
                        buildString {
                            append(provider.type)
                            if (!provider.model.isNullOrBlank()) {
                                append(" · ")
                                append(provider.model)
                            }
                        }
                    )
                },
                trailingContent = if (currentProviderId == provider.id) {
                    { Icon(Icons.Default.Check, contentDescription = "selected") }
                } else null,
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onSelect(provider.id) },
            )
            HorizontalDivider()
        }
    }
}
