package com.sebastian.android.data.remote

import app.cash.turbine.test
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.dto.SseFrameParser
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SseEnvelopeTest {

    @Test
    fun `SseEnvelope carries eventId and event`() {
        val event = StreamEvent.TextDelta(sessionId = "s1", blockId = "b1", delta = "hi")
        val envelope = SseEnvelope(eventId = "42", event = event)
        assertEquals("42", envelope.eventId)
        assertTrue(envelope.event is StreamEvent.TextDelta)
        assertEquals("hi", (envelope.event as StreamEvent.TextDelta).delta)
    }

    @Test
    fun `SseEnvelope eventId can be null when server omits id field`() {
        val event = StreamEvent.Unknown
        val envelope = SseEnvelope(eventId = null, event = event)
        assertNull(envelope.eventId)
        assertEquals(StreamEvent.Unknown, envelope.event)
    }

    @Test
    fun `flow of SseEnvelope emits correct eventIds in order`() = runTest {
        val json = """{"type":"turn.delta","data":{"session_id":"s1","block_id":"b1","delta":"hi"},"ts":"2026-01-01T00:00:00Z"}"""
        val rawPairs = listOf(
            Pair("1", SseFrameParser.parse(json)),
            Pair("2", SseFrameParser.parse(json)),
            Pair(null, SseFrameParser.parse(json)),
        )
        val envelopeFlow = flowOf(*rawPairs.toTypedArray())
            .map { (id, event) -> SseEnvelope(eventId = id, event = event) }

        envelopeFlow.test {
            val first = awaitItem()
            assertEquals("1", first.eventId)
            assertTrue(first.event is StreamEvent.TextDelta)

            val second = awaitItem()
            assertEquals("2", second.eventId)

            val third = awaitItem()
            assertNull(third.eventId)

            awaitComplete()
        }
    }

    @Test
    fun `last non-null eventId is tracked as replay cursor`() = runTest {
        val json = """{"type":"turn.delta","data":{"session_id":"s1","block_id":"b1","delta":"x"},"ts":"2026-01-01T00:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        val envelopes = listOf(
            SseEnvelope(eventId = "10", event = event),
            SseEnvelope(eventId = "11", event = event),
            SseEnvelope(eventId = null, event = event),
            SseEnvelope(eventId = "13", event = event),
        )
        var cursor: String? = null
        flowOf(*envelopes.toTypedArray()).test {
            repeat(4) {
                val env = awaitItem()
                if (env.eventId != null) cursor = env.eventId
            }
            awaitComplete()
        }
        assertEquals("13", cursor)
    }
}

class SseFrameParserTest {

    @Test
    fun `parses turn_delta event`() {
        val json = """{"type":"turn.delta","data":{"session_id":"s1","block_id":"b0_1","delta":"好的"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.TextDelta)
        val delta = event as StreamEvent.TextDelta
        assertEquals("s1", delta.sessionId)
        assertEquals("b0_1", delta.blockId)
        assertEquals("好的", delta.delta)
    }

    @Test
    fun `parses thinking_block_start event`() {
        val json = """{"type":"thinking_block.start","data":{"session_id":"s1","block_id":"b0_0"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ThinkingBlockStart)
        assertEquals("b0_0", (event as StreamEvent.ThinkingBlockStart).blockId)
    }

    @Test
    fun `returns Unknown for unrecognized event type`() {
        val json = """{"type":"unknown.event","data":{},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertEquals(StreamEvent.Unknown, event)
    }

    @Test
    fun `returns Unknown for malformed json`() {
        val event = SseFrameParser.parse("not json")
        assertEquals(StreamEvent.Unknown, event)
    }

    @Test
    fun `parses tool_running event`() {
        val json = """{"type":"tool.running","data":{"session_id":"s1","tool_id":"tu_01","name":"web_search"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ToolRunning)
        val e = event as StreamEvent.ToolRunning
        assertEquals("tu_01", e.toolId)
        assertEquals("web_search", e.name)
    }

    @Test
    fun `parses approval_requested event with tool details`() {
        val json = """{"type":"approval.requested","data":{"session_id":"s1","approval_id":"ap_1","agent_type":"code_agent","tool_name":"bash_run","tool_input":{"command":"rm -rf build"},"reason":"清理构建"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ApprovalRequested)
        val approval = event as StreamEvent.ApprovalRequested
        assertEquals("ap_1", approval.approvalId)
        assertEquals("code_agent", approval.agentType)
        assertEquals("bash_run", approval.toolName)
        assertEquals("清理构建", approval.reason)
        assertTrue(approval.toolInputJson.contains("rm -rf build"))
    }

    @Test
    fun `parses approval_requested event defaults agent_type to sebastian`() {
        val json = """{"type":"approval.requested","data":{"session_id":"s1","approval_id":"ap_2","tool_name":"shell"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ApprovalRequested)
        val approval = event as StreamEvent.ApprovalRequested
        assertEquals("sebastian", approval.agentType)
        assertEquals("{}", approval.toolInputJson)
    }
}
