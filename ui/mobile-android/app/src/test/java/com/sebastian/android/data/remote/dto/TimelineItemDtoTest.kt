package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.ContentBlock
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TimelineItemDtoTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    @Test
    fun sessionDetailParsesTimelineItems() {
        val json = """
            {
              "session": {
                "id": "s1",
                "agent_type": "sebastian",
                "status": "active"
              },
              "messages": [],
              "timeline_items": [
                {
                  "id": "i1",
                  "session_id": "s1",
                  "agent_type": "sebastian",
                  "seq": 1,
                  "kind": "thinking",
                  "role": "assistant",
                  "content": "thinking text",
                  "payload": {"duration_ms": 1234},
                  "archived": false,
                  "assistant_turn_id": "t1",
                  "provider_call_index": 0,
                  "block_index": 0,
                  "created_at": "2026-04-22T00:00:01Z"
                }
              ]
            }
        """.trimIndent()

        val adapter = moshi.adapter(SessionDetailResponse::class.java)
        val parsed = adapter.fromJson(json)!!

        assertEquals(1, parsed.timelineItems.size)
        val item = parsed.timelineItems.first()
        assertEquals("thinking", item.kind)
        assertEquals(1234L, item.payloadLong("duration_ms"))
    }

    @Test
    fun summaryBlockIsAlwaysDone() {
        val block = ContentBlock.SummaryBlock(blockId = "summary-1", text = "summary")
        assertTrue(block.isDone)
    }

    @Test
    fun timelineItemDefaultsArchivedFalse() {
        val item = TimelineItemDto(
            id = "i1",
            sessionId = "s1",
            seq = 1L,
            kind = "user_message",
        )
        assertTrue(!item.archived)
    }
}
