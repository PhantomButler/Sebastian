# Agents 模块 Spec 索引

*← [Spec 根索引](../INDEX.md)*

---

Agent 系统相关设计：权限体系、Workspace 边界、Sub-Agent 注册与配置。

| Spec | 摘要 |
|------|------|
| [code-agent.md](code-agent.md) | CodeAgent persona 与工程规范设计、BaseAgent 知识加载机制（`_knowledge_section`）、manifest.toml 配置、knowledge 目录结构 |
| [permission.md](permission.md) | PolicyGate + PermissionReviewer 三档权限体系（LOW/MODEL_DECIDES/HIGH_RISK）、reason 注入、ToolCallContext、ApprovalManager 集成、Tool 目录结构重组 |
| [workspace-boundary.md](workspace-boundary.md) | `_path_utils.py` 路径解析、PolicyGate workspace 边界前置检查、PermissionReviewer workspace_dir 注入、BaseAgent `_guidelines_section()` 操作规范 |

---

*← [Spec 根索引](../INDEX.md)*
