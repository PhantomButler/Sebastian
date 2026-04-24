package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.ToolStatus

fun List<TimelineItemDto>.toMessagesFromTimeline(): List<Message> {
    val output = mutableListOf<Message>()
    var currentGroupKey: Pair<String?, Int?>? = null
    var currentGroupItems = mutableListOf<TimelineItemDto>()

    fun flushAssistantGroup() {
        if (currentGroupItems.isEmpty()) return
        val msg = currentGroupItems.toAssistantMessage()
        if (msg != null) output += msg
        currentGroupItems = mutableListOf()
        currentGroupKey = null
    }

    sortedBy { it.seq }.forEach { item ->
        when (item.kind) {
            "user_message" -> {
                flushAssistantGroup()
                output += item.toUserMessage()
            }
            "context_summary" -> {
                flushAssistantGroup()
                output += item.toSummaryMessage()
            }
            "assistant_message", "thinking", "tool_call", "tool_result" -> {
                val key = item.assistantTurnId to item.providerCallIndex
                if (currentGroupKey != null && currentGroupKey != key) {
                    flushAssistantGroup()
                }
                currentGroupKey = key
                currentGroupItems += item
            }
            // system_event, raw_block → skip
        }
    }
    flushAssistantGroup()
    return output
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

private fun TimelineItemDto.stableBlockId(): String {
    return if (assistantTurnId != null && providerCallIndex != null && blockIndex != null) {
        "timeline-$sessionId-$assistantTurnId-$providerCallIndex-$blockIndex"
    } else {
        "timeline-$sessionId-block-$seq"
    }
}

private fun TimelineItemDto.toUserMessage(): Message = Message(
    id = "timeline-$sessionId-$seq",
    sessionId = sessionId,
    role = MessageRole.USER,
    blocks = emptyList(),
    text = content ?: "",
    createdAt = createdAt ?: "",
)

private fun TimelineItemDto.toSummaryMessage(): Message {
    val blockId = "timeline-$sessionId-summary-block-$seq"
    val block = ContentBlock.SummaryBlock(
        blockId = blockId,
        text = content ?: "",
        sourceSeqStart = payloadLong("source_seq_start"),
        sourceSeqEnd = payloadLong("source_seq_end"),
    )
    return Message(
        id = "timeline-$sessionId-summary-$seq",
        sessionId = sessionId,
        role = MessageRole.ASSISTANT,
        blocks = listOf(block),
        createdAt = createdAt ?: "",
    )
}

private fun List<TimelineItemDto>.toAssistantMessage(): Message? {
    if (isEmpty()) return null
    val first = first()
    val sessionId = first.sessionId

    // Compute stable message ID
    val msgId = run {
        val assistantTurnId = first.assistantTurnId
        val pci = first.providerCallIndex
        if (assistantTurnId != null && pci != null) {
            "timeline-$sessionId-$assistantTurnId-$pci"
        } else {
            "timeline-$sessionId-${first.seq}"
        }
    }

    val blocks = buildAssistantBlocks(sessionId)

    return Message(
        id = msgId,
        sessionId = sessionId,
        role = MessageRole.ASSISTANT,
        blocks = blocks,
        createdAt = first.createdAt ?: "",
    )
}

private fun List<TimelineItemDto>.buildAssistantBlocks(sessionId: String): List<ContentBlock> {
    val toolCalls = filter { it.kind == "tool_call" }
    val toolResults = filter { it.kind == "tool_result" }

    // Build a map from tool_call_id → tool_result
    val resultByCallId: Map<String, TimelineItemDto> = toolResults
        .mapNotNull { r -> r.payloadString("tool_call_id")?.let { it to r } }
        .toMap()

    // Track which tool_result items were matched (to detect orphans)
    val matchedResultIds = mutableSetOf<String>()

    val blocks = mutableListOf<ContentBlock>()

    forEach { item ->
        when (item.kind) {
            "thinking" -> {
                blocks += ContentBlock.ThinkingBlock(
                    blockId = item.stableBlockId(),
                    text = item.content ?: "",
                    done = true,
                    durationMs = item.payloadLong("duration_ms"),
                )
            }
            "assistant_message" -> {
                blocks += ContentBlock.TextBlock(
                    blockId = item.stableBlockId(),
                    text = item.content ?: "",
                    done = true,
                )
            }
            "tool_call" -> {
                val callId = item.payloadString("tool_call_id") ?: ""
                val result = resultByCallId[callId]
                if (result != null) matchedResultIds += result.id

                val status = when {
                    result == null -> ToolStatus.PENDING
                    result.payloadBoolean("ok") == true -> ToolStatus.DONE
                    result.payloadBoolean("ok") == false || result.payload?.containsKey("error") == true -> ToolStatus.FAILED
                    else -> ToolStatus.DONE
                }

                blocks += ContentBlock.ToolBlock(
                    blockId = item.stableBlockId(),
                    toolId = callId,
                    name = item.payloadString("tool_name") ?: item.payloadString("name") ?: "",
                    inputs = item.content ?: "",
                    status = status,
                    resultSummary = result?.content,
                    error = if (status == ToolStatus.FAILED) result?.payloadString("error") else null,
                )
            }
            "tool_result" -> {
                // Only handle as orphan if not already matched to a tool_call
                if (item.id !in matchedResultIds) {
                    val callId = item.payloadString("tool_call_id") ?: ""
                    val failed = item.payloadBoolean("ok") == false || item.payload?.containsKey("error") == true
                    blocks += ContentBlock.ToolBlock(
                        blockId = "timeline-$sessionId-tool-result-${item.seq}",
                        toolId = callId,
                        name = "",
                        inputs = "",
                        status = if (failed) ToolStatus.FAILED else ToolStatus.DONE,
                        resultSummary = item.content,
                        error = if (failed) item.payloadString("error") else null,
                    )
                }
            }
        }
    }

    return blocks
}
