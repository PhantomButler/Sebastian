package com.sebastian.android.ui.settings

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.navigation.NavController

@Composable
fun AgentBindingEditorPage(agentType: String, navController: NavController) {
    Text("Editor for $agentType")
}
