# orchestrator — 主管家编排层

## 职责

Sebastian 主 Agent 的具体实现，以及对话平面（Approval 挂起/恢复机制）。是系统的"大脑入口"：接收用户消息，规划，执行或委派。

## 关键文件

| 文件 | 职责 |
|---|---|
| `sebas.py` | `Sebastian` 类：继承 `BaseAgent`，持有 `TaskManager`、`ConversationManager`、`IndexStore`，实现 `chat()` 和 `get_or_create_session()`；定义 Sebastian 的 system prompt |
| `conversation.py` | `ConversationManager`：管理 Approval 挂起/恢复，`request_approval()` 挂起当前协程直到用户 grant/deny 或超时（默认 300s） |

## 公开接口（其他模块如何使用）

```python
# Gateway 通过 state.py 访问，不直接实例化
import sebastian.gateway.state as state

# 发送用户消息
response = await state.sebastian.chat(user_message, session_id)

# 创建或获取 session
session = await state.sebastian.get_or_create_session(session_id, first_message)

# Approval 挂起（在 BaseAgent 的 tool 执行路径中调用）
granted = await state.conversation.request_approval(
    approval_id, task_id, tool_name, tool_input
)
```

## 数据流

```
用户消息 (HTTP POST /turns)
  → Sebastian.chat()
    → BaseAgent.run_streaming()
      → AgentLoop（LLM turn）
        → 需要 tool: CapabilityRegistry.call()
        → 需要审批: ConversationManager.request_approval() [挂起]
          → 用户 POST /approvals/{id}/grant → [恢复]
        → 需要委派: TaskManager.submit() + A2A DelegateTask
```

## 常见任务入口

- **修改 Sebastian 的人格/指令** → `sebas.py` 的 `SEBASTIAN_SYSTEM_PROMPT`
- **修改对话入口逻辑（session 管理、消息预处理）** → `sebas.py` 的 `chat()` 和 `get_or_create_session()`
- **修改 Approval 超时/挂起行为** → `conversation.py` 的 `request_approval()`
- **新增 Orchestrator 级别功能**（规划、目标分解等，Phase 2+）→ 在此目录新增文件
