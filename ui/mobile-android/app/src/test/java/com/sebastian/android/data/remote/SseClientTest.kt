package com.sebastian.android.data.remote

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.dto.SseFrameParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

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
    fun `parses approval_requested event with agent_type`() {
        val json = """{"type":"approval.requested","data":{"session_id":"s1","approval_id":"ap_1","agent_type":"code_agent","description":"删除文件"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ApprovalRequested)
        val approval = event as StreamEvent.ApprovalRequested
        assertEquals("ap_1", approval.approvalId)
        assertEquals("code_agent", approval.agentType)
        assertEquals("删除文件", approval.description)
    }

    @Test
    fun `parses approval_requested event defaults agent_type to sebastian`() {
        val json = """{"type":"approval.requested","data":{"session_id":"s1","approval_id":"ap_2","description":"运行命令"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ApprovalRequested)
        assertEquals("sebastian", (event as StreamEvent.ApprovalRequested).agentType)
    }
}
