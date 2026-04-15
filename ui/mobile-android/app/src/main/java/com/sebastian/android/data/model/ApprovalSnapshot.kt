package com.sebastian.android.data.model

/**
 * REST 快照用的待审批条目（`GET /approvals` 响应的领域模型）。
 * 字段与 `GlobalApproval` 对齐，独立存放以避免 repository 反向依赖 viewmodel 包。
 */
data class ApprovalSnapshot(
    val approvalId: String,
    val sessionId: String,
    val agentType: String,
    val toolName: String,
    val toolInputJson: String,
    val reason: String,
)
