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
