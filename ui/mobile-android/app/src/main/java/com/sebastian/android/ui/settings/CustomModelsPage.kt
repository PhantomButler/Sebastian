package com.sebastian.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.CustomModel
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.ui.common.SebastianIcons
import com.sebastian.android.viewmodel.CustomModelsViewModel

private data class CapabilityOption(val value: String, val label: String, val hint: String)

private val CAPABILITY_OPTIONS = listOf(
    CapabilityOption("none", "none", "不支持思考控制"),
    CapabilityOption("toggle", "toggle", "仅开关，无档位"),
    CapabilityOption("effort", "effort", "low / medium / high"),
    CapabilityOption("adaptive", "adaptive", "含 max 档位"),
    CapabilityOption("always_on", "always_on", "固定思考"),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CustomModelsPage(
    accountId: String,
    onBack: () -> Unit,
    viewModel: CustomModelsViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    var deleteTarget by remember { mutableStateOf<CustomModel?>(null) }
    var capabilityMenuExpanded by remember { mutableStateOf(false) }

    LaunchedEffect(uiState.error) {
        uiState.error?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearError()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("自定义模型") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
        floatingActionButton = {
            if (!uiState.showForm) {
                FloatingActionButton(
                    onClick = viewModel::startNew,
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                    shape = androidx.compose.foundation.shape.CircleShape,
                ) {
                    Icon(Icons.Filled.Add, contentDescription = "添加模型")
                }
            }
        },
    ) { innerPadding ->
        if (uiState.isLoading) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            if (uiState.showForm) {
                ModelFormSection(
                    state = uiState,
                    capabilityMenuExpanded = capabilityMenuExpanded,
                    onCapabilityMenuExpand = { capabilityMenuExpanded = it },
                    onModelIdChange = viewModel::updateModelId,
                    onDisplayNameChange = viewModel::updateDisplayName,
                    onContextWindowChange = viewModel::updateContextWindow,
                    onThinkingCapabilityChange = viewModel::updateThinkingCapability,
                    onThinkingFormatChange = viewModel::updateThinkingFormat,
                    onSave = viewModel::saveModel,
                    onDismiss = viewModel::dismissForm,
                )
                Spacer(Modifier.height(8.dp))
            }

            when {
                uiState.isLoading && uiState.models.isEmpty() -> {
                    Box(
                        Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center,
                    ) {
                        CircularProgressIndicator()
                    }
                }
                uiState.models.isEmpty() && !uiState.showForm -> {
                    Box(
                        Modifier
                            .fillMaxSize()
                            .padding(horizontal = 16.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Surface(
                            shape = RoundedCornerShape(14.dp),
                            color = MaterialTheme.colorScheme.surfaceContainerLow,
                        ) {
                            Column(modifier = Modifier.padding(18.dp)) {
                                Text(
                                    "需要至少一个模型才能在绑定中选择此连接",
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.Medium,
                                )
                                Text(
                                    "点击右下角 + 添加自定义模型。",
                                    fontSize = 14.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(top = 8.dp),
                                )
                            }
                        }
                    }
                }
                else -> {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(items = uiState.models, key = { it.id }) { model ->
                            ModelCard(
                                model = model,
                                onEdit = { viewModel.startEdit(model) },
                                onDelete = { deleteTarget = model },
                            )
                        }
                        item { Spacer(Modifier.height(88.dp)) }
                    }
                }
            }
        }
    }

    deleteTarget?.let { model ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("删除模型") },
            text = { Text("确认删除 \"${model.displayName}\"（${model.modelId}）？") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.deleteModel(model.id)
                    deleteTarget = null
                }) {
                    Text("删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) { Text("取消") }
            },
        )
    }
}

