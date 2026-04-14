package com.sebastian.android.ui.chat

/**
 * 工具名 → 卡片 header 显示的统一映射。
 *
 * 背景：后端注册的大多数工具名本身就是 PascalCase（`Read` / `Write` / `Bash`…），
 * 可以直接作为显示名，`summary` 用 [ToolCallInputExtractor] 从 inputs 抽关键字段。
 * 少数工具（例如 snake_case 的 `delegate_to_agent` / `spawn_sub_agent`）希望
 * 在 UI 上呈现成自定义的「类别 + 目标」形式，这里集中维护这些规则。
 *
 * 新增规则步骤：
 * 1. 确认后端工具 inputs 里能稳定取到需要展示的字段；如字段未被
 *    [ToolCallInputExtractor.KEY_PRIORITY] 收录，先把它加进去，保证提取顺序确定。
 * 2. 在 [resolve] 的 `when` 里追加一条 case，返回期望的 (title, summary)。
 * 3. 纯展示层改动，不要依赖 inputs JSON schema 以外的状态。
 */
internal object ToolDisplayName {

    /** header 展示用的 (title, summary) 对，title 替代 tool 名，summary 放在右侧。 */
    data class Display(val title: String, val summary: String)

    fun resolve(toolName: String, inputs: String): Display {
        val rawSummary = ToolCallInputExtractor.extractInputSummary(toolName, inputs)
        return when (toolName) {
            "delegate_to_agent" -> Display(title = "Agent: $rawSummary", summary = "")
            "spawn_sub_agent" -> Display(title = "Worker", summary = rawSummary)
            else -> Display(title = toolName, summary = rawSummary)
        }
    }
}
