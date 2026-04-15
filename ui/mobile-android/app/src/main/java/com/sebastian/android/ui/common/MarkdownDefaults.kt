package com.sebastian.android.ui.common

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.mikepenz.markdown.compose.components.MarkdownComponents
import com.mikepenz.markdown.compose.components.markdownComponents
import com.mikepenz.markdown.compose.elements.MarkdownHighlightedCodeBlock
import com.mikepenz.markdown.compose.elements.MarkdownHighlightedCodeFence
import com.mikepenz.markdown.m3.markdownColor
import com.mikepenz.markdown.m3.markdownTypography
import com.mikepenz.markdown.model.MarkdownColors
import com.mikepenz.markdown.model.MarkdownTypography
import dev.snipme.highlights.Highlights
import dev.snipme.highlights.model.SyntaxThemes

object MarkdownDefaults {

    @Composable
    fun colors(): MarkdownColors = markdownColor(
        text = MaterialTheme.colorScheme.onSurface,
        codeBackground = MaterialTheme.colorScheme.surfaceVariant,
        inlineCodeBackground = Color.Transparent,
        dividerColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f),
    )

    @Composable
    fun typography(): MarkdownTypography {
        val base = MaterialTheme.typography.bodyLarge
        return markdownTypography(
            h1 = base.copy(fontSize = 22.sp, fontWeight = FontWeight.Bold, lineHeight = 30.sp),
            h2 = base.copy(fontSize = 19.sp, fontWeight = FontWeight.SemiBold, lineHeight = 27.sp),
            h3 = base.copy(fontSize = 17.sp, fontWeight = FontWeight.Medium, lineHeight = 25.sp),
            h4 = base.copy(fontWeight = FontWeight.Medium),
            h5 = base,
            h6 = MaterialTheme.typography.bodyMedium,
            text = base,
            code = TextStyle(
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
                lineHeight = 20.sp,
            ),
            inlineCode = MaterialTheme.typography.bodyMedium.copy(
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.primary,
            ),
        )
    }

    @Composable
    fun components(): MarkdownComponents {
        val isDark = isSystemInDarkTheme()
        val highlightsBuilder = remember(isDark) {
            Highlights.Builder().theme(SyntaxThemes.atom(darkMode = isDark))
        }
        return markdownComponents(
            codeBlock = {
                MarkdownHighlightedCodeBlock(
                    content = it.content,
                    node = it.node,
                    highlightsBuilder = highlightsBuilder,
                    showHeader = true,
                )
            },
            codeFence = {
                MarkdownHighlightedCodeFence(
                    content = it.content,
                    node = it.node,
                    highlightsBuilder = highlightsBuilder,
                    showHeader = true,
                )
            },
        )
    }
}
