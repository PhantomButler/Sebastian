package com.sebastian.android.data.local

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class MarkwonMarkdownParser @Inject constructor(
    @param:ApplicationContext private val context: Context,
) : MarkdownParser {
    private val markwon: Markwon = Markwon.builder(context)
        .usePlugin(StrikethroughPlugin.create())
        .usePlugin(TablePlugin.create(context))
        .build()

    override fun parse(text: String): CharSequence = markwon.toMarkdown(text)
}
