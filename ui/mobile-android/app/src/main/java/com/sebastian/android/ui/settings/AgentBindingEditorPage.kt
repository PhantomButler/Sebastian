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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.Memory
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType

import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.ui.settings.components.EffortSlider
import com.sebastian.android.viewmodel.AgentBindingEditorViewModel
import com.sebastian.android.viewmodel.EditorEvent
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentBindingEditorPage(
    agentType: String,
    isMemoryComponent: Boolean = false,
    navController: NavController,
) {
    val vm: AgentBindingEditorViewModel =
        hiltViewModel<AgentBindingEditorViewModel, AgentBindingEditorViewModel.Factory>(
            key = "$agentType-$isMemoryComponent",
            creationCallback = { factory -> factory.create(agentType, isMemoryComponent) },
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

    val pageTitle = when {
        state.isDefault -> "默认模型"
        else -> agentType.replaceFirstChar { it.uppercase() }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(pageTitle) },
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
            AccountSelector(
                accounts = state.accounts,
                selectedAccount = state.selectedAccount,
                onSelect = vm::selectAccount,
                onClear = if (state.isDefault) null else vm::clearBinding,
            )

            Spacer(Modifier.height(16.dp))

            if (state.selectedAccount != null) {
                ModelSelector(
                    models = state.availableModels,
                    selectedModel = state.selectedModel,
                    onSelect = vm::selectModel,
                )
                Spacer(Modifier.height(8.dp))
                state.contextWindowText?.let { ctxText ->
                    Text(
                        text = "上下文窗口: $ctxText",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 16.dp),
                    )
                }
            }

            Spacer(Modifier.height(16.dp))

            when (val capability = state.effectiveCapability) {
                null -> {
                    if (state.selectedAccount == null) {
                        Text(
                            if (state.isDefault) "未配置默认模型" else "使用默认模型",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
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
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AccountSelector(
    accounts: List<com.sebastian.android.data.model.LlmAccount>,
    selectedAccount: com.sebastian.android.data.model.LlmAccount?,
    onSelect: (String?) -> Unit,
    onClear: (() -> Unit)?,
) {
    var expanded by remember { mutableStateOf(false) }

    Text(
        "LLM Account",
        style = MaterialTheme.typography.titleSmall,
        fontWeight = FontWeight.SemiBold,
    )
    Spacer(Modifier.height(8.dp))

    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = it },
    ) {
        OutlinedTextField(
            value = selectedAccount?.name ?: "使用默认模型",
            onValueChange = {},
            readOnly = true,
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier
                .fillMaxWidth()
                .menuAnchor(MenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
        ) {
            if (selectedAccount != null && onClear != null) {
                androidx.compose.material3.DropdownMenuItem(
                    text = {
                        Column {
                            Text("使用默认模型", fontWeight = FontWeight.Medium)
                            Text(
                                "取消此 Agent 的专属绑定",
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    },
                    onClick = {
                        onClear()
                        expanded = false
                    },
                )
            }
            for (account in accounts) {
                androidx.compose.material3.DropdownMenuItem(
                    text = {
                        Column {
                            Text(account.name, fontWeight = FontWeight.Medium)
                            Text(
                                account.providerType,
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    },
                    onClick = {
                        onSelect(account.id)
                        expanded = false
                    },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ModelSelector(
    models: List<com.sebastian.android.viewmodel.ModelOption>,
    selectedModel: com.sebastian.android.viewmodel.ModelOption?,
    onSelect: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }

    Text(
        "Model",
        style = MaterialTheme.typography.titleSmall,
        fontWeight = FontWeight.SemiBold,
    )
    Spacer(Modifier.height(8.dp))

    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = it },
    ) {
        OutlinedTextField(
            value = selectedModel?.displayName ?: "Select a model",
            onValueChange = {},
            readOnly = true,
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier
                .fillMaxWidth()
                .menuAnchor(MenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
        ) {
            for (model in models) {
                val ctxLabel = if (model.contextWindowTokens >= 1_000_000) {
                    "${model.contextWindowTokens / 1_000_000}M tokens"
                } else {
                    "%,d tokens".format(model.contextWindowTokens)
                }
                androidx.compose.material3.DropdownMenuItem(
                    text = {
                        Column {
                            Text(model.displayName, fontWeight = FontWeight.Medium)
                            Text(
                                ctxLabel,
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    },
                    onClick = {
                        onSelect(model.id)
                        expanded = false
                    },
                )
            }
        }
    }
}
