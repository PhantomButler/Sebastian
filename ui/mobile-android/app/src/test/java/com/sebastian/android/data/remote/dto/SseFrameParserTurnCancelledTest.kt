package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.StreamEvent
import org.junit.Assert.assertEquals
import org.junit.Test

class SseFrameParserTurnCancelledTest {
    @Test
    fun `parses turn_cancelled into TurnCancelled`() {
        val raw = """{"type":"turn.cancelled","data":{"session_id":"s1","partial_content":"half"}}"""
        val event = SseFrameParser.parse(raw)
        assertEquals(StreamEvent.TurnCancelled("s1", "half"), event)
    }

    @Test
    fun `parses turn_cancelled without partial_content`() {
        val raw = """{"type":"turn.cancelled","data":{"session_id":"s1"}}"""
        val event = SseFrameParser.parse(raw)
        assertEquals(StreamEvent.TurnCancelled("s1", ""), event)
    }
}
