package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.ToolStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TimelineMapperTest {

    @Test
    fun mapsTimelineInSeqOrderIgnoringEffectiveSeq() {
        // Items deliberately out-of-order by seq
        val items = listOf(
            item(seq = 3, kind = "context_summary", content = "summary"),
            item(seq = 1, kind = "user_message", role = "user", content = "hello"),
            item(seq = 2, kind = "assistant_message", role = "assistant", content = "hi", assistantTurnId = "t1"),
        )
        val messages = items.toMessagesFromTimeline()
        // Must be sorted by seq: user(1), assistant(2), summary(3)
        assertEquals(MessageRole.USER, messages[0].role)
        assertEquals("hello", messages[0].text)
        assertEquals("hi", (messages[1].blocks.single() as ContentBlock.TextBlock).text)
        assertTrue(messages[2].blocks.single() is ContentBlock.SummaryBlock)
    }

    @Test
    fun mapsThinkingWithDurationAndStableBlockId() {
        val messages = listOf(
            item(
                seq = 1, kind = "thinking", content = "considering",
                assistantTurnId = "t1", providerCallIndex = 0, blockIndex = 2,
                payload = mapOf("duration_ms" to 1500.0),
            )
        ).toMessagesFromTimeline()
        val block = messages.single().blocks.single() as ContentBlock.ThinkingBlock
        assertEquals("considering", block.text)
        assertEquals(1500L, block.durationMs)
        assertEquals("timeline-s1-t1-0-2", block.blockId)
    }

    @Test
    fun mergesToolCallAndResultByToolCallId() {
        val messages = listOf(
            item(
                seq = 1, kind = "tool_call", content = "search",
                assistantTurnId = "t1", blockIndex = 0,
                payload = mapOf("tool_call_id" to "tool-1", "tool_name" to "web_search"),
            ),
            item(
                seq = 2, kind = "tool_result", content = "done",
                assistantTurnId = "t1",
                payload = mapOf("tool_call_id" to "tool-1", "ok" to true),
            ),
        ).toMessagesFromTimeline()
        val block = messages.single().blocks.single() as ContentBlock.ToolBlock
        assertEquals("web_search", block.name)
        assertEquals("done", block.resultSummary)
        assertEquals(ToolStatus.DONE, block.status)
    }

    @Test
    fun hidesSystemAndRawItems() {
        val messages = listOf(
            item(seq = 1, kind = "system_event", content = "hidden"),
            item(seq = 2, kind = "raw_block", content = "hidden"),
        ).toMessagesFromTimeline()
        assertTrue(messages.isEmpty())
    }

    @Test
    fun flushesAssistantGroupWhenGroupKeyChanges() {
        val messages = listOf(
            item(seq = 1, kind = "assistant_message", content = "first", assistantTurnId = "t1", providerCallIndex = 0),
            item(seq = 2, kind = "assistant_message", content = "second", assistantTurnId = "t1", providerCallIndex = 1),
        ).toMessagesFromTimeline()
        assertEquals(2, messages.size)
        assertEquals(MessageRole.ASSISTANT, messages[0].role)
        assertEquals(MessageRole.ASSISTANT, messages[1].role)
    }

    @Test
    fun stableMessageIdForAssistantGroup() {
        val messages = listOf(
            item(seq = 5, kind = "assistant_message", content = "hello", assistantTurnId = "t99", providerCallIndex = 2),
        ).toMessagesFromTimeline()
        assertEquals("timeline-s1-t99-2", messages.single().id)
    }

    @Test
    fun stableMessageIdFallbackWhenAssistantTurnIdNull() {
        val messages = listOf(
            item(seq = 7, kind = "assistant_message", content = "hello", assistantTurnId = null, providerCallIndex = null),
        ).toMessagesFromTimeline()
        assertEquals("timeline-s1-7", messages.single().id)
    }

    @Test
    fun userMessageHasCorrectIdAndText() {
        val messages = listOf(
            item(seq = 3, kind = "user_message", role = "user", content = "ping", assistantTurnId = null),
        ).toMessagesFromTimeline()
        val msg = messages.single()
        assertEquals("timeline-s1-3", msg.id)
        assertEquals("ping", msg.text)
        assertEquals(MessageRole.USER, msg.role)
        assertTrue(msg.blocks.isEmpty())
    }

    @Test
    fun summaryMessageHasCorrectBlockAndSourceRange() {
        val messages = listOf(
            item(
                seq = 10, kind = "context_summary", content = "summarized",
                payload = mapOf("source_seq_start" to 1.0, "source_seq_end" to 9.0),
            )
        ).toMessagesFromTimeline()
        val msg = messages.single()
        assertEquals("timeline-s1-summary-10", msg.id)
        val block = msg.blocks.single() as ContentBlock.SummaryBlock
        assertEquals("summarized", block.text)
        assertEquals(1L, block.sourceSeqStart)
        assertEquals(9L, block.sourceSeqEnd)
        assertEquals("timeline-s1-summary-block-10", block.blockId)
    }

    @Test
    fun orphanToolResultCreatesMinimalToolBlock() {
        val messages = listOf(
            item(
                seq = 4, kind = "tool_result", content = "result content",
                assistantTurnId = "t1",
                payload = mapOf("tool_call_id" to "orphan-id", "ok" to true),
            ),
        ).toMessagesFromTimeline()
        val block = messages.single().blocks.single() as ContentBlock.ToolBlock
        assertEquals("orphan-id", block.toolId)
        assertEquals(ToolStatus.DONE, block.status)
        assertEquals("result content", block.resultSummary)
        assertEquals("timeline-s1-tool-result-4", block.blockId)
    }

    @Test
    fun failedToolResultSetsFailedStatus() {
        val messages = listOf(
            item(
                seq = 1, kind = "tool_call", content = "{}",
                assistantTurnId = "t1", blockIndex = 0,
                payload = mapOf("tool_call_id" to "tc-1", "tool_name" to "risky_tool"),
            ),
            item(
                seq = 2, kind = "tool_result", content = null,
                assistantTurnId = "t1",
                payload = mapOf("tool_call_id" to "tc-1", "ok" to false, "error" to "timeout"),
            ),
        ).toMessagesFromTimeline()
        val block = messages.single().blocks.single() as ContentBlock.ToolBlock
        assertEquals(ToolStatus.FAILED, block.status)
        assertEquals("timeout", block.error)
    }

    @Test
    fun pendingToolCallWithNoResult() {
        val messages = listOf(
            item(
                seq = 1, kind = "tool_call", content = "{}",
                assistantTurnId = "t1", blockIndex = 0,
                payload = mapOf("tool_call_id" to "tc-x", "tool_name" to "slow_tool"),
            ),
        ).toMessagesFromTimeline()
        val block = messages.single().blocks.single() as ContentBlock.ToolBlock
        assertEquals(ToolStatus.PENDING, block.status)
    }

    @Test
    fun multipleBlockKindsInOneGroup() {
        val messages = listOf(
            item(seq = 1, kind = "thinking", content = "let me think", assistantTurnId = "t1", blockIndex = 0),
            item(seq = 2, kind = "assistant_message", content = "the answer", assistantTurnId = "t1", blockIndex = 1),
        ).toMessagesFromTimeline()
        val msg = messages.single()
        assertEquals(2, msg.blocks.size)
        assertTrue(msg.blocks[0] is ContentBlock.ThinkingBlock)
        assertTrue(msg.blocks[1] is ContentBlock.TextBlock)
    }

    @Test
    fun createdAtTakenFromFirstItemInGroup() {
        val messages = listOf(
            item(seq = 1, kind = "thinking", content = "a", assistantTurnId = "t1", createdAt = "2026-04-22T10:00:00Z"),
            item(seq = 2, kind = "assistant_message", content = "b", assistantTurnId = "t1", createdAt = "2026-04-22T10:00:01Z"),
        ).toMessagesFromTimeline()
        assertEquals("2026-04-22T10:00:00Z", messages.single().createdAt)
    }

    // ---------------------------------------------------------------------------
    // Attachment tests
    // ---------------------------------------------------------------------------

    @Test
    fun `user_message and attachment with same exchangeId merge into one message`() {
        val items = listOf(
            item(
                seq = 1, kind = "user_message", content = "hello",
                exchangeId = "exch-1",
            ),
            item(
                seq = 2, kind = "attachment", content = "photo.png",
                exchangeId = "exch-1",
                payload = mapOf(
                    "attachment_id" to "att-abc",
                    "kind" to "image",
                    "mime_type" to "image/png",
                    "size_bytes" to 12345.0,
                ),
            ),
        )
        val messages = items.toMessagesFromTimeline()
        assertEquals(1, messages.size)
        assertEquals(MessageRole.USER, messages[0].role)
        val imageBlocks = messages[0].blocks.filterIsInstance<ContentBlock.ImageBlock>()
        assertEquals(1, imageBlocks.size)
        assertTrue(imageBlocks[0].downloadUrl.contains("att-abc"))
    }

    @Test
    fun `text_file attachment produces FileBlock`() {
        val items = listOf(
            item(
                seq = 1, kind = "user_message", content = "check this",
                exchangeId = "exch-2",
            ),
            item(
                seq = 2, kind = "attachment", content = "notes.md",
                exchangeId = "exch-2",
                payload = mapOf(
                    "attachment_id" to "att-xyz",
                    "kind" to "text_file",
                    "mime_type" to "text/markdown",
                    "size_bytes" to 500.0,
                    "text_excerpt" to "# Hello",
                ),
            ),
        )
        val messages = items.toMessagesFromTimeline()
        assertEquals(1, messages.size)
        val fileBlocks = messages[0].blocks.filterIsInstance<ContentBlock.FileBlock>()
        assertEquals(1, fileBlocks.size)
        assertEquals("notes.md", fileBlocks[0].filename)
        assertEquals("# Hello", fileBlocks[0].textExcerpt)
    }

    @Test
    fun `user_message without attachment emits message with no blocks`() {
        val items = listOf(
            item(seq = 1, kind = "user_message", content = "hi"),
        )
        val messages = items.toMessagesFromTimeline()
        assertEquals(1, messages.size)
        assertTrue(messages[0].blocks.isEmpty())
    }

    @Test
    fun `context_summary with same exchangeId as user message must produce separate entry`() {
        val items = listOf(
            item(
                seq = 1, kind = "user_message", role = "user",
                content = "hello", exchangeId = "exc-1",
            ),
            item(
                seq = 2, kind = "context_summary", role = "user",
                content = "Summary text", exchangeId = "exc-1",  // same exchangeId as user_message
            ),
        )
        val messages = items.toMessagesFromTimeline(baseUrl = "")
        // Must produce two separate messages (user bubble + standalone summary)
        assertEquals(2, messages.size)
    }

    @Test
    fun `attachment without user_message in exchange is skipped`() {
        val items = listOf(
            item(
                seq = 1, kind = "attachment", content = "photo.png",
                exchangeId = "exch-orphan",
                payload = mapOf("attachment_id" to "att-orphan", "kind" to "image", "mime_type" to "image/png"),
            ),
        )
        val messages = items.toMessagesFromTimeline()
        assertEquals(0, messages.size)
    }

    @Test
    fun `provider capability fields map to ModelInputCapabilities`() {
        val dto = ResolvedBindingDto(
            accountName = null, providerDisplayName = null,
            modelDisplayName = null, contextWindowTokens = null,
            thinkingCapability = null,
            supportsImageInput = true, supportsTextFileInput = true,
        )
        val domain = dto.toDomain()
        val caps = domain.toInputCapabilities()
        assertTrue(caps.supportsImageInput)
        assertTrue(caps.supportsTextFileInput)
    }

    @Test
    fun `provider capability fields default to false true when missing`() {
        val dto = ResolvedBindingDto(
            accountName = null, providerDisplayName = null,
            modelDisplayName = null, contextWindowTokens = null,
            thinkingCapability = null,
        )
        val caps = dto.toDomain().toInputCapabilities()
        assertFalse(caps.supportsImageInput)
        assertTrue(caps.supportsTextFileInput)
    }

    // ---------------------------------------------------------------------------
    // Helper
    // ---------------------------------------------------------------------------

    private fun item(
        seq: Long,
        kind: String,
        role: String? = "assistant",
        content: String? = null,
        assistantTurnId: String? = null,
        providerCallIndex: Int? = 0,
        blockIndex: Int? = null,
        payload: Map<String, Any?>? = null,
        createdAt: String = "2026-01-01T00:00:00Z",
        exchangeId: String? = null,
    ) = TimelineItemDto(
        id = "item-$seq",
        sessionId = "s1",
        agentType = "sebastian",
        seq = seq,
        kind = kind,
        role = role,
        content = content,
        payload = payload,
        assistantTurnId = assistantTurnId,
        providerCallIndex = providerCallIndex,
        blockIndex = blockIndex,
        createdAt = createdAt,
        exchangeId = exchangeId,
    )
}
