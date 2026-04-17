package com.sebastian.android.data.model

fun String?.toThinkingEffort(): ThinkingEffort = when (this) {
    "on" -> ThinkingEffort.ON
    "low" -> ThinkingEffort.LOW
    "medium" -> ThinkingEffort.MEDIUM
    "high" -> ThinkingEffort.HIGH
    "max" -> ThinkingEffort.MAX
    else -> ThinkingEffort.OFF
}

fun ThinkingEffort.toApiString(): String? = when (this) {
    ThinkingEffort.OFF -> null
    ThinkingEffort.ON -> "on"
    ThinkingEffort.LOW -> "low"
    ThinkingEffort.MEDIUM -> "medium"
    ThinkingEffort.HIGH -> "high"
    ThinkingEffort.MAX -> "max"
}

/**
 * 用户可见的 effort 标签。OFF 返回空串（由调用方决定是否渲染）。
 * 与 [toApiString] 区别：UI 不关心 null，需要稳定非空返回。
 */
fun ThinkingEffort.displayLabel(): String = when (this) {
    ThinkingEffort.OFF -> ""
    ThinkingEffort.ON -> "on"
    ThinkingEffort.LOW -> "low"
    ThinkingEffort.MEDIUM -> "medium"
    ThinkingEffort.HIGH -> "high"
    ThinkingEffort.MAX -> "max"
}
