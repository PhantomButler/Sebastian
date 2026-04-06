# orchestrator — 主管家编排层

> 上级索引：[sebastian/](../README.md)

## 模块职责

Sebastian 主 Agent 的具体实现，以及对话平面（Approval 挂起/恢复机制）。
是系统的"大脑入口"：接收用户消息，依托 `BaseAgent` 引擎运行 LLM 循环，按需委派任务给 Sub-Agent，或挂起等待用户审批高危操作。

## 目录结构

```
orchestrator/
├── __init__.py        # 模块入口（空）
├── sebas.py           # Sebastian 类：继承 BaseAgent，定义人格 Prompt、chat()、get_or_create_session()、intervene()
├── conversation.py    # ConversationManager：Approval 挂起/恢复，request_approval() / resolve_approval()
└── tools/             # → [tools/README.md](tools/README.md)
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| Sebastian 人格、系统指令（Prompt） | [sebas.py](sebas.py) 的 `SEBASTIAN_PERSONA` 常量 |
| 对话入口逻辑（Session 创建/复用、消息预处理） | [sebas.py](sebas.py) 的 `chat()` 和 `get_or_create_session()` |
| Sub-Agent 可用列表的 Prompt 注入 | [sebas.py](sebas.py) 的 `_agents_section()` |
| 后台任务提交逻辑 | [sebas.py](sebas.py) 的 `submit_background_task()` |
| 干预（用户主动介入正在执行的 Agent）逻辑 | [sebas.py](sebas.py) 的 `intervene()` |
| Approval 超时时长（默认 300s）、挂起/恢复行为 | [conversation.py](conversation.py) 的 `request_approval()` |
| Approval 审批结果写回（grant/deny REST 回调） | [conversation.py](conversation.py) 的 `resolve_approval()` |
| Sub-Agent 委派工具 | [tools/](tools/README.md) 的 `delegate_to_agent` |
| 新增 Orchestrator 级能力（规划、目标分解，Phase 2+） | 在本目录新建文件 |

## 子模块

- [tools/](tools/README.md) — Orchestrator 专属工具，当前包含 `delegate_to_agent`（通过 A2ADispatcher 将任务委派给 Sub-Agent）

## 数据流

```
用户消息 (HTTP POST /turns)
  → Sebastian.chat()
    → BaseAgent.run_streaming()
      → AgentLoop（LLM turn）
        → 需要工具: CapabilityRegistry.call()
        → 需要审批: ConversationManager.request_approval() [协程挂起]
          → 用户 POST /approvals/{id}/grant → ConversationManager.resolve_approval() [协程恢复]
        → 需要委派: delegate_to_agent → A2ADispatcher.delegate() → Sub-Agent
```

## 公开接口（其他模块如何使用）

```python
# Gateway 通过 state.py 访问，不直接实例化
import sebastian.gateway.state as state

# 发送用户消息
response = await state.sebastian.chat(user_message, session_id)

# 创建或复用 session
session = await state.sebastian.get_or_create_session(session_id, first_message)

# Approval 挂起（在 BaseAgent 的工具执行路径中由 PolicyGate 调用）
granted = await state.conversation.request_approval(
    approval_id, task_id, tool_name, tool_input, reason, session_id
)

# Approval 恢复（由 routes/approvals.py 调用）
await state.conversation.resolve_approval(approval_id, granted=True)
```

---

> 修改本目录或模块后，请同步更新此 README。
