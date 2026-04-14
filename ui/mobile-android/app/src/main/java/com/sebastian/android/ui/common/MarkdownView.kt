package com.sebastian.android.ui.common

import android.widget.TextView
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.viewinterop.AndroidView

/**
 * Renders pre-parsed Markdown (Spanned CharSequence).
 * Parsing is done on IO thread in ChatViewModel; this composable only assigns
 * the result to TextView.text on the Main thread — zero parse work here.
 */
@Composable
fun MarkdownView(
    markdown: CharSequence,
    modifier: Modifier = Modifier,
) {
    val textColor = MaterialTheme.colorScheme.onSurface.toArgb()

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
            textView.text = markdown
        },
        modifier = modifier,
    )
}
