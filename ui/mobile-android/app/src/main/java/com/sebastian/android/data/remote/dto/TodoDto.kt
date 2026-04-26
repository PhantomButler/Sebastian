package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.TodoItem
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class TodoItemDto(
    @param:Json(name = "content") val content: String,
    @param:Json(name = "activeForm") val activeForm: String,
    @param:Json(name = "status") val status: String,
) {
    fun toDomain() = TodoItem(content = content, activeForm = activeForm, status = status)
}

@JsonClass(generateAdapter = true)
data class TodoListResponse(
    @param:Json(name = "todos") val todos: List<TodoItemDto>,
    @param:Json(name = "updated_at") val updatedAt: String? = null,
)
