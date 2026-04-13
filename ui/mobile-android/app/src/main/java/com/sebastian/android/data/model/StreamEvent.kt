package com.sebastian.android.data.model

sealed class StreamEvent {
    // Turn 级别
    data class TurnReceived(val sessionId: String) : StreamEvent()
    data class TurnResponse(val sessionId: String, val content: String) : StreamEvent()
    data class TurnInterrupted(val sessionId: String, val partialContent: String) : StreamEvent()

    // Thinking block
    data class ThinkingBlockStart(val sessionId: String, val blockId: String) : StreamEvent()
    data class ThinkingDelta(val sessionId: String, val blockId: String, val delta: String) : StreamEvent()
    data class ThinkingBlockStop(val sessionId: String, val blockId: String) : StreamEvent()

    // Text block
    data class TextBlockStart(val sessionId: String, val blockId: String) : StreamEvent()
    data class TextDelta(val sessionId: String, val blockId: String, val delta: String) : StreamEvent()
    data class TextBlockStop(val sessionId: String, val blockId: String) : StreamEvent()

    // Tool
    data class ToolBlockStart(val sessionId: String, val blockId: String, val toolId: String, val name: String) : StreamEvent()
    data class ToolBlockStop(val sessionId: String, val blockId: String, val toolId: String, val name: String, val inputs: String) : StreamEvent()
    data class ToolRunning(val sessionId: String, val toolId: String, val name: String) : StreamEvent()
    data class ToolExecuted(val sessionId: String, val toolId: String, val name: String, val resultSummary: String) : StreamEvent()
    data class ToolFailed(val sessionId: String, val toolId: String, val name: String, val error: String) : StreamEvent()

    // Task
    data class TaskCreated(val sessionId: String, val taskId: String, val goal: String) : StreamEvent()
    data class TaskStarted(val sessionId: String, val taskId: String) : StreamEvent()
    data class TaskCompleted(val sessionId: String, val taskId: String) : StreamEvent()
    data class TaskFailed(val sessionId: String, val taskId: String, val error: String) : StreamEvent()
    data class TaskCancelled(val sessionId: String, val taskId: String) : StreamEvent()

    // Approval
    data class ApprovalRequested(val sessionId: String, val approvalId: String, val agentType: String, val description: String) : StreamEvent()
    data class ApprovalGranted(val approvalId: String) : StreamEvent()
    data class ApprovalDenied(val approvalId: String) : StreamEvent()

    // 未识别事件（忽略）
    object Unknown : StreamEvent()
}
