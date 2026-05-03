# Capabilities 模块 Spec 索引

*← [Spec 根索引](../INDEX.md)*

---

能力体系设计：Tools、MCPs、Skills 三层能力注册与实现。

| Spec | 摘要 |
|------|------|
| [core-tools.md](core-tools.md) | 六个核心工具（Read/Write/Edit/Bash/Glob/Grep）规格、`_file_state.py` mtime 缓存、`_coerce_args` 类型强制转换、权限层级分配、Bash 静默命令识别、语义化退出码、进度心跳、ToolSpec.display_name 后端展示名协议 |
| [agent-file-send.md](agent-file-send.md) | `todo_read`（只读 todo 列表）、`send_file` + `send_file_path` helper（Agent 向用户发送图片/文件）、Tool Result Artifact 持久化链路、SSE `tool.executed` artifact 字段、工具失败返回规范 |
| [screenshot-send.md](screenshot-send.md) | `capture_screenshot_and_send` 截图工具（`PermissionTier.HIGH_RISK`）、macOS/Linux 平台后端、临时文件管理、复用 `send_file_path` helper |

---

*← [Spec 根索引](../INDEX.md)*
