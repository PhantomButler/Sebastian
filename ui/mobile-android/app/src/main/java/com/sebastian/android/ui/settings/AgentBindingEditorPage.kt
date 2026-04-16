package com.sebastian.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.Memory
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.ui.settings.components.EffortSlider
import com.sebastian.android.ui.settings.components.ProviderPickerDialog
import com.sebastian.android.viewmodel.AgentBindingEditorViewModel
import com.sebastian.android.viewmodel.EditorEvent
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentBindingEditorPage(
    agentType: String,
    navController: NavController,
) {
    val vm: AgentBindingEditorViewModel =
        hiltViewModel<AgentBindingEditorViewModel, AgentBindingEditorViewModel.Factory>(
            key = agentType,
            creationCallback = { factory -> factory.create(agentType) },
        )
    val state by vm.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) { vm.load() }
    LaunchedEffect(vm) {
        vm.events.collect { ev ->
            when (ev) {
                is EditorEvent.Snackbar -> scope.launch { snackbarHostState.showSnackbar(ev.text) }
            }
        }
    }

    var showPicker by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        state.selectedProvider?.name
                            ?: agentType.replaceFirstChar { it.uppercase() },
                    )
                },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        if (state.loading) {
            Column(
                modifier = Modifier.fillMaxSize().padding(padding),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) { CircularProgressIndicator() }
            return@Scaffold
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
        ) {
            Text("LLM Provider", style = MaterialTheme.typography.titleSmall)
            ElevatedCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 8.dp)
                    .clickable { showPicker = true },
            ) {
                ListItem(
                    leadingContent = { Icon(Icons.Outlined.Memory, contentDescription = null) },
                    headlineContent = {
                        Text(state.selectedProvider?.name ?: "Use default provider")
                    },
                    supportingContent = {
                        Text(state.selectedProvider?.type ?: "Follow global default")
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp),
                )
            }
            Spacer(Modifier.height(16.dp))

            when (val capability = state.effectiveCapability) {
                null -> {
                    Text(
                        "No default provider configured",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                ThinkingCapability.NONE -> Unit
                ThinkingCapability.ALWAYS_ON -> {
                    ListItem(
                        headlineContent = {
                            Text("Thinking: Always on (controlled by model)")
                        },
                    )
                }
                else -> {
                    Text("Thinking Depth", style = MaterialTheme.typography.titleSmall)
                    EffortSlider(
                        capability = capability,
                        value = state.thinkingEffort,
                        onValueChange = vm::setEffort,
                    )
                }
            }
        }

        if (showPicker) {
            ProviderPickerDialog(
                currentProviderId = state.selectedProvider?.id,
                providers = state.providers,
                onDismiss = { showPicker = false },
                onSelect = { pid ->
                    vm.selectProvider(pid)
                    showPicker = false
                },
            )
        }
    }
}
