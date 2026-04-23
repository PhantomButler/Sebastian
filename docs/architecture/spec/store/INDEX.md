# Store — 持久化层 Spec 索引

*← [Spec 根索引](../INDEX.md)*

---

SQLite 是 session 数据的唯一主存储。`SessionStore` 门面委托给四个 SQLite helper 管理元数据、timeline、任务和 todo。文件系统 JSON 路径已 deprecated，仅保留迁移工具使用。

| Spec | 摘要 |
|------|------|
| [session-storage.md](session-storage.md) | Session/Task/Checkpoint/Todo 从文件系统迁移到 SQLite 的完整设计：数据模型（sessions/session_items/tasks/checkpoints/session_todos/session_consolidations）、schema 迁移策略、存储接口与模块拆分、timeline 写入与 seq 分配、context 投影（Anthropic/OpenAI）、读取视图、上下文压缩模型、IndexStore/EpisodicMemory 退场 |

---

*← [Spec 根索引](../INDEX.md)*
