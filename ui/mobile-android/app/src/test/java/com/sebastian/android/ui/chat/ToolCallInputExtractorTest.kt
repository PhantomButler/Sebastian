package com.sebastian.android.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ToolCallInputExtractorTest {

    @Test
    fun `bash summary picks command`() {
        val summary = ToolCallInputExtractor.extractInputSummary(
            "Bash",
            """{"command":"ls -la","description":"list"}""",
        )
        assertEquals("ls -la", summary)
    }

    @Test
    fun `delegate_to_agent summary shows capitalized agent_type, not goal`() {
        val summary = ToolCallInputExtractor.extractInputSummary(
            "delegate_to_agent",
            """{"agent_type":"coder","goal":"write tests"}""",
        )
        assertEquals("Coder", summary)
    }

    @Test
    fun `non-json input falls back to raw string truncated at 80 chars`() {
        val short = "not json at all"
        assertEquals(short, ToolCallInputExtractor.extractInputSummary("Bash", short))

        val long = "x".repeat(200)
        val summary = ToolCallInputExtractor.extractInputSummary("Bash", long)
        assertEquals("x".repeat(80) + "…", summary)
    }

    @Test
    fun `unknown tool falls back to generic keys`() {
        val summary = ToolCallInputExtractor.extractInputSummary(
            "SomeFutureTool",
            """{"query":"hello world","extra":"ignored"}""",
        )
        assertEquals("hello world", summary)
    }

    @Test
    fun `extractKeyParams produces multi-line key value pairs`() {
        val text = ToolCallInputExtractor.extractKeyParams(
            "Grep",
            """{"pattern":"foo","path":"/tmp","extra":"x"}""",
        )
        assertEquals("pattern: foo\npath: /tmp", text)
    }

    @Test
    fun `extractKeyParams falls back to iterating all string fields when priority keys miss`() {
        val text = ToolCallInputExtractor.extractKeyParams(
            "SomeFutureTool",
            """{"url":"https://x","label":"y"}""",
        )
        val lines = text.split('\n').toSet()
        assertEquals(setOf("url: https://x", "label: y"), lines)
    }

    @Test
    fun `empty input returns empty`() {
        assertTrue(ToolCallInputExtractor.extractInputSummary("Bash", "").isEmpty())
        assertTrue(ToolCallInputExtractor.extractKeyParams("Bash", "").isEmpty())
    }

    @Test
    fun `non-string fields (number, array, boolean) are ignored, aligning with RN typeof-string`() {
        // generic tool with only numeric/array/boolean → no match → empty summary
        val summary = ToolCallInputExtractor.extractInputSummary(
            "SomeFutureTool",
            """{"count":42,"files":["a","b"],"verbose":true}""",
        )
        assertEquals("", summary)

        // extractKeyParams also skips non-string fields even on fallback iteration
        val params = ToolCallInputExtractor.extractKeyParams(
            "SomeFutureTool",
            """{"count":42,"label":"hi"}""",
        )
        assertEquals("label: hi", params)
    }

    @Test
    fun `extractKeyParams truncates raw fallback on JSON parse failure`() {
        val junk = "not-json-" + "y".repeat(200)
        val params = ToolCallInputExtractor.extractKeyParams("Bash", junk)
        // 80-char summary truncation is reused to avoid dumping超长原文
        assertTrue(params.length <= 81) // 80 + ellipsis
        assertTrue(params.endsWith("…"))
    }
}
