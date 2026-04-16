package com.sebastian.android.ui.settings.components

import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import org.junit.Assert.assertEquals
import org.junit.Test

class EffortStepsTest {
    @Test
    fun `toggle capability has 2 steps`() {
        assertEquals(
            listOf(ThinkingEffort.OFF, ThinkingEffort.ON),
            effortStepsFor(ThinkingCapability.TOGGLE),
        )
    }

    @Test
    fun `effort capability has 4 steps`() {
        assertEquals(
            listOf(ThinkingEffort.OFF, ThinkingEffort.LOW, ThinkingEffort.MEDIUM, ThinkingEffort.HIGH),
            effortStepsFor(ThinkingCapability.EFFORT),
        )
    }

    @Test
    fun `adaptive capability has 5 steps`() {
        assertEquals(
            listOf(ThinkingEffort.OFF, ThinkingEffort.LOW, ThinkingEffort.MEDIUM, ThinkingEffort.HIGH, ThinkingEffort.MAX),
            effortStepsFor(ThinkingCapability.ADAPTIVE),
        )
    }
}
