# Gateway Spec 索引

*← [Spec 根索引](../INDEX.md)*

---

Gateway 层设计：SSE 事件流管理、REST API 路由、子代理通信机制。

| Spec | 摘要 |
|------|------|
| [subagent-notification.md](subagent-notification.md) | CompletionNotifier 主动通知、SSE 路由修复（parent_session_id 匹配）、ask_parent/resume_agent 双向通信工具、SessionStatus.WAITING 状态 |
| [agent-stop-resume.md](agent-stop-resume.md) | stop_agent 暂停子代理、resume_agent 恢复（原 reply_to_agent 改名扩展）、SESSION_PAUSED/RESUMED 事件、cancel intent 区分 |

---

*← [Spec 根索引](../INDEX.md)*
