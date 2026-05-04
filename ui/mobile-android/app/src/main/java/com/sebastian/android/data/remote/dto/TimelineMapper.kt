package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.ToolStatus


fun List<TimelineItemDto>.toMessagesFromTimeline(baseUrl: String = ""): List<Message> {
    val sorted = sortedBy { it.seq }
    val output = mutableListOf<Message>()

    // ── User-side: group by exchangeId ──────────────────────────────────────
    // Collect user-side item kinds; assistant-side kinds handled separately below.
    // context_summary is intentionally excluded: it is always standalone, never merged
    // into a user exchange (even if it shares the same exchangeId).
    val userSideKinds = setOf("user_message", "attachment")
    val userSideByExchange: Map<String, List<TimelineItemDto>> = sorted
        .filter { it.kind in userSideKinds }
        .groupBy { it.exchangeId ?: "seq-${it.seq}" }

    // Determine the "representative seq" for each user-side exchange group
    // (used to interleave with assistant groups in seq order)
    val exchangeMinSeq: Map<String, Long> = userSideByExchange.mapValues { (_, items) ->
        items.minOf { it.seq }
    }

    // ── Assistant-side: group by (assistantTurnId, providerCallIndex) ────────
    data class AssistantGroupKey(val turnId: String?, val pci: Int?)

    val assistantSideItems = sorted.filter {
        it.kind in setOf("assistant_message", "thinking", "tool_call", "tool_result")
    }

    // Build ordered assistant groups preserving seq order of first occurrence
    val assistantGroups = mutableListOf<Pair<Long, List<TimelineItemDto>>>()
    var currentKey: AssistantGroupKey? = null
    var currentGroup = mutableListOf<TimelineItemDto>()

    fun flushAssistantGroup() {
        if (currentGroup.isEmpty()) return
        assistantGroups += currentGroup.first().seq to currentGroup.toList()
        currentGroup = mutableListOf()
        currentKey = null
    }

    for (item in assistantSideItems) {
        val key = AssistantGroupKey(item.assistantTurnId, item.providerCallIndex)
        if (currentKey != null && currentKey != key) flushAssistantGroup()
        currentKey = key
        currentGroup += item
    }
    flushAssistantGroup()

    // ── Merge in seq order ──────────────────────────────────────────────────
    // Build a combined list of (minSeq, producer) and sort by seq
    data class Entry(val seq: Long, val produce: () -> Message?)

    val entries = mutableListOf<Entry>()

    for ((exchangeKey, items) in userSideByExchange) {
        val minSeq = exchangeMinSeq[exchangeKey]!!
        entries += Entry(minSeq) {
            val userMsg = items.firstOrNull { it.kind == "user_message" }
            val attachments = items.filter { it.kind == "attachment" }

            when {
                userMsg != null -> userMsg.toUserMessage(attachments, baseUrl)
                else -> null  // orphan attachment-only exchange: skip
            }
        }
    }

    // context_summary items are standalone — not grouped with user exchanges
    for (item in sorted.filter { it.kind == "context_summary" }) {
        entries += Entry(item.seq) { item.toSummaryMessage() }
    }

    for ((seq, group) in assistantGroups) {
        entries += Entry(seq) { group.toAssistantMessage(baseUrl) }
    }

    entries.sortedBy { it.seq }.forEach { entry ->
        val msg = entry.produce()
        if (msg != null) output += msg
    }

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

private fun TimelineItemDto.toUserMessage(
    attachments: List<TimelineItemDto>,
    baseUrl: String,
): Message {
    val blocks = mutableListOf<ContentBlock>()
    for (att in attachments.sortedBy { it.seq }) {
        val attId = att.payloadString("attachment_id") ?: continue
        val kind = att.payloadString("kind")
        val block: ContentBlock = if (kind == "image") {
            ContentBlock.ImageBlock(
                blockId = "timeline-${att.sessionId}-att-$attId",
                attachmentId = attId,
                filename = att.content ?: "",
                mimeType = att.payloadString("mime_type") ?: "",
                sizeBytes = att.payloadLong("size_bytes") ?: 0L,
                downloadUrl = "$baseUrl/api/v1/attachments/$attId",
                thumbnailUrl = "$baseUrl/api/v1/attachments/$attId/thumbnail",
            )
        } else {
            ContentBlock.FileBlock(
                blockId = "timeline-${att.sessionId}-att-$attId",
                attachmentId = attId,
                filename = att.content ?: "",
                mimeType = att.payloadString("mime_type") ?: "",
                sizeBytes = att.payloadLong("size_bytes") ?: 0L,
                downloadUrl = "$baseUrl/api/v1/attachments/$attId",
                textExcerpt = att.payloadString("text_excerpt"),
            )
        }
        blocks += block
    }
    return Message(
        id = "timeline-$sessionId-$seq",
        sessionId = sessionId,
        role = MessageRole.USER,
        blocks = blocks,
        text = content ?: "",
        createdAt = createdAt ?: "",
    )
}

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

private fun List<TimelineItemDto>.toAssistantMessage(baseUrl: String): Message? {
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

    val blocks = buildAssistantBlocks(sessionId, baseUrl)

    return Message(
        id = msgId,
        sessionId = sessionId,
        role = MessageRole.ASSISTANT,
        blocks = blocks,
        createdAt = first.createdAt ?: "",
    )
}

private fun List<TimelineItemDto>.buildAssistantBlocks(sessionId: String, baseUrl: String): List<ContentBlock> {
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

                val toolName = item.payloadString("tool_name") ?: item.payloadString("name") ?: ""

                // tool result with successful artifact → inline attachment block, no ToolBlock
                if (result?.payloadBoolean("ok") == true) {
                    @Suppress("UNCHECKED_CAST")
                    val artifactMap = result.payload?.get("artifact") as? Map<String, Any?>
                    if (artifactMap != null) {
                        val artifactBlock = artifactMapToBlock(sessionId, artifactMap, baseUrl)
                        if (artifactBlock != null) {
                            blocks += artifactBlock
                            return@forEach
                        }
                    }
                }

                val status = when {
                    result == null -> ToolStatus.PENDING
                    result.payloadBoolean("ok") == true -> ToolStatus.DONE
                    result.payloadBoolean("ok") == false || result.payload?.containsKey("error") == true -> ToolStatus.FAILED
                    else -> ToolStatus.DONE
                }

                blocks += ContentBlock.ToolBlock(
                    blockId = item.stableBlockId(),
                    toolId = callId,
                    name = toolName,
                    displayName = item.payloadString("display_name") ?: toolName,
                    inputs = item.content ?: "",
                    status = status,
                    resultSummary = result?.payloadString("display") ?: result?.content,
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
                        displayName = "",
                        inputs = "",
                        status = if (failed) ToolStatus.FAILED else ToolStatus.DONE,
                        resultSummary = item.payloadString("display") ?: item.content,
                        error = if (failed) item.payloadString("error") else null,
                    )
                }
            }
        }
    }

    return blocks
}

