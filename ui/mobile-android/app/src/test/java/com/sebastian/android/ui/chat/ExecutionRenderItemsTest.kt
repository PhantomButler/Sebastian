package com.sebastian.android.ui.chat

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.ToolStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ExecutionRenderItemsTest {

    @Test
    fun `consecutive thinking and tool blocks become one execution group`() {
        val blocks = listOf(
            ContentBlock.ThinkingBlock(blockId = "think-1", text = "plan", done = true),
            ContentBlock.ToolBlock(
                blockId = "tool-1",
                toolId = "call-1",
                name = "read_file",
                displayName = "Read file",
                inputs = "{}",
                status = ToolStatus.DONE,
            ),
        )

        val items = buildMessageRenderItems(blocks)

        assertEquals(1, items.size)
        val group = items.single() as MessageRenderItem.ExecutionGroup
        assertEquals("exec-think-1-tool-1", group.id)
        assertEquals(blocks, group.blocks)
    }

    @Test
    fun `text block splits execution groups and preserves order`() {
        val first = ContentBlock.ThinkingBlock(blockId = "think-1", text = "plan", done = true)
        val text = ContentBlock.TextBlock(blockId = "text-1", text = "answer", done = true)
        val second = ContentBlock.ToolBlock(
            blockId = "tool-1",
            toolId = "call-1",
            name = "search",
            displayName = "Search",
            inputs = "{}",
            status = ToolStatus.RUNNING,
        )

        val items = buildMessageRenderItems(listOf(first, text, second))

        assertEquals(3, items.size)
        assertTrue(items[0] is MessageRenderItem.ExecutionGroup)
        assertEquals(text, (items[1] as MessageRenderItem.Block).block)
        assertTrue(items[2] is MessageRenderItem.ExecutionGroup)
    }

    @Test
    fun `blank text block does not split execution groups`() {
        val first = ContentBlock.ThinkingBlock(blockId = "think-1", text = "plan", done = true)
        val blankText = ContentBlock.TextBlock(blockId = "text-blank", text = "", done = true)
        val second = ContentBlock.ToolBlock(
            blockId = "tool-1",
            toolId = "call-1",
            name = "search",
            displayName = "Search",
            inputs = "{}",
            status = ToolStatus.DONE,
        )

        val items = buildMessageRenderItems(listOf(first, blankText, second))

        assertEquals(1, items.size)
        val group = items.single() as MessageRenderItem.ExecutionGroup
        assertEquals(listOf(first, second), group.blocks)
    }

    @Test
    fun `summary image and file blocks split execution groups`() {
        val think = ContentBlock.ThinkingBlock(blockId = "think-1", text = "plan")
        val summary = ContentBlock.SummaryBlock(blockId = "summary-1", text = "compressed")
        val image = ContentBlock.ImageBlock(
            blockId = "image-1",
            attachmentId = "att-image",
            filename = "shot.png",
            mimeType = "image/png",
            sizeBytes = 10L,
            downloadUrl = "/download/image",
        )
        val file = ContentBlock.FileBlock(
            blockId = "file-1",
            attachmentId = "att-file",
            filename = "notes.txt",
            mimeType = "text/plain",
            sizeBytes = 20L,
            downloadUrl = "/download/file",
        )
        val tool = ContentBlock.ToolBlock(
            blockId = "tool-1",
            toolId = "call-1",
            name = "read",
            inputs = "{}",
            status = ToolStatus.DONE,
        )

        val items = buildMessageRenderItems(listOf(think, summary, image, file, tool))

        assertEquals(5, items.size)
        assertTrue(items[0] is MessageRenderItem.ExecutionGroup)
        assertEquals(summary, (items[1] as MessageRenderItem.Block).block)
        assertEquals(image, (items[2] as MessageRenderItem.Block).block)
        assertEquals(file, (items[3] as MessageRenderItem.Block).block)
        assertTrue(items[4] is MessageRenderItem.ExecutionGroup)
    }

    @Test
    fun `single execution block still becomes execution group`() {
        val block = ContentBlock.ToolBlock(
            blockId = "tool-1",
            toolId = "call-1",
            name = "read",
            inputs = "{}",
            status = ToolStatus.DONE,
        )

        val items = buildMessageRenderItems(listOf(block))

        assertEquals(1, items.size)
        assertEquals(listOf(block), (items.single() as MessageRenderItem.ExecutionGroup).blocks)
    }

    @Test
    fun `executionStepState maps thinking states`() {
        assertEquals(
            ExecutionStepState.RUNNING,
            executionStepState(ContentBlock.ThinkingBlock(blockId = "think-running", text = "")),
        )
        assertEquals(
            ExecutionStepState.DONE,
            executionStepState(
                ContentBlock.ThinkingBlock(
                    blockId = "think-done",
                    text = "",
                    done = true,
                ),
            ),
        )
    }

    @Test
    fun `executionStepState maps tool states`() {
        fun tool(status: ToolStatus) = ContentBlock.ToolBlock(
            blockId = "tool-$status",
            toolId = "call-$status",
            name = "tool",
            inputs = "{}",
            status = status,
        )

        assertEquals(ExecutionStepState.RUNNING, executionStepState(tool(ToolStatus.PENDING)))
        assertEquals(ExecutionStepState.RUNNING, executionStepState(tool(ToolStatus.RUNNING)))
        assertEquals(ExecutionStepState.DONE, executionStepState(tool(ToolStatus.DONE)))
        assertEquals(ExecutionStepState.FAILED, executionStepState(tool(ToolStatus.FAILED)))
    }

    @Test
    fun `activeExecutionSummary returns Thinking for running thinking block`() {
        val summary = activeExecutionSummary(
            listOf(
                ContentBlock.ThinkingBlock(blockId = "think-running", text = "plan"),
            ),
        )

        assertEquals("think-running", summary?.id)
        assertEquals("Thinking", summary?.text)
    }

    @Test
    fun `activeExecutionSummary returns running tool display name and input summary`() {
        val summary = activeExecutionSummary(
            listOf(
                ContentBlock.ToolBlock(
                    blockId = "tool-running",
                    toolId = "call-running",
                    name = "Bash",
                    displayName = "Shell",
                    inputs = """{"command":"sebastian skills search weather"}""",
                    status = ToolStatus.RUNNING,
                ),
            ),
        )

        assertEquals("tool-running", summary?.id)
        assertEquals("Shell sebastian skills search weather", summary?.text)
    }

    @Test
    fun `activeExecutionSummary falls back to tool name without input summary`() {
        val summary = activeExecutionSummary(
            listOf(
                ContentBlock.ToolBlock(
                    blockId = "tool-running",
                    toolId = "call-running",
                    name = "Bash",
                    displayName = "",
                    inputs = "{}",
                    status = ToolStatus.PENDING,
                ),
            ),
        )

        assertEquals("Bash", summary?.text)
    }

    @Test
    fun `activeExecutionSummary ignores completed and failed blocks`() {
        val summary = activeExecutionSummary(
            listOf(
                ContentBlock.ThinkingBlock(blockId = "think-done", text = "plan", done = true),
                ContentBlock.ToolBlock(
                    blockId = "tool-failed",
                    toolId = "call-failed",
                    name = "Bash",
                    inputs = "{}",
                    status = ToolStatus.FAILED,
                ),
            ),
        )

        assertEquals(null, summary)
    }

    @Test
    fun `activeExecutionSummary uses the last running block`() {
        val summary = activeExecutionSummary(
            listOf(
                ContentBlock.ThinkingBlock(blockId = "think-running", text = "plan"),
                ContentBlock.ToolBlock(
                    blockId = "tool-running",
                    toolId = "call-running",
                    name = "Bash",
                    inputs = """{"command":"date"}""",
                    status = ToolStatus.RUNNING,
                ),
            ),
        )

        assertEquals("tool-running", summary?.id)
        assertEquals("Bash date", summary?.text)
    }
}
