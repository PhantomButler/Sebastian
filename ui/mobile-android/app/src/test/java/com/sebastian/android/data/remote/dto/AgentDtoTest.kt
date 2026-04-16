package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AgentDtoTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val adapter = moshi.adapter(AgentDto::class.java)

    @Test
    fun `parses bound_provider_id when present`() {
        val json = """{
            "agent_type": "forge",
            "description": "Code",
            "active_session_count": 0,
            "max_children": 5,
            "bound_provider_id": "prov-1"
        }""".trimIndent()
        val dto = adapter.fromJson(json)!!
        assertEquals("prov-1", dto.boundProviderId)
        assertEquals("prov-1", dto.toDomain().boundProviderId)
    }

    @Test
    fun `bound_provider_id defaults to null when absent`() {
        val json = """{
            "agent_type": "aide",
            "description": "Research",
            "active_session_count": 0,
            "max_children": 2
        }""".trimIndent()
        val dto = adapter.fromJson(json)!!
        assertNull(dto.boundProviderId)
        assertNull(dto.toDomain().boundProviderId)
    }
}
