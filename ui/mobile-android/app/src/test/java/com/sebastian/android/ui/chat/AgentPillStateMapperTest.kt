package com.sebastian.android.ui.chat

import com.sebastian.android.viewmodel.AgentAnimState
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * AgentAnimState → AgentPillMode 的 4→3 档映射。
 * STREAMING 和 WORKING 合并为 ACTIVE（同一 HUD 动画）。
 */
class AgentPillStateMapperTest {

    @Test
    fun `IDLE maps to COLLAPSED`() {
        assertEquals(AgentPillMode.COLLAPSED, AgentAnimState.IDLE.toPillMode())
    }

    @Test
    fun `THINKING maps to THINKING`() {
        assertEquals(AgentPillMode.THINKING, AgentAnimState.THINKING.toPillMode())
    }

    @Test
    fun `STREAMING maps to ACTIVE`() {
        assertEquals(AgentPillMode.ACTIVE, AgentAnimState.STREAMING.toPillMode())
    }

    @Test
    fun `WORKING maps to ACTIVE`() {
        assertEquals(AgentPillMode.ACTIVE, AgentAnimState.WORKING.toPillMode())
    }
}
