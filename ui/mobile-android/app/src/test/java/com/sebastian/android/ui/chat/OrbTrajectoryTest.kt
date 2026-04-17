package com.sebastian.android.ui.chat

import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 光团轨迹关键帧插值（纯数学，不依赖 Compose runtime）。
 * easeInOutQuad 作为唯一 easing。
 */
class OrbTrajectoryTest {

    private val trajectory = listOf(
        Keyframe(0.0f, DpOffset(0.dp, 0.dp),      alpha = 0.6f),
        Keyframe(0.5f, DpOffset(8.dp, (-4).dp),   alpha = 1.0f),
        Keyframe(1.0f, DpOffset(0.dp, 0.dp),      alpha = 0.6f),
    )

    @Test
    fun `at t=0 returns first keyframe`() {
        val v = interpolateTrajectory(0f, trajectory)
        assertEquals(0f, v.offset.x.value, 0.001f)
        assertEquals(0f, v.offset.y.value, 0.001f)
        assertEquals(0.6f, v.alpha, 0.001f)
    }

    @Test
    fun `at t=1 returns last keyframe`() {
        val v = interpolateTrajectory(1f, trajectory)
        assertEquals(0f, v.offset.x.value, 0.001f)
        assertEquals(0.6f, v.alpha, 0.001f)
    }

    @Test
    fun `at t=0_5 returns middle keyframe exactly`() {
        val v = interpolateTrajectory(0.5f, trajectory)
        assertEquals(8f, v.offset.x.value, 0.001f)
        assertEquals(-4f, v.offset.y.value, 0.001f)
        assertEquals(1.0f, v.alpha, 0.001f)
    }

    @Test
    fun `at t=0_25 interpolates with easeInOutQuad between first and middle`() {
        // raw=(0.25-0)/(0.5-0)=0.5，easeInOutQuad(0.5) = 0.5
        val v = interpolateTrajectory(0.25f, trajectory)
        assertEquals(4f, v.offset.x.value, 0.001f)    // lerp(0, 8, 0.5)
        assertEquals(-2f, v.offset.y.value, 0.001f)   // lerp(0, -4, 0.5)
        assertEquals(0.8f, v.alpha, 0.001f)           // lerp(0.6, 1.0, 0.5)
    }

    @Test
    fun `at t=0_125 easing deviates from linear lerp`() {
        // raw = (0.125 - 0) / (0.5 - 0) = 0.25
        // easeInOutQuad(0.25) = 2 * 0.25 * 0.25 = 0.125   ← not 0.25 (linear would give 0.25)
        val v = interpolateTrajectory(0.125f, trajectory)
        assertEquals(1.0f, v.offset.x.value, 0.001f)   // lerp(0, 8, 0.125) = 1.0
        assertEquals(-0.5f, v.offset.y.value, 0.001f)  // lerp(0, -4, 0.125) = -0.5
        assertEquals(0.65f, v.alpha, 0.001f)            // lerp(0.6, 1.0, 0.125) = 0.65
    }

    @Test
    fun `time out of range clamps to boundaries`() {
        assertEquals(0.6f, interpolateTrajectory(-0.5f, trajectory).alpha, 0.001f)
        assertEquals(0.6f, interpolateTrajectory(1.5f, trajectory).alpha, 0.001f)
    }
}
