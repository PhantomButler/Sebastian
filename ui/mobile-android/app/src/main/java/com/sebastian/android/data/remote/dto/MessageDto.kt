package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.ToolStatus
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/**
 * Backend message format from GET /api/v1/sessions/{id}:
 * {"role": "user|assistant", "content": "...", "ts": "...", "blocks": [...]}
 *
 * No `id` or `session_id` — those are generated client-side.
 */
@JsonClass(generateAdapter = true)
data class MessageDto(
    @param:Json(name ="role") val role: String,
    @param:Json(name ="content") val content: String = "",
    @param:Json(name ="ts") val ts: String = "",
    @param:Json(name ="blocks") val blocks: List<BlockDto>? = null,
) {
    fun toDomain(sessionId: String, index: Int): Message {
        val msgId = "$sessionId-$index"
        val msgRole = if (role == "user") MessageRole.USER else MessageRole.ASSISTANT

        if (msgRole == MessageRole.ASSISTANT) {
            val contentBlocks = mutableListOf<ContentBlock>()
            var hasTextBlock = false
            blocks?.forEachIndexed { i, b ->
                when (b.type) {
                    "thinking" -> contentBlocks.add(
                        ContentBlock.ThinkingBlock(
                            blockId = "$msgId-thinking-$i",
                            text = b.thinking ?: "",
                            done = true,
                            durationMs = b.durationMs,
                        )
                    )
                    "text" -> {
                        hasTextBlock = true
                        contentBlocks.add(
                            ContentBlock.TextBlock(
                                blockId = "$msgId-text-$i",
                                text = b.text ?: "",
                                done = true,
                            )
                        )
                    }
                    "tool" -> contentBlocks.add(
                        ContentBlock.ToolBlock(
                            blockId = "$msgId-tool-$i",
                            toolId = b.toolId ?: "$msgId-tool-$i",
                            name = b.name ?: "",
                            inputs = b.input ?: "",
                            status = if (b.status == "failed") ToolStatus.FAILED else ToolStatus.DONE,
                            resultSummary = b.result,
                        )
                    )
                }
            }
            // 历史数据兼容：老消息的 blocks 只存 thinking/tool，text 全在 content 字段
            if (!hasTextBlock && content.isNotEmpty()) {
                contentBlocks.add(
                    ContentBlock.TextBlock(
                        blockId = "$msgId-text",
                        text = content,
                        done = true,
                    )
                )
            }
            return Message(
                id = msgId,
                sessionId = sessionId,
                role = msgRole,
                blocks = contentBlocks,
                text = content,
                createdAt = ts,
            )
        }

        return Message(
            id = msgId,
            sessionId = sessionId,
            role = msgRole,
            text = content,
            createdAt = ts,
        )
    }
}

@JsonClass(generateAdapter = true)
data class BlockDto(
    @param:Json(name ="type") val type: String,
    @param:Json(name ="text") val text: String? = null,
    @param:Json(name ="thinking") val thinking: String? = null,
    @param:Json(name ="signature") val signature: String? = null,
    @param:Json(name ="duration_ms") val durationMs: Long? = null,
    @param:Json(name ="tool_id") val toolId: String? = null,
    @param:Json(name ="name") val name: String? = null,
    @param:Json(name ="input") val input: String? = null,
    @param:Json(name ="status") val status: String? = null,
    @param:Json(name ="result") val result: String? = null,
)
