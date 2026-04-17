// app/src/test/java/com/sebastian/android/ui/composer/ComposerStateTest.kt
package com.sebastian.android.ui.composer

import com.sebastian.android.viewmodel.ComposerState
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Composer 输入文本变化驱动 ComposerState 的逻辑测试。
 * 实际 state 由 ChatViewModel 持有，此处测试纯函数映射。
 */
class ComposerStateTest {

    @Test
    fun `empty text maps to IDLE_EMPTY`() {
        assertEquals(ComposerState.IDLE_EMPTY, resolveComposerState("", ComposerState.IDLE_EMPTY))
    }

    @Test
    fun `non-empty text in IDLE_EMPTY maps to IDLE_READY`() {
        assertEquals(ComposerState.IDLE_READY, resolveComposerState("hello", ComposerState.IDLE_EMPTY))
    }

    @Test
    fun `clearing text in IDLE_READY maps back to IDLE_EMPTY`() {
        assertEquals(ComposerState.IDLE_EMPTY, resolveComposerState("", ComposerState.IDLE_READY))
    }

    @Test
    fun `STREAMING state is not affected by text content`() {
        // 流式进行中，不因文字变化改变 composerState（由 ViewModel 控制）
        assertEquals(ComposerState.STREAMING, resolveComposerState("", ComposerState.STREAMING))
        assertEquals(ComposerState.STREAMING, resolveComposerState("text", ComposerState.STREAMING))
    }

    @Test
    fun `PENDING state is not affected by text content`() {
        assertEquals(ComposerState.PENDING, resolveComposerState("", ComposerState.PENDING))
    }

    // 辅助函数：模拟 Composer 内部的状态映射逻辑
    private fun resolveComposerState(text: String, current: ComposerState): ComposerState {
        if (current == ComposerState.STREAMING || current == ComposerState.PENDING || current == ComposerState.CANCELLING) {
            return current
        }
        return if (text.isNotBlank()) ComposerState.IDLE_READY else ComposerState.IDLE_EMPTY
    }
}
