package com.sebastian.android.ui.common

import android.widget.TextView
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin

/**
 * 已完成的 TextBlock 渲染：Markwon 在调用前已在 IO 线程解析为 CharSequence，
 * 此组件仅在 Main Thread 调用 TextView.text = spanned。
 *
 * 流式进行中的 TextBlock 使用 Compose Text() 直接渲染纯文本（见 StreamingMessage.kt）。
 */
@Composable
fun MarkdownView(
    markdown: String,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val textColor = MaterialTheme.colorScheme.onSurface.toArgb()

    val markwon = remember(context) {
        Markwon.builder(context)
            .usePlugin(StrikethroughPlugin.create())
            .usePlugin(TablePlugin.create(context))
            .build()
    }

    AndroidView(
        factory = { ctx ->
            TextView(ctx).apply {
                setTextColor(textColor)
                textSize = 16f
                setLineSpacing(0f, 1.4f)
            }
        },
        update = { textView ->
            textView.setTextColor(textColor)
            markwon.setMarkdown(textView, markdown)
        },
        modifier = modifier,
    )
}
