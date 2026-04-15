// com/sebastian/android/ui/composer/ThinkButton.kt
package com.sebastian.android.ui.composer

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.ui.common.SebastianIcons

/**
 * ThinkButton 根据当前 Provider 的 thinking_capability 渲染不同形态：
 *
 * | capability  | 渲染                         |
 * |-------------|------------------------------|
 * | null        | 禁用 chip（加载中）             |
 * | NONE        | 不渲染                         |
 * | ALWAYS_ON   | 非交互 badge「auto」            |
 * | TOGGLE      | 单击切换 on/off               |
 * | EFFORT      | 单击调用 [onShowPicker]        |
 * | ADAPTIVE    | 单击调用 [onShowPicker]        |
 *
 * Chip 宽度通过 [widthIn] 固定最小值，不随档位文字跳动。
 * Picker 弹出逻辑由调用方（ChatScreen）负责，通过 [onShowPicker] 回调触发。
 */
@Composable
fun ThinkButton(
    activeProvider: Provider?,
    currentEffort: ThinkingEffort,
    onEffortChange: (ThinkingEffort) -> Unit,
    onShowPicker: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val capability = activeProvider?.thinkingCapability

    if (capability == ThinkingCapability.NONE) return

    val isActive = currentEffort != ThinkingEffort.OFF

    val label = when (capability) {
        null -> "…"
        ThinkingCapability.ALWAYS_ON -> "Auto"
        ThinkingCapability.TOGGLE -> if (isActive) "On" else "Off"
        ThinkingCapability.EFFORT, ThinkingCapability.ADAPTIVE -> when (currentEffort) {
            ThinkingEffort.OFF -> "Off"
            ThinkingEffort.ON -> "On"
            ThinkingEffort.LOW -> "Low"
            ThinkingEffort.MEDIUM -> "Medium"
            ThinkingEffort.HIGH -> "High"
            ThinkingEffort.MAX -> "Max"
        }
        ThinkingCapability.NONE -> return
    }

    val isEnabled = capability != null && capability != ThinkingCapability.ALWAYS_ON
    val chipShape = RoundedCornerShape(percent = 50)

    val backgroundColor = if (isActive && capability != ThinkingCapability.ALWAYS_ON)
        MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
    else
        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f)

    val borderColor = if (isActive && capability != ThinkingCapability.ALWAYS_ON)
        MaterialTheme.colorScheme.primary.copy(alpha = 0.32f)
    else
        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f)

    val contentColor = if (isActive && capability != ThinkingCapability.ALWAYS_ON)
        MaterialTheme.colorScheme.primary
    else
        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f)

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = modifier
            .width(90.dp)
            .alpha(if (capability == null) 0.5f else 1f)
            .clip(chipShape)
            .background(backgroundColor)
            .border(0.5.dp, borderColor, chipShape)
            .clickable(enabled = isEnabled) {
                when (capability) {
                    ThinkingCapability.TOGGLE ->
                        onEffortChange(if (isActive) ThinkingEffort.OFF else ThinkingEffort.ON)
                    ThinkingCapability.EFFORT, ThinkingCapability.ADAPTIVE -> onShowPicker()
                    else -> {}
                }
            }
            .padding(horizontal = 10.dp, vertical = 6.dp),
    ) {
        Icon(
            imageVector = SebastianIcons.Think,
            contentDescription = null,
            tint = contentColor,
            modifier = Modifier.size(16.dp),
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = contentColor,
            textAlign = TextAlign.Center,
            modifier = Modifier.weight(1f),
        )
    }
}
