package com.sebastian.android.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class ThinkingCardTest {

    @Test
    fun `formatThinkingDuration returns seconds only when under 60s`() {
        assertEquals("0s", formatThinkingDuration(0L))
        assertEquals("3s", formatThinkingDuration(3_000L))
        assertEquals("59s", formatThinkingDuration(59_999L))
    }

    @Test
    fun `formatThinkingDuration returns minutes and seconds at 60s boundary`() {
        assertEquals("1m 0s", formatThinkingDuration(60_000L))
        assertEquals("1m 25s", formatThinkingDuration(85_000L))
        assertEquals("2m 5s", formatThinkingDuration(125_000L))
    }
}
