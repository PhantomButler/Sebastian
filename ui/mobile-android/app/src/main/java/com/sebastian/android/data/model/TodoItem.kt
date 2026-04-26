package com.sebastian.android.data.model

data class TodoItem(
    val content: String,
    val activeForm: String,
    val status: String,
) {
    val isDone: Boolean get() = status == "completed"
    val isInProgress: Boolean get() = status == "in_progress"
}
