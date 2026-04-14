package com.sebastian.android.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.util.concurrent.ConcurrentHashMap

class DeltaAtomicRemoveTest {

    @Test
    fun `remove returns value and clears key atomically`() {
        val map = ConcurrentHashMap<String, StringBuilder>()
        map.getOrPut("block1") { StringBuilder() }.append("hello")
        map.getOrPut("block1") { StringBuilder() }.append(" world")

        val snapshot = map.keys.toList().mapNotNull { key ->
            map.remove(key)?.toString()?.let { key to it }
        }

        assertEquals(1, snapshot.size)
        assertEquals("block1" to "hello world", snapshot[0])
        assertFalse(map.containsKey("block1"))
    }

    @Test
    fun `remove on absent key returns null without throwing`() {
        val map = ConcurrentHashMap<String, StringBuilder>()
        val result = map.remove("nonexistent")
        assertEquals(null, result)
    }
}
