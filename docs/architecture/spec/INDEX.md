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
| [runtime.md](core/runtime.md) | AgentLoop async generator 流式引擎、LLMStreamEvent 类型体系、block_id 规范、BaseAgent streaming + 打断机制、Task 状态机、SSE 事件协议与帧格式 |
| [llm-provider.md](core/llm-provider.md) | LLMProvider 抽象接口、Anthropic/OpenAI 双适配、api_key Fernet 加密、Provider Registry、Thinking Effort 全链路控制（UI → API → Provider）、thinking signature 修复 |
| [system-prompt.md](core/system-prompt.md) | Sebastian 人设提示词、BaseAgent 结构化 prompt 构造体系（persona/tools/skills/agents/knowledge 五段式）、per-agent 工具与 Skill 白名单 |
| [logging.md](core/logging.md) | 三文件日志架构（main/llm_stream/sse）、RotatingFileHandler 轮转策略、LogManager 热切换、Gateway debug API、App Settings UI 集成 |

### 待建模块（后续批次）

| 模块 | 预计内容 |
|------|---------|
| `agents/` | Sub-Agent 自动注册、manifest.toml 规范、AgentConfig、扩展目录机制 |
| `capabilities/` | Tools/MCPs/Skills 三层能力体系、注册与扫描机制、Skill SKILL.md 格式 |
| `mobile/` | Android App 设计（Chat UI、SubAgents 督导、Settings IA、Theme 系统、Composer 等） |
| `gateway/` | Gateway REST API 完整路由表、SSE 管理、认证机制 |
| `infra/` | 发布与 CI/CD 工作流、Docker 部署、Mac mini 原生部署 |

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
