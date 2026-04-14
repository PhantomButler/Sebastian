package com.sebastian.android.ui.chat

import org.json.JSONException
import org.json.JSONObject

/**
 * 解析工具调用的 JSON inputs，给 [ToolCallCard] 提供折叠态摘要和展开态 key-value 列表。
 *
 * 行为对齐 RN 版本 `ui/mobile/src/components/conversation/ToolCallRow.tsx`：
 * - 每个工具维护一个优先键表，按顺序取第一个非空字符串
 * - 未知工具走通用键兜底
 * - 非法 JSON 直接把原始输入（截断 80 字）作为摘要
 * - `delegate_to_agent` 摘要显示子代理名（首字母大写），而不是 goal
 */
internal object ToolCallInputExtractor {
    private const val SUMMARY_MAX_LEN = 80

    private val KEY_PRIORITY: Map<String, List<String>> = mapOf(
        "Bash" to listOf("command"),
        "Read" to listOf("file_path"),
        "Write" to listOf("file_path"),
        "Edit" to listOf("file_path"),
        "Grep" to listOf("pattern", "path"),
        "Glob" to listOf("pattern", "path"),
        "delegate_to_agent" to listOf("agent_type"),
    )

    private val GENERIC_KEYS = listOf("command", "file_path", "path", "pattern", "query")

    /** 折叠态 header 右侧的一行摘要。解析失败返回截断后的原始输入。 */
    fun extractInputSummary(name: String, inputs: String): String {
        if (inputs.isEmpty()) return ""
        val parsed = parseOrNull(inputs) ?: return truncate(inputs)

        val keys = KEY_PRIORITY[name] ?: GENERIC_KEYS
        for (key in keys) {
            val value = parsed.optStringOrNull(key) ?: continue
            val shaped = if (name == "delegate_to_agent" && key == "agent_type") {
                value.replaceFirstChar { it.uppercase() }
            } else {
                value
            }
            return truncate(shaped)
        }

        val iter = parsed.keys()
        while (iter.hasNext()) {
            val key = iter.next()
            val value = parsed.optStringOrNull(key) ?: continue
            return truncate(value)
        }

        return ""
    }

    /** 展开态「参数」区的多行文本，形如 `key: value\nkey: value`。 */
    fun extractKeyParams(name: String, inputs: String): String {
        if (inputs.isEmpty()) return ""
        // 解析失败时复用 summary 的 80 字截断，避免把超长异常 inputs 原文糊进「参数」区
        val parsed = parseOrNull(inputs) ?: return truncate(inputs)

        val keys = KEY_PRIORITY[name] ?: GENERIC_KEYS
        val lines = mutableListOf<String>()
        for (key in keys) {
            val value = parsed.optStringOrNull(key) ?: continue
            lines += "$key: $value"
        }

        if (lines.isEmpty()) {
            val iter = parsed.keys()
            while (iter.hasNext()) {
                val key = iter.next()
                val value = parsed.optStringOrNull(key) ?: continue
                lines += "$key: $value"
            }
        }

        return lines.joinToString("\n")
    }

    private fun parseOrNull(text: String): JSONObject? = try {
        JSONObject(text)
    } catch (_: JSONException) {
        null
    }

    /**
     * 严格只接受 `String` 类型字段，对齐 RN `typeof val === 'string'` 语义。
     * `JSONObject.optString` 会把 number/boolean/array 都字符串化，摘要里出现 `count: 42`
     * 或 `files: []` 不是期望行为。
     */
    private fun JSONObject.optStringOrNull(key: String): String? {
        val raw = opt(key) as? String ?: return null
        val trimmed = raw.trim()
        return trimmed.ifEmpty { null }
    }

    private fun truncate(text: String): String = if (text.length > SUMMARY_MAX_LEN) {
        text.take(SUMMARY_MAX_LEN) + "…"
    } else {
        text
    }
}
