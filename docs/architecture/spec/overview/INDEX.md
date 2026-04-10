# Overview — 总体架构与 Agent 模型

> 本目录包含 Sebastian 的顶层架构设计，覆盖项目愿景、核心概念、三层 Agent 模型等全局性决策。

*← 返回 [Spec 根索引](../INDEX.md)*

---

## 文档列表

### [architecture.md](architecture.md) — 总体架构设计

Sebastian 的全局架构蓝图。涵盖：

- 项目愿景与设计原则（目标驱动、持续自主、渐进自主、能力可扩展、始终响应）
- 核心概念：城堡管理体系、Session 一等公民、非阻塞双路径、Agent 继承模型、三层协议栈、Memory 三层结构、Dynamic Tool Factory
- 技术栈选型与理由
- 项目目录结构
- 扩展规范（Sub-Agent / Tool / MCP / Skill）
- 关键数据模型（Session、Task、LLMProviderRecord、Event Types）
- Mobile App 设计概要
- 权限与身份体系
- 部署架构
- 分期实施路线图（Phase 1-5）
- 与 OpenJax 的关系

| 版本 | 状态 | 最后更新 |
|------|------|---------|
| 1.0 | in-progress | 2026-04-10 |

---

### [three-tier-agent.md](three-tier-agent.md) — 三层 Agent 架构设计

替代原有 AgentPool/Worker 多开模型的新架构。涵盖：

- 背景与动机（为什么废弃 AgentPool）
- 三层模型：Sebastian(depth=1) → 组长(depth=2) → 组员(depth=3)
- Agent 单例模型 + per-session 并发
- Session 模型变更（depth、parent_session_id、last_activity_at、新 status 枚举）
- 对话通道与 LLM 路由（每个 agent 用自己的 persona 回复）
- 委派与分派工具设计（delegate_to_agent、spawn_sub_agent、check_sub_agents、inspect_session）
- Stalled 检测机制（watchdog + 阈值 + 处理链路）
- API 接口变更
- 前端变更
- 实现注意事项

| 版本 | 状态 | 最后更新 |
|------|------|---------|
| 1.0 | implemented | 2026-04-10 |
