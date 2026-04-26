package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.StreamEvent
import org.json.JSONException
import org.json.JSONObject

/**
 * SSE 帧格式：{"type":"...","data":{...},"ts":"..."}
 * 使用 org.json（Android 内置）解析，避免额外依赖
 */
object SseFrameParser {

    fun parse(raw: String): StreamEvent = try {
        val frame = JSONObject(raw)
        val type = frame.getString("type")
        val data = frame.optJSONObject("data") ?: JSONObject()
        parseByType(type, data)
    } catch (e: JSONException) {
        StreamEvent.Unknown
    }

    private fun parseByType(type: String, data: JSONObject): StreamEvent = when (type) {
        "turn.received" -> StreamEvent.TurnReceived(data.getString("session_id"))
        "turn.response" -> StreamEvent.TurnResponse(data.getString("session_id"), data.optString("content", ""))
        "turn.interrupted" -> StreamEvent.TurnInterrupted(data.getString("session_id"), data.optString("partial_content", ""))
        "turn.cancelled" -> StreamEvent.TurnCancelled(data.getString("session_id"), data.optString("partial_content", ""))
        "thinking_block.start" -> StreamEvent.ThinkingBlockStart(data.getString("session_id"), data.getString("block_id"))
        "turn.thinking_delta" -> StreamEvent.ThinkingDelta(data.getString("session_id"), data.getString("block_id"), data.getString("delta"))
        "thinking_block.stop" -> StreamEvent.ThinkingBlockStop(
            sessionId  = data.getString("session_id"),
            blockId    = data.getString("block_id"),
            durationMs = data.optLong("duration_ms", -1L).takeIf { it >= 0L },
        )
        "text_block.start" -> StreamEvent.TextBlockStart(data.getString("session_id"), data.getString("block_id"))
        "turn.delta" -> StreamEvent.TextDelta(data.getString("session_id"), data.getString("block_id"), data.getString("delta"))
        "text_block.stop" -> StreamEvent.TextBlockStop(data.getString("session_id"), data.getString("block_id"))
        "tool_block.start" -> StreamEvent.ToolBlockStart(data.getString("session_id"), data.getString("block_id"), data.getString("tool_id"), data.getString("name"))
        "tool_block.stop" -> StreamEvent.ToolBlockStop(data.getString("session_id"), data.getString("block_id"), data.getString("tool_id"), data.getString("name"), data.optJSONObject("inputs")?.toString() ?: "{}")
        "tool.running" -> StreamEvent.ToolRunning(data.getString("session_id"), data.getString("tool_id"), data.getString("name"))
        "tool.executed" -> StreamEvent.ToolExecuted(data.getString("session_id"), data.getString("tool_id"), data.getString("name"), data.optString("result_summary", ""))
        "tool.failed" -> StreamEvent.ToolFailed(data.getString("session_id"), data.getString("tool_id"), data.getString("name"), data.optString("error", ""))
        "task.created" -> StreamEvent.TaskCreated(data.getString("session_id"), data.getString("task_id"), data.optString("goal", ""))
        "task.started" -> StreamEvent.TaskStarted(data.getString("session_id"), data.getString("task_id"))
        "task.completed" -> StreamEvent.TaskCompleted(data.getString("session_id"), data.getString("task_id"))
        "task.failed" -> StreamEvent.TaskFailed(data.getString("session_id"), data.getString("task_id"), data.optString("error", ""))
        "task.cancelled" -> StreamEvent.TaskCancelled(data.getString("session_id"), data.getString("task_id"))
        "approval.requested" -> StreamEvent.ApprovalRequested(
            sessionId = data.getString("session_id"),
            approvalId = data.getString("approval_id"),
            agentType = data.optString("agent_type", "sebastian"),
            toolName = data.optString("tool_name", ""),
            toolInputJson = data.optJSONObject("tool_input")?.toString() ?: "{}",
            reason = data.optString("reason", ""),
        )
        "approval.granted" -> StreamEvent.ApprovalGranted(data.getString("approval_id"))
        "approval.denied" -> StreamEvent.ApprovalDenied(data.getString("approval_id"))
        "todo.updated" -> StreamEvent.TodoUpdated(data.getString("session_id"), data.optInt("count", 0))
        "session.completed" -> StreamEvent.SessionCompleted(
            sessionId = data.getString("session_id"),
            agentType = data.optString("agent_type", ""),
            goal = data.optString("goal", ""),
        )
        "session.failed" -> StreamEvent.SessionFailed(
            sessionId = data.getString("session_id"),
            agentType = data.optString("agent_type", ""),
            goal = data.optString("goal", ""),
            error = data.optString("error", ""),
        )
        else -> StreamEvent.Unknown
    }
}
