package com.sebastian.android.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * iOS 风格 rubberband 衰减公式：rubberband(d, dim) = d * dim / (d + dim * 0.55)
 * 性质：单调递增、过原点、有渐近线 dim/0.55。
 */
class RubberbandTest {

    @Test
    fun `at zero distance returns zero`() {
        assertEquals(0f, rubberband(0f, 100f), 0.0001f)
    }

    @Test
    fun `dimension zero returns zero regardless of distance`() {
        assertEquals(0f, rubberband(50f, 0f), 0.0001f)
        assertEquals(0f, rubberband(10000f, 0f), 0.0001f)
    }

    @Test
    fun `output is always less than input distance for positive inputs`() {
        // 衰减性质：rubberband(d, dim) < d
        val outs = listOf(10f, 50f, 100f, 500f, 1000f)
        outs.forEach { d ->
            val r = rubberband(d, 100f)
            assertTrue("rubberband($d, 100) = $r should be < $d", r < d)
            assertTrue("rubberband($d, 100) = $r should be > 0", r > 0f)
        }
    }

    @Test
    fun `output asymptotes to dimension`() {
        // iOS UIKit 公式 (0.55*x*D)/(0.55*x+D) 的渐近线 = D
        val r = rubberband(1_000_000f, 100f)
        assertTrue("rubberband(1M, 100) = $r should be < 100", r < 100f)
        // 距离极大时应非常接近渐近线
        assertTrue("rubberband(1M, 100) = $r should be > 99", r > 99f)
    }

    @Test
    fun `is monotonically increasing in distance`() {
        val dim = 200f
        val samples = (0..10).map { rubberband(it * 100f, dim) }
        samples.zipWithNext().forEachIndexed { i, pair ->
            val a = pair.first
            val b = pair.second
            assertTrue(
                "step $i: rubberband(${i * 100}f) = $a should be < rubberband(${(i + 1) * 100}f) = $b",
                a < b,
            )
        }
    }

    @Test
    fun `at distance equal to dimension returns 0_355 dim`() {
        // d == dim 时 (0.55 * D * D) / (0.55 * D + D) = D * 0.55 / 1.55 ≈ 0.3548 * D
        val expected = 100f * 0.55f / 1.55f
        assertEquals(expected, rubberband(100f, 100f), 0.0001f)
    }
}
