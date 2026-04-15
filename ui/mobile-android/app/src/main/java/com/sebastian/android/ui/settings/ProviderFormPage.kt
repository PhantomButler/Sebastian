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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.ui.common.SebastianSwitch
import com.sebastian.android.viewmodel.ProviderFormViewModel

private val PROVIDER_TYPES = listOf("anthropic", "openai")

private val MODEL_PLACEHOLDERS = mapOf(
    "anthropic" to "claude-sonnet-4-5",
    "openai" to "gpt-4o",
)

private data class CapabilityOption(
    val value: ThinkingCapability,
    val label: String,
    val hint: String,
)

private val CAPABILITY_OPTIONS = listOf(
    CapabilityOption(ThinkingCapability.NONE, "none", "模型不支持思考控制"),
    CapabilityOption(ThinkingCapability.TOGGLE, "toggle", "只支持开关，没有档位"),
    CapabilityOption(ThinkingCapability.EFFORT, "effort", "支持 low / medium / high 三档"),
    CapabilityOption(ThinkingCapability.ADAPTIVE, "adaptive", "Anthropic Adaptive，含 max 档位"),
    CapabilityOption(ThinkingCapability.ALWAYS_ON, "always_on", "模型固定思考，前端不再提供切换"),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProviderFormPage(
    navController: NavController,
    providerId: String?,
    viewModel: ProviderFormViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    var apiKeyVisible by remember { mutableStateOf(false) }
    var capabilityMenuExpanded by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        providerId?.let { viewModel.loadProvider(it) }
    }

    LaunchedEffect(uiState.isSaved) {
        if (uiState.isSaved) navController.popBackStack()
    }

    LaunchedEffect(uiState.error) {
        uiState.error?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearError()
        }
    }

    val doneEnabled = uiState.isDirty && !uiState.isLoading

    Scaffold(
        topBar = {
            TopAppBar(
                title = {},
                navigationIcon = {
                    TextButton(onClick = { navController.popBackStack() }) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                        Text("返回", modifier = Modifier.padding(start = 4.dp))
                    }
                },
                actions = {
                    Surface(
                        onClick = { if (doneEnabled) viewModel.save(providerId) },
                        shape = RoundedCornerShape(18.dp),
                        color = if (doneEnabled) MaterialTheme.colorScheme.primary
                               else MaterialTheme.colorScheme.surfaceContainerHighest,
                        modifier = Modifier.padding(end = 8.dp),
                    ) {
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .height(36.dp)
                                .padding(horizontal = 16.dp),
                        ) {
                            if (uiState.isLoading) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(18.dp),
                                    strokeWidth = 2.dp,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                            } else {
                                Text(
                                    "完成",
                                    fontSize = 15.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = if (doneEnabled) MaterialTheme.colorScheme.onPrimary
                                           else MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            // ── 名称 ──
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = MaterialTheme.colorScheme.surfaceContainerLow,
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    FieldLabel("名称")
                    OutlinedTextField(
                        value = uiState.name,
                        onValueChange = viewModel::onNameChange,
                        placeholder = { Text("Claude / OpenAI / DeepSeek...") },
                        singleLine = true,
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier.fillMaxWidth(),
                    )

                    FieldLabel("Provider 类型", topPadding = 14.dp)
                    SegmentedControl(
                        options = PROVIDER_TYPES,
                        selected = uiState.type,
                        onSelect = viewModel::onTypeChange,
                    )
                }
            }

            // ── 连接配置 ──
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = MaterialTheme.colorScheme.surfaceContainerLow,
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    FieldLabel("API Key")
                    OutlinedTextField(
                        value = uiState.apiKey,
                        onValueChange = viewModel::onApiKeyChange,
                        placeholder = { Text("sk-...") },
                        singleLine = true,
                        shape = RoundedCornerShape(14.dp),
                        visualTransformation = if (apiKeyVisible) VisualTransformation.None
                                              else PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        trailingIcon = {
                            IconButton(onClick = { apiKeyVisible = !apiKeyVisible }) {
                                Text(
                                    if (apiKeyVisible) "隐藏" else "显示",
                                    fontSize = 13.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                    )

                    FieldLabel("Base URL", topPadding = 14.dp)
                    OutlinedTextField(
                        value = uiState.baseUrl,
                        onValueChange = viewModel::onBaseUrlChange,
                        placeholder = { Text("https://api.example.com/v1") },
                        singleLine = true,
                        shape = RoundedCornerShape(14.dp),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }

            // ── 模型与思考能力 ──
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = MaterialTheme.colorScheme.surfaceContainerLow,
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    FieldLabel("模型")
                    OutlinedTextField(
                        value = uiState.model,
                        onValueChange = viewModel::onModelChange,
                        placeholder = { Text(MODEL_PLACEHOLDERS[uiState.type] ?: "") },
                        singleLine = true,
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier.fillMaxWidth(),
                    )

                    FieldLabel("思考能力", topPadding = 14.dp)
                    val currentOption = CAPABILITY_OPTIONS.first { it.value == uiState.thinkingCapability }
                    ExposedDropdownMenuBox(
                        expanded = capabilityMenuExpanded,
                        onExpandedChange = { capabilityMenuExpanded = it },
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
                            onDismissRequest = { capabilityMenuExpanded = false },
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
                                        viewModel.onThinkingCapabilityChange(option.value)
                                        capabilityMenuExpanded = false
                                    },
                                )
                            }
                        }
                    }
                }
            }

            // ── 默认设置 ──
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = MaterialTheme.colorScheme.surfaceContainerLow,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(18.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "设为默认 Provider",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Medium,
                        modifier = Modifier.weight(1f),
                    )
                    SebastianSwitch(
                        checked = uiState.isDefault,
                        onCheckedChange = viewModel::onIsDefaultChange,
                    )
                }
            }

            Spacer(Modifier.height(32.dp))
        }
    }
}

// ── 共用组件 ──

@Composable
private fun FieldLabel(text: String, topPadding: androidx.compose.ui.unit.Dp = 0.dp) {
    Text(
        text,
        fontSize = 13.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = topPadding, bottom = 8.dp),
    )
}

@Composable
private fun SegmentedControl(
    options: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surfaceContainerHighest,
    ) {
        Row(modifier = Modifier.padding(4.dp)) {
            options.forEach { option ->
                val active = option == selected
                Surface(
                    onClick = { onSelect(option) },
                    shape = RoundedCornerShape(12.dp),
                    color = if (active) MaterialTheme.colorScheme.surface else Color.Transparent,
                    modifier = Modifier
                        .weight(1f)
                        .height(40.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text(
                            option,
                            fontSize = 15.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = if (active) MaterialTheme.colorScheme.onSurface
                                   else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}
