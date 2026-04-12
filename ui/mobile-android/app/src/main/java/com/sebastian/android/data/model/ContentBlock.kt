package com.sebastian.android.data.model

sealed class ContentBlock {
    abstract val blockId: String

    data class TextBlock(
        override val blockId: String,
        val text: String,
        val done: Boolean,
    ) : ContentBlock()

    data class ThinkingBlock(
        override val blockId: String,
        val text: String,
        val done: Boolean,
        val expanded: Boolean = false,
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
}

enum class ToolStatus { PENDING, RUNNING, DONE, FAILED }
