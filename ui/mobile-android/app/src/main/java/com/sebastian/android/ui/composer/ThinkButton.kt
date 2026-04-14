// com/sebastian/android/ui/composer/ThinkButton.kt
package com.sebastian.android.ui.composer

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.ui.common.SebastianIcons
import kotlinx.coroutines.launch

/**
 * ThinkButton 根据当前 Provider 的 thinking_capability 渲染不同形态：
 *
 * | capability  | 渲染                              |
 * |-------------|----------------------------------|
 * | null        | 禁用 chip（加载中）                 |
 * | NONE        | 不渲染                             |
 * | ALWAYS_ON   | 非交互 badge「思考·自动」             |
 * | TOGGLE      | 单击切换 on/off                    |
 * | EFFORT      | 单击打开 EffortPickerSheet          |
 * | ADAPTIVE    | 单击打开 EffortPickerSheet          |
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ThinkButton(
    activeProvider: Provider?,
    currentEffort: ThinkingEffort,
    onEffortChange: (ThinkingEffort) -> Unit,
    modifier: Modifier = Modifier,
) {
    val capability = activeProvider?.thinkingCapability

    // NONE：不渲染任何内容
    if (capability == ThinkingCapability.NONE) return

    var showSheet by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState()
    val scope = rememberCoroutineScope()

    val isActive = currentEffort != ThinkingEffort.OFF

    val label = when (capability) {
        null -> "思考…"
        ThinkingCapability.ALWAYS_ON -> "思考·自动"
        ThinkingCapability.TOGGLE -> if (isActive) "思考·开" else "思考·关"
        ThinkingCapability.EFFORT, ThinkingCapability.ADAPTIVE -> when (currentEffort) {
            ThinkingEffort.OFF -> "思考"
            ThinkingEffort.LOW -> "思考·轻"
            ThinkingEffort.MEDIUM -> "思考·中"
            ThinkingEffort.HIGH -> "思考·深"
            ThinkingEffort.MAX -> "思考·最大"
            ThinkingEffort.ON -> "思考·开"
        }
        ThinkingCapability.NONE -> return
    }

    AssistChip(
        onClick = {
            when (capability) {
                null, ThinkingCapability.ALWAYS_ON -> { /* 不可点击 */ }
                ThinkingCapability.TOGGLE -> {
                    onEffortChange(if (isActive) ThinkingEffort.OFF else ThinkingEffort.ON)
                }
                ThinkingCapability.EFFORT, ThinkingCapability.ADAPTIVE -> showSheet = true
                ThinkingCapability.NONE -> {}
            }
        },
        label = { Text(label, style = MaterialTheme.typography.labelMedium) },
        leadingIcon = {
            Icon(SebastianIcons.Think, contentDescription = null)
        },
        enabled = capability != null && capability != ThinkingCapability.ALWAYS_ON,
        shape = RoundedCornerShape(percent = 50),
        colors = if (isActive && capability != ThinkingCapability.ALWAYS_ON)
            AssistChipDefaults.assistChipColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
        else AssistChipDefaults.assistChipColors(),
        modifier = modifier.alpha(if (capability == null) 0.5f else 1f),
    )

    if (showSheet) {
        ModalBottomSheet(
            onDismissRequest = { showSheet = false },
            sheetState = sheetState,
        ) {
            EffortPickerSheet(
                current = currentEffort,
                capability = capability!!,
                onSelect = { effort ->
                    onEffortChange(effort)
                    scope.launch { sheetState.hide() }.invokeOnCompletion { showSheet = false }
                },
            )
        }
    }
}

private val EFFORT_OPTIONS = listOf(
    ThinkingEffort.OFF to "关闭",
    ThinkingEffort.LOW to "轻度思考",
    ThinkingEffort.MEDIUM to "中度思考",
    ThinkingEffort.HIGH to "深度思考",
)

private val ADAPTIVE_OPTIONS = listOf(
    ThinkingEffort.OFF to "关闭",
    ThinkingEffort.LOW to "轻度思考",
    ThinkingEffort.MEDIUM to "中度思考",
    ThinkingEffort.HIGH to "深度思考",
    ThinkingEffort.MAX to "最大思考",
)

@Composable
private fun EffortPickerSheet(
    current: ThinkingEffort,
    capability: ThinkingCapability,
    onSelect: (ThinkingEffort) -> Unit,
) {
    val options = if (capability == ThinkingCapability.ADAPTIVE) ADAPTIVE_OPTIONS else EFFORT_OPTIONS

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 32.dp),
    ) {
        Text(
            "思考档位",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        )
        options.forEach { (effort, label) ->
            ListItem(
                headlineContent = { Text(label) },
                trailingContent = {
                    RadioButton(
                        selected = current == effort,
                        onClick = { onSelect(effort) },
                    )
                },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}
