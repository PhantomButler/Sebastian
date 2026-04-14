package com.sebastian.android.ui.common

import org.json.JSONObject

data class ApprovalSummary(
    val title: String,   // "Execute Command" / "Write File" / "Call Tool" …
    val detail: String,  // the command / path / main param
)

private const val MAX_DETAIL_LEN = 120

fun summarizeApproval(toolName: String, toolInputJson: String): ApprovalSummary {
    val input = runCatching { JSONObject(toolInputJson) }.getOrNull() ?: JSONObject()
    val lowered = toolName.lowercase()

    return when {
        lowered.contains("bash") || lowered.contains("shell") || lowered == "run_command" -> {
            val cmd = input.optString("command").ifBlank { input.optString("cmd") }
            ApprovalSummary(title = "Execute Command", detail = "$ ${cmd.truncate()}")
        }
        lowered.contains("write") || lowered.contains("edit") || lowered == "create_file" -> {
            val path = input.optString("path").ifBlank { input.optString("file_path") }
            ApprovalSummary(title = "Write File", detail = path.ifBlank { firstFieldSummary(input) }.truncate())
        }
        lowered.contains("read") || lowered == "open_file" -> {
            val path = input.optString("path").ifBlank { input.optString("file_path") }
            ApprovalSummary(title = "Read File", detail = path.ifBlank { firstFieldSummary(input) }.truncate())
        }
        lowered.contains("delete") || lowered.contains("remove") -> {
            val path = input.optString("path").ifBlank { input.optString("target") }
            ApprovalSummary(title = "Delete", detail = path.ifBlank { firstFieldSummary(input) }.truncate())
        }
        lowered.contains("http") || lowered.contains("fetch") || lowered.contains("request") -> {
            val url = input.optString("url").ifBlank { input.optString("endpoint") }
            ApprovalSummary(title = "HTTP Request", detail = url.ifBlank { firstFieldSummary(input) }.truncate())
        }
        else -> ApprovalSummary(title = "Call Tool", detail = firstFieldSummary(input).truncate())
    }
}

/**
 * Clip the backend reason string to the first meaningful clause.
 * Splits on the first occurrence of "（", "，", "," or "。" so only the
 * leading summary phrase is shown (e.g. "检测到高危 Bash 命令（...）" → "检测到高危 Bash 命令").
 */
fun clipReason(reason: String): String {
    if (reason.isBlank()) return ""
    val cutAt = reason.indexOfFirst { it == '（' || it == '，' || it == ',' || it == '。' }
    return if (cutAt > 0) reason.substring(0, cutAt) else reason
}

private fun firstFieldSummary(input: JSONObject): String {
    val keys = input.keys()
    while (keys.hasNext()) {
        val key = keys.next()
        val value = input.opt(key)?.toString().orEmpty()
        if (value.isNotBlank()) return "$key=$value"
    }
    return "(no params)"
}

private fun String.truncate(max: Int = MAX_DETAIL_LEN): String =
    if (length <= max) this else substring(0, max) + "…"
