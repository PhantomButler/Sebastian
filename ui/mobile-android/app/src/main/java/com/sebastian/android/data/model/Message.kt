package com.sebastian.android.data.model

data class Message(
    val id: String,
    val sessionId: String,
    val role: MessageRole,
    val blocks: List<ContentBlock> = emptyList(),
    val text: String = "",         // user 消息纯文本
    val createdAt: String = "",
)

enum class MessageRole { USER, ASSISTANT }
