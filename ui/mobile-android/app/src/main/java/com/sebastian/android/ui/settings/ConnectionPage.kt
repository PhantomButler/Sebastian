package com.sebastian.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.viewmodel.ConnectionTestResult
import com.sebastian.android.viewmodel.SettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConnectionPage(
    navController: NavController,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    var urlInput by rememberSaveable(uiState.serverUrl) {
        mutableStateOf(uiState.serverUrl)
    }

    LaunchedEffect(uiState.connectionTestResult) {
        when (val result = uiState.connectionTestResult) {
            is ConnectionTestResult.Success -> {
                snackbarHostState.showSnackbar("连接成功")
                viewModel.clearConnectionTestResult()
            }
            is ConnectionTestResult.Failure -> {
                snackbarHostState.showSnackbar("连接失败：${result.message}")
                viewModel.clearConnectionTestResult()
            }
            null -> {}
        }
    }

    LaunchedEffect(uiState.error) {
        uiState.error?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearError()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("连接与账户") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
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
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Spacer(Modifier.height(8.dp))
            Text("服务器地址", style = MaterialTheme.typography.titleSmall)
            OutlinedTextField(
                value = urlInput,
                onValueChange = { urlInput = it },
                label = { Text("http://192.168.1.x:8823") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { viewModel.testConnection(urlInput) },
                    enabled = urlInput.isNotBlank() && !uiState.isLoading,
                    modifier = Modifier.weight(1f),
                ) {
                    if (uiState.isLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier
                                .width(20.dp)
                                .height(20.dp),
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Text("测试连接")
                    }
                }
                Button(
                    onClick = {
                        viewModel.saveServerUrl(urlInput)
                        navController.popBackStack()
                    },
                    enabled = urlInput.isNotBlank(),
                    modifier = Modifier.weight(1f),
                ) {
                    Text("保存")
                }
            }
            Text(
                text = "模拟器访问宿主机：http://10.0.2.2:8823\n真机使用局域网 IP",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