private fun artifactMapToBlock(
    sessionId: String,
    artifact: Map<String, Any?>,
    baseUrl: String,
): ContentBlock? {
    val attId = artifact["attachment_id"] as? String ?: return null
    val kind = artifact["kind"] as? String ?: return null
    val filename = artifact["filename"] as? String ?: ""
    val mimeType = artifact["mime_type"] as? String ?: ""
    val sizeBytes: Long = when (val v = artifact["size_bytes"]) {
        is Long -> v
        is Int -> v.toLong()
        is Double -> v.toLong()
        else -> 0L
    }

    fun absoluteUrl(url: String?): String {
        if (url.isNullOrBlank()) return ""
        return if (url.startsWith("http://") || url.startsWith("https://")) url else "$baseUrl$url"
    }

    return when (kind) {
        "image" -> ContentBlock.ImageBlock(
            blockId = "timeline-$sessionId-artifact-$attId",
            attachmentId = attId,
            filename = filename,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
            downloadUrl = absoluteUrl(artifact["download_url"] as? String),
            thumbnailUrl = (artifact["thumbnail_url"] as? String)?.let { absoluteUrl(it) }?.takeIf { it.isNotBlank() },
        )
        "text_file", "download" -> ContentBlock.FileBlock(
            blockId = "timeline-$sessionId-artifact-$attId",
            attachmentId = attId,
            filename = filename,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
            downloadUrl = absoluteUrl(artifact["download_url"] as? String),
            textExcerpt = (artifact["text_excerpt"] as? String)?.takeIf { it.isNotBlank() },
        )
        else -> null
    }
}
