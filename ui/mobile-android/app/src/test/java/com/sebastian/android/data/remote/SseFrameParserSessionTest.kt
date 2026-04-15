package com.sebastian.android.data.remote

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.dto.SseFrameParser
import org.junit.Assert.assertEquals
import org.junit.Test

class SseFrameParserSessionTest {
    @Test
    fun `parses session completed frame`() {
        val raw = """{"type":"session.completed","data":{"session_id":"s1","agent_type":"researcher","goal":"查资料"}}"""
        val event = SseFrameParser.parse(raw)
        assertEquals(
            StreamEvent.SessionCompleted(sessionId = "s1", agentType = "researcher", goal = "查资料"),
            event,
        )
    }

    @Test
    fun `parses session failed frame with error`() {
        val raw = """{"type":"session.failed","data":{"session_id":"s2","agent_type":"coder","goal":"写函数","error":"LLM timeout"}}"""
        val event = SseFrameParser.parse(raw)
        assertEquals(
            StreamEvent.SessionFailed(sessionId = "s2", agentType = "coder", goal = "写函数", error = "LLM timeout"),
            event,
        )
    }
}
