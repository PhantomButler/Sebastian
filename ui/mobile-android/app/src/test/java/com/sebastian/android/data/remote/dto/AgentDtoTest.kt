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
    fun `parses nested binding when present`() {
        val json = """{
            "agent_type": "forge",
            "description": "Code",
            "active_session_count": 0,
            "max_children": 5,
            "binding": {
                "agent_type": "forge",
                "provider_id": "prov-1",
                "thinking_effort": "high"
            }
        }""".trimIndent()
        val dto = adapter.fromJson(json)!!
        assertEquals("prov-1", dto.binding?.providerId)
        val domain = dto.toDomain()
        assertEquals("prov-1", domain.boundProviderId)
        assertEquals(5, domain.maxChildren)
    }

    @Test
    fun `binding defaults to null when absent`() {
        val json = """{
            "agent_type": "aide",
            "description": "Research",
            "active_session_count": 0,
            "max_children": 2
        }""".trimIndent()
        val dto = adapter.fromJson(json)!!
        assertNull(dto.binding)
        assertNull(dto.toDomain().boundProviderId)
    }

    @Test
    fun `orchestrator entry tolerates null max_children`() {
        val json = """{
            "agent_type": "sebastian",
            "description": "主管家",
            "is_orchestrator": true,
            "active_session_count": 0,
            "max_children": null,
            "binding": null
        }""".trimIndent()
        val dto = adapter.fromJson(json)!!
        assertNull(dto.maxChildren)
        val domain = dto.toDomain()
        assertEquals(0, domain.maxChildren)
        assertNull(domain.boundProviderId)
    }
}
