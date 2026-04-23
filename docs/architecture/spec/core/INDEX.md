# Core — 核心运行时与基础设施

> 本目录包含 Sebastian 核心引擎的详细设计：流式推理引擎、LLM Provider 抽象、Prompt 构造、日志系统。

*← 返回 [Spec 根索引](../INDEX.md)*

---

## 文档列表

### [runtime.md](runtime.md) — 核心运行时设计

AgentLoop 流式引擎与 SSE 事件协议。涵盖：

- 核心架构决策（独立 SSE 通道、AgentLoop/BaseAgent 职责分层、打断机制选型）
- AgentLoop async generator streaming（LLMStreamEvent 类型、block_id 规范、工具结果回注）
- BaseAgent streaming + 打断机制（cancel + partial + restart）
- Task 状态机（状态转换图、合法转换表、Session 计数维护）
- SSE 事件协议（完整事件表、帧格式、turn/打断事件序列示例、前端约定）
- REST API 路由总表

| 版本 | 状态 | 最后更新 |
|------|------|---------|
| 1.0 | implemented | 2026-04-10 |

---

### [llm-provider.md](llm-provider.md) — LLM Provider 管理与 Thinking 控制

LLM 多 Provider 抽象层 + Agent Binding + Thinking Effort 全链路设计。涵盖：

- LLMProvider 抽象接口（单次调用职责、stream() 签名）
- Anthropic 适配（SDK 事件 → LLMStreamEvent 映射）
- OpenAI 兼容适配（thinking_format 三模式：None / reasoning_content / think_tags）
- LLMProviderRecord 数据模型（api_key Fernet 加密、thinking_capability 字段）
- AgentLLMBindingRecord 数据模型（agent_type PK、provider_id FK、thinking_effort）
- LLMProviderRegistry（binding 表优先查询、ResolvedProvider 返回值、thinking 钳制）
- AgentLoop / BaseAgent 集成（provider 依赖注入、per-turn live 生效）
- Thinking Effort 控制：thinking_capability 五档能力模型、effort 翻译表、从 binding 表读取注入、多轮 thinking signature 修复
- 前端 Thinking 迁移（移除 Composer ThinkButton → Agent Binding EditorPage 持久化配置）
- Gateway CRUD 路由（Provider + Agent Binding）

| 版本 | 状态 | 最后更新 |
|------|------|---------|
| 2.0 | implemented | 2026-04-23 |

---

### [system-prompt.md](system-prompt.md) — System Prompt 构造机制

Agent 结构化 Prompt 构建体系。涵盖：

- Sebastian 角色人设提示词（完整文本）
- BaseAgent prompt 构造方法体系（五段式：persona / guidelines / tools / skills / agents / knowledge）
- per-agent 工具与 Skill 白名单（manifest.toml allowed_tools / allowed_skills）
- CapabilityRegistry 过滤查询扩展
- Sebastian 特化（动态注入 Sub-Agent 列表）

| 版本 | 状态 | 最后更新 |
|------|------|---------|
| 1.0 | implemented | 2026-04-10 |

---

### [logging.md](logging.md) — 日志追踪系统

后端日志模块与运行时热切换。涵盖：

- 日志文件设计（main.log / llm_stream.log / sse.log，10MB 轮转 × 3 备份）
- `sebastian/log/` 模块结构（LogManager 单例、LogState/LogConfigPatch 模型）
- 热切换机制（addHandler / removeHandler，线程安全）
- Gateway debug API（GET/PATCH /api/debug/logging）
- App Settings UI 集成（调试日志 toggle）

| 版本 | 状态 | 最后更新 |
|------|------|---------|
| 1.0 | implemented | 2026-04-10 |
