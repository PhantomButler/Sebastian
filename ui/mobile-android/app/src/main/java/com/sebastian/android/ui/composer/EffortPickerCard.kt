// com/sebastian/android/ui/composer/EffortPickerCard.kt
package com.sebastian.android.ui.composer

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.ui.common.glass.GlassState
import com.sebastian.android.ui.common.glass.GlassSurface

private val EFFORT_OPTIONS = listOf(
    ThinkingEffort.OFF to "Off",
    ThinkingEffort.LOW to "Low",
    ThinkingEffort.MEDIUM to "Medium",
    ThinkingEffort.HIGH to "High",
)

private val ADAPTIVE_OPTIONS = listOf(
    ThinkingEffort.OFF to "Off",
    ThinkingEffort.LOW to "Low",
    ThinkingEffort.MEDIUM to "Medium",
    ThinkingEffort.HIGH to "High",
    ThinkingEffort.MAX to "Max",
)

/**
 * 思考档位选择卡片。
 *
 * 使用 [GlassSurface] 实现玻璃材质模糊效果。
 * 必须放在与 [GlassState.contentModifier] 同一棵 composable 树中，否则 backdrop 采样无法工作。
 * （因此不能放在 Popup / Dialog 里；应由 ChatScreen 在其根 Box 中直接渲染。）
 */
@Composable
fun EffortPickerCard(
    current: ThinkingEffort,
    capability: ThinkingCapability,
    glassState: GlassState,
    onSelect: (ThinkingEffort) -> Unit,
    modifier: Modifier = Modifier,
) {
    val options = if (capability == ThinkingCapability.ADAPTIVE) ADAPTIVE_OPTIONS else EFFORT_OPTIONS
    val cardShape = RoundedCornerShape(20.dp)

    GlassSurface(
        state = glassState,
        shape = cardShape,
        shadowElevation = 16.dp,
        shadowCornerRadius = 20.dp,
        shadowColor = Color.Black.copy(alpha = 0.18f),
        modifier = modifier,
    ) {
        Column(modifier = Modifier.padding(vertical = 4.dp)) {
            Text(
                text = "Thinking Mode",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 14.dp),
            )
            HorizontalDivider(
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f),
            )
            options.forEach { (effort, label) ->
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onSelect(effort) }
                        .padding(start = 20.dp, end = 12.dp, top = 4.dp, bottom = 4.dp),
                ) {
                    Text(
                        text = label,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f),
                    )
                    RadioButton(
                        selected = current == effort,
                        onClick = { onSelect(effort) },
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}
