package com.sebastian.android.data.model

sealed class ContentBlock {
    abstract val blockId: String

    val isDone: Boolean get() = when (this) {
        is TextBlock     -> done
        is ThinkingBlock -> done
        is ToolBlock     -> status == ToolStatus.DONE || status == ToolStatus.FAILED
        is SummaryBlock  -> true
    }

    data class TextBlock(
        override val blockId: String,
        val text: String,
        val done: Boolean = false,
    ) : ContentBlock()

    data class ThinkingBlock(
        override val blockId: String,
        val text: String,
        val done: Boolean = false,
        val expanded: Boolean = false,
        val durationMs: Long? = null,
    ) : ContentBlock()

    data class ToolBlock(
        override val blockId: String,
        val toolId: String,
        val name: String,
        val inputs: String,
        val status: ToolStatus,
        val resultSummary: String? = null,
        val error: String? = null,
        val expanded: Boolean = false,
    ) : ContentBlock()

    data class SummaryBlock(
        override val blockId: String,
        val text: String,
        val expanded: Boolean = false,
        val sourceSeqStart: Long? = null,
        val sourceSeqEnd: Long? = null,
    ) : ContentBlock()
}

enum class ToolStatus { PENDING, RUNNING, DONE, FAILED }
