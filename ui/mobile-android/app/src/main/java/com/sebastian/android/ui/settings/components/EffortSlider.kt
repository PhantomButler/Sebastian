package com.sebastian.android.ui.settings.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.ui.common.SebastianSwitch

fun effortStepsFor(capability: ThinkingCapability): List<ThinkingEffort> = when (capability) {
    ThinkingCapability.TOGGLE -> listOf(ThinkingEffort.OFF, ThinkingEffort.ON)
    ThinkingCapability.EFFORT -> listOf(
        ThinkingEffort.OFF, ThinkingEffort.LOW, ThinkingEffort.MEDIUM, ThinkingEffort.HIGH,
    )
    ThinkingCapability.ADAPTIVE -> listOf(
        ThinkingEffort.OFF, ThinkingEffort.LOW, ThinkingEffort.MEDIUM, ThinkingEffort.HIGH, ThinkingEffort.MAX,
    )
    ThinkingCapability.OUTPUT_EFFORT -> listOf(
        ThinkingEffort.OFF, ThinkingEffort.HIGH, ThinkingEffort.MAX,
    )
    else -> emptyList()
}

private fun ThinkingEffort.label(): String = when (this) {
    ThinkingEffort.OFF -> "Off"
    ThinkingEffort.ON -> "On"
    ThinkingEffort.LOW -> "Low"
    ThinkingEffort.MEDIUM -> "Med"
    ThinkingEffort.HIGH -> "High"
    ThinkingEffort.MAX -> "Max"
}

@Composable
fun EffortSlider(
    capability: ThinkingCapability,
    value: ThinkingEffort,
    onValueChange: (ThinkingEffort) -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val steps = effortStepsFor(capability)
    if (steps.isEmpty()) return

    if (capability == ThinkingCapability.TOGGLE) {
        Row(
            modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Thinking", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            SebastianSwitch(
                checked = value == ThinkingEffort.ON,
                onCheckedChange = if (enabled) {
                    { checked -> onValueChange(if (checked) ThinkingEffort.ON else ThinkingEffort.OFF) }
                } else null,
                enabled = enabled,
            )
        }
        return
    }

    Column(
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)
            .alpha(if (enabled) 1f else 0.38f),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            steps.forEach { step ->
                val selected = step == value
                FilterChip(
                    selected = selected,
                    onClick = { if (enabled) onValueChange(step) },
                    label = {
                        Text(
                            text = step.label(),
                            style = MaterialTheme.typography.labelMedium,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    },
                    modifier = Modifier.weight(1f),
                    enabled = enabled,
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
                        selectedLabelColor = MaterialTheme.colorScheme.onPrimaryContainer,
                    ),
                    border = FilterChipDefaults.filterChipBorder(
                        enabled = enabled,
                        selected = selected,
                        borderColor = MaterialTheme.colorScheme.outlineVariant,
                        selectedBorderColor = MaterialTheme.colorScheme.primaryContainer,
                        borderWidth = 1.dp,
                        selectedBorderWidth = 0.dp,
                    ),
                )
            }
        }
    }
}
