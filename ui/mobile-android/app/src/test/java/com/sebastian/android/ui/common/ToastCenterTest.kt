package com.sebastian.android.ui.common

import android.content.Context
import android.widget.Toast
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify

class ToastCenterTest {

    private lateinit var context: Context
    private var fakeNow: Long = 0L
    private val createdToasts = mutableListOf<Toast>()

    private val origClock = ToastCenter.clock
    private val origExecutor = ToastCenter.mainExecutor
    private val origFactory = ToastCenter.toastFactory

    @Before
    fun setup() {
        context = mock { on { applicationContext } doReturn it }
        fakeNow = 0L
        createdToasts.clear()
        ToastCenter.resetForTest()
        ToastCenter.clock = { fakeNow }
        ToastCenter.mainExecutor = { it.run() }
        ToastCenter.toastFactory = { _, _, _ ->
            mock<Toast>().also { createdToasts += it }
        }
    }

    @After
    fun tearDown() {
        ToastCenter.clock = origClock
        ToastCenter.mainExecutor = origExecutor
        ToastCenter.toastFactory = origFactory
        ToastCenter.resetForTest()
    }

    @Test
    fun `first call at clock zero is not throttled`() {
        // 回归：防止 lastShownAt[key] 初值陷阱把 fakeNow = 0 的首次调用误节流
        fakeNow = 0L
        ToastCenter.show(context, "hi")

        assertEquals(1, createdToasts.size)
    }

    @Test
    fun `same key within throttle window is dropped`() {
        ToastCenter.show(context, "hi")
        fakeNow = 500L
        ToastCenter.show(context, "hi")

        assertEquals(1, createdToasts.size)
    }

    @Test
    fun `same key after throttle window is shown`() {
        ToastCenter.show(context, "hi")
        fakeNow = 1600L
        ToastCenter.show(context, "hi")

        assertEquals(2, createdToasts.size)
    }

    @Test
    fun `different keys pass independently`() {
        ToastCenter.show(context, "hi", key = "a")
        ToastCenter.show(context, "hi", key = "b")

        assertEquals(2, createdToasts.size)
    }

    @Test
    fun `second show cancels previous toast`() {
        ToastCenter.show(context, "first", key = "a")
        ToastCenter.show(context, "second", key = "b")

        verify(createdToasts[0]).cancel()
    }
}
