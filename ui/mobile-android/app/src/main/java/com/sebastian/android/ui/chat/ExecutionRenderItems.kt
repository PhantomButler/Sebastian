package com.sebastian.android.ui.chat

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.ToolStatus

sealed interface MessageRenderItem {
    data class Block(val block: ContentBlock) : MessageRenderItem

    data class ExecutionGroup(
        val id: String,
        val blocks: List<ContentBlock>,
    ) : MessageRenderItem
}

enum class ExecutionStepState {
    DONE,
    RUNNING,
    FAILED,
}

data class ActiveExecutionSummary(
    val id: String,
    val text: String,
)

fun buildMessageRenderItems(blocks: List<ContentBlock>): List<MessageRenderItem> {
    val items = mutableListOf<MessageRenderItem>()
    val pendingExecutionBlocks = mutableListOf<ContentBlock>()

    fun flushExecutionGroup() {
        if (pendingExecutionBlocks.isEmpty()) return
        val firstId = pendingExecutionBlocks.first().blockId
        val lastId = pendingExecutionBlocks.last().blockId
        items += MessageRenderItem.ExecutionGroup(
            id = "exec-$firstId-$lastId",
            blocks = pendingExecutionBlocks.toList(),
        )
        pendingExecutionBlocks.clear()
    }

    for (block in blocks) {
        when {
            block.isExecutionBlock() -> pendingExecutionBlocks += block
            block.isBlankTextBlock() -> {}
            else -> {
                flushExecutionGroup()
                items += MessageRenderItem.Block(block)
            }
        }
    }
    flushExecutionGroup()

    return items
}

fun ContentBlock.isExecutionBlock(): Boolean =
    this is ContentBlock.ThinkingBlock || this is ContentBlock.ToolBlock

private fun ContentBlock.isBlankTextBlock(): Boolean =
    this is ContentBlock.TextBlock && text.isBlank()

fun executionStepState(block: ContentBlock): ExecutionStepState = when (block) {
    is ContentBlock.ThinkingBlock ->
        if (block.done) ExecutionStepState.DONE else ExecutionStepState.RUNNING
    is ContentBlock.ToolBlock -> when (block.status) {
        ToolStatus.DONE -> ExecutionStepState.DONE
        ToolStatus.FAILED -> ExecutionStepState.FAILED
        ToolStatus.PENDING, ToolStatus.RUNNING -> ExecutionStepState.RUNNING
    }
    else -> error("Non-execution block has no execution step state: ${block::class.simpleName}")
}

fun activeExecutionSummary(blocks: List<ContentBlock>): ActiveExecutionSummary? {
    val activeBlock = blocks.lastOrNull { block ->
        block.isExecutionBlock() && executionStepState(block) == ExecutionStepState.RUNNING
    } ?: return null

    val text = when (activeBlock) {
        is ContentBlock.ThinkingBlock -> "Thinking"
        is ContentBlock.ToolBlock -> activeBlock.activeToolSummaryText()
        else -> return null
    }

    return ActiveExecutionSummary(
        id = activeBlock.blockId,
        text = text,
    )
}

private fun ContentBlock.ToolBlock.activeToolSummaryText(): String {
    val title = displayName.ifBlank { name }
    val inputSummary = ToolCallInputExtractor.extractInputSummary(name, inputs)
    return if (inputSummary.isBlank()) title else "$title $inputSummary"
}