@Composable
private fun ModelCard(
    model: CustomModel,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surfaceContainerLow,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = model.displayName,
                    fontSize = 17.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = model.modelId,
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 2.dp),
                )
                Row(
                    modifier = Modifier.padding(top = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Surface(
                        shape = RoundedCornerShape(6.dp),
                        color = MaterialTheme.colorScheme.secondaryContainer,
                    ) {
                        Text(
                            formatTokens(model.contextWindowTokens),
                            fontSize = 11.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                        )
                    }
                    if (model.thinkingCapability != ThinkingCapability.NONE) {
                        Surface(
                            shape = RoundedCornerShape(6.dp),
                            color = MaterialTheme.colorScheme.tertiaryContainer,
                        ) {
                            Text(
                                "思考: ${formatCapability(model.thinkingCapability)}",
                                fontSize = 11.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onTertiaryContainer,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                            )
                        }
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                IconButton(onClick = onEdit, modifier = Modifier.size(36.dp)) {
                    Icon(
                        SebastianIcons.Edit,
                        contentDescription = "编辑",
                        modifier = Modifier.size(18.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                IconButton(onClick = onDelete, modifier = Modifier.size(36.dp)) {
                    Icon(
                        SebastianIcons.Delete,
                        contentDescription = "删除",
                        modifier = Modifier.size(18.dp),
                        tint = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ModelFormSection(
    state: com.sebastian.android.viewmodel.CustomModelsUiState,
    capabilityMenuExpanded: Boolean,
    onCapabilityMenuExpand: (Boolean) -> Unit,
    onModelIdChange: (String) -> Unit,
    onDisplayNameChange: (String) -> Unit,
    onContextWindowChange: (String) -> Unit,
    onThinkingCapabilityChange: (String) -> Unit,
    onThinkingFormatChange: (String) -> Unit,
    onSave: () -> Unit,
    onDismiss: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(18.dp),
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
    ) {
        Column(modifier = Modifier.padding(18.dp)) {
            Text(
                if (state.editingModelId != null) "编辑模型" else "添加模型",
                fontSize = 17.sp,
                fontWeight = FontWeight.SemiBold,
            )

            Spacer(Modifier.height(14.dp))

            FieldLabel("Model ID")
            OutlinedTextField(
                value = state.modelId,
                onValueChange = onModelIdChange,
                placeholder = { Text("my-model-v1") },
                singleLine = true,
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth(),
            )

            FieldLabel("显示名称", topPadding = 14.dp)
            OutlinedTextField(
                value = state.displayName,
                onValueChange = onDisplayNameChange,
                placeholder = { Text("My Model V1") },
                singleLine = true,
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth(),
            )

            FieldLabel("上下文窗口（tokens）", topPadding = 14.dp)
            OutlinedTextField(
                value = state.contextWindowTokens,
                onValueChange = onContextWindowChange,
                placeholder = { Text("32,000") },
                singleLine = true,
                shape = RoundedCornerShape(14.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                supportingText = { Text("1,000 – 10,000,000") },
                modifier = Modifier.fillMaxWidth(),
            )

            FieldLabel("思考能力", topPadding = 14.dp)
            val currentOption = CAPABILITY_OPTIONS.first { it.value == state.thinkingCapability }
            ExposedDropdownMenuBox(
                expanded = capabilityMenuExpanded,
                onExpandedChange = onCapabilityMenuExpand,
            ) {
                OutlinedTextField(
                    value = currentOption.label,
                    onValueChange = {},
                    readOnly = true,
                    singleLine = true,
                    shape = RoundedCornerShape(14.dp),
                    supportingText = { Text(currentOption.hint) },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = capabilityMenuExpanded) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .menuAnchor(type = MenuAnchorType.PrimaryNotEditable),
                )
                ExposedDropdownMenu(
                    expanded = capabilityMenuExpanded,
                    onDismissRequest = { onCapabilityMenuExpand(false) },
                ) {
                    CAPABILITY_OPTIONS.forEach { option ->
                        DropdownMenuItem(
                            text = {
                                Column {
                                    Text(option.label, fontWeight = FontWeight.Medium)
                                    Text(
                                        option.hint,
                                        fontSize = 12.sp,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            },
                            onClick = {
                                onThinkingCapabilityChange(option.value)
                                onCapabilityMenuExpand(false)
                            },
                        )
                    }
                }
            }

            if (state.thinkingCapability != "none") {
                FieldLabel("Thinking Format（可选）", topPadding = 14.dp)
                OutlinedTextField(
                    value = state.thinkingFormat,
                    onValueChange = onThinkingFormatChange,
                    placeholder = { Text("Leave empty for default") },
                    singleLine = true,
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Spacer(Modifier.height(18.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                TextButton(
                    onClick = onDismiss,
                    modifier = Modifier.weight(1f),
                ) { Text("取消") }
                Surface(
                    onClick = onSave,
                    shape = RoundedCornerShape(14.dp),
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.weight(1f),
                ) {
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier.height(44.dp),
                    ) {
                        if (state.isSaving) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(18.dp),
                                strokeWidth = 2.dp,
                                color = MaterialTheme.colorScheme.onPrimary,
                            )
                        } else {
                            Text(
                                if (state.editingModelId != null) "更新" else "添加",
                                fontSize = 15.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onPrimary,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FieldLabel(text: String, topPadding: androidx.compose.ui.unit.Dp = 0.dp) {
    Text(
        text,
        fontSize = 13.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = topPadding, bottom = 8.dp),
    )
}

private fun formatTokens(tokens: Long): String = when {
    tokens >= 1_000_000 -> "${tokens / 1_000_000}M tokens"
    tokens >= 1_000 -> "${tokens / 1_000}K tokens"
    else -> "$tokens tokens"
}

private fun formatCapability(capability: ThinkingCapability): String = when (capability) {
    ThinkingCapability.NONE -> "none"
    ThinkingCapability.TOGGLE -> "toggle"
    ThinkingCapability.EFFORT -> "effort"
    ThinkingCapability.ADAPTIVE -> "adaptive"
    ThinkingCapability.OUTPUT_EFFORT -> "output_effort"
    ThinkingCapability.ALWAYS_ON -> "always_on"
}
