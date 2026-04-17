# Sebastian 架构 Spec 索引

> 本索引是 Sebastian 所有架构设计文档的根入口。
> 按模块分目录组织，每个子目录有独立索引，双向链接。
> 查找某块设计时，从这里出发 → 进入模块索引 → 定位具体 spec。

---

## 模块索引

### [overview/](overview/INDEX.md) — 总体架构与 Agent 模型

Sebastian 的顶层设计：愿景、核心概念、技术栈、三层 Agent 架构、目录结构、分期路线图。

| Spec | 摘要 |
|------|------|
| [architecture.md](overview/architecture.md) | 项目愿景、核心概念（Session 一等公民、非阻塞双路径、能力可扩展）、技术栈、目录结构、扩展规范、数据模型、事件类型、部署架构、分期路线图 |
| [three-tier-agent.md](overview/three-tier-agent.md) | 三层 Agent 模型（Sebastian → 组长 → 组员）、单例 + per-session 并发、对话通道与 LLM 路由、委派/分派工具设计、Stalled 检测、API 与前端变更 |

### [core/](core/INDEX.md) — 核心运行时与基础设施

AgentLoop 流式引擎、LLM Provider 抽象与 Thinking 控制、System Prompt 构造、日志系统。

| Spec | 摘要 |
|------|------|
| [runtime.md](core/runtime.md) | AgentLoop async generator 流式引擎、LLMStreamEvent 类型体系（含 ThinkingBlockStop duration_ms）、block_id 规范、BaseAgent streaming + 打断机制、Task 状态机、SSE 事件协议与帧格式 |
| [llm-provider.md](core/llm-provider.md) | LLMProvider 抽象接口、Anthropic/OpenAI 双适配、api_key Fernet 加密、Provider Registry、Thinking Effort 全链路控制（UI → API → Provider）、thinking signature 修复 |
| [system-prompt.md](core/system-prompt.md) | Sebastian 人设提示词、BaseAgent 结构化 prompt 构造体系（persona/tools/skills/agents/knowledge 五段式）、per-agent 工具与 Skill 白名单 |
| [logging.md](core/logging.md) | 三文件日志架构（main/llm_stream/sse）、RotatingFileHandler 轮转策略、LogManager 热切换、Gateway debug API、App Settings UI 集成 |

### [agents/](agents/INDEX.md) — Agent 系统与权限体系

权限三档体系、Workspace 边界强制、Sub-Agent 配置与知识加载。

| Spec | 摘要 |
|------|------|
| [code-agent.md](agents/code-agent.md) | Forge Agent（原 Code Agent）persona 与工程规范、BaseAgent 知识加载机制（`_knowledge_section`）、manifest.toml 配置 |
| [permission.md](agents/permission.md) | PolicyGate + PermissionReviewer 三档权限（LOW/MODEL_DECIDES/HIGH_RISK）、reason 注入、ToolCallContext、Tool 目录重组 |
| [workspace-boundary.md](agents/workspace-boundary.md) | `_path_utils.py` 路径解析、PolicyGate workspace 边界检查、`_guidelines_section()` 操作规范注入 |
| [agent-naming.md](agents/agent-naming.md) | 移除 `display_name`、统一 `agent_type` 命名、`code` 重命名为 `forge` |

### [capabilities/](capabilities/INDEX.md) — 能力体系

Tools / MCPs / Skills 三层能力注册与实现。

| Spec | 摘要 |
|------|------|
| [core-tools.md](capabilities/core-tools.md) | 六个核心工具规格、ToolResult.display 人类可读摘要、模型侧 JSON 序列化、`_file_state.py` mtime 缓存、Bash 静默命令/语义化退出码/进度心跳 |

### [infra/](infra/INDEX.md) — 基础设施

发布流程、CI/CD 工作流、部署与安装。

| Spec | 摘要 |
|------|------|
| [release-cicd.md](infra/release-cicd.md) | 首次配置 UX（Web 向导 + CLI）、版本管理、bootstrap.sh 一键安装、CI 质量门禁、release.yml 发版、分支保护 |

### [gateway/](gateway/INDEX.md) — Gateway 通信层

Gateway 层设计：SSE 事件流管理、REST API 路由、子代理通信机制。

| Spec | 摘要 |
|------|------|
| [subagent-notification.md](gateway/subagent-notification.md) | CompletionNotifier 主动通知、SSE 路由修复（parent_session_id 匹配）、ask_parent/resume_agent 双向通信、SessionStatus.WAITING |
| [agent-stop-resume.md](gateway/agent-stop-resume.md) | stop_agent 暂停、resume_agent 恢复（原 reply_to_agent 改名）、SESSION_PAUSED/RESUMED、cancel intent |

### [mobile/](mobile/INDEX.md) — Android 原生客户端

Kotlin + Jetpack Compose 原生 Android 客户端架构（替代 React Native 版）。

| Spec | 摘要 |
|------|------|
| [overview.md](mobile/overview.md) | 项目定位、技术栈决策、目录结构、Phase 功能规划、与后端协议对接约定 |
| [navigation.md](mobile/navigation.md) | ThreePaneScaffold 三面板导航、WindowSizeClass 自适应（手机覆盖/平板常驻）、页面路由结构 |
| [streaming.md](mobile/streaming.md) | SSE 连接稳定性架构、流式 Markdown 渲染（multiplatform-markdown-renderer）、ThinkingCard 极简风格、逐块淡入动画、滚动跟随逻辑 |
| [composer.md](mobile/composer.md) | Composer 插槽架构、Phase 1 实现、Phase 2-3 预留扩展路径（语音/附件/全双工）|
| [data-layer.md](mobile/data-layer.md) | Repository 分层、ViewModel + StateFlow、Hilt 注入、本地持久化（DataStore）|
| [global-approval.md](mobile/global-approval.md) | 全局审批系统（GlobalApprovalViewModel + Banner）、SubAgent 对话页复用 ChatScreen、路由变更 |

### 待建模块（后续批次）

暂无待建模块。

---

## 文档规范

每篇 spec 文件头部包含 frontmatter：

```yaml
version: "1.0"           # 语义版本号
last_updated: 2026-04-10 # 最后更新日期
status: implemented | in-progress | planned  # 实施状态
```

- **version**：内容有实质变更时递增（修正错别字不算）
- **last_updated**：每次变更时更新
- **status**：`implemented` = 已在代码中实现；`in-progress` = 部分实现；`planned` = 纯设计未实现

---

*← 返回项目根 [INDEX.md](../../../INDEX.md)*
