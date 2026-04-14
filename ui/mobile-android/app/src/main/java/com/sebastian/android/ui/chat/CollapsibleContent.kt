package com.sebastian.android.ui.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 展开态「参数」/「输出」区内部的二次折叠容器。
 *
 * 行为对齐 RN `ui/mobile/src/components/conversation/CollapsibleContent.tsx`：
 * - `lines <= 5`：直接展示全部；
 * - `lines > 5`：折叠态只显示第一行 + 右箭头；展开态最多显示 30 行，超出追加 `… (共 N 行)`，点击任意处收起。
 */
private const val LINE_THRESHOLD = 5
private const val MAX_LINES = 30

@Composable
fun CollapsibleContent(
    content: String,
    modifier: Modifier = Modifier,
) {
    if (content.isBlank()) return

    val mutedColor = MaterialTheme.colorScheme.onSurfaceVariant
    val textStyle = MaterialTheme.typography.bodySmall.copy(
        fontFamily = FontFamily.Monospace,
        fontSize = 12.sp,
        lineHeight = 18.sp,
        color = mutedColor,
    )

    val allLines = content.split('\n')
    val totalLines = allLines.size

    if (totalLines <= LINE_THRESHOLD) {
        Text(text = content, style = textStyle, modifier = modifier)
        return
    }

    // 不用 content 做 key——saveable 自动按 call site + position 管理生命周期，
    // 内容变化（例如流式增量 inputs/result）不会坍塌已展开状态
    var expanded by rememberSaveable { mutableStateOf(false) }
    val interactionSource = remember { MutableInteractionSource() }

    if (!expanded) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            modifier = modifier.clickable(
                interactionSource = interactionSource,
                indication = null,
            ) { expanded = true },
        ) {
            Text(
                text = allLines[0],
                style = textStyle,
                maxLines = 1,
                modifier = Modifier.weight(1f, fill = false),
            )
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = "展开",
                tint = mutedColor,
                modifier = Modifier.width(12.dp),
            )
        }
        return
    }

    val displayLines = allLines.take(MAX_LINES)
    val truncated = totalLines > MAX_LINES
    val displayText = if (truncated) {
        displayLines.joinToString("\n") + "\n… (共 $totalLines 行)"
    } else {
        displayLines.joinToString("\n")
    }

    Text(
        text = displayText,
        style = textStyle,
        modifier = modifier.clickable(
            interactionSource = interactionSource,
            indication = null,
        ) { expanded = false },
    )
}
