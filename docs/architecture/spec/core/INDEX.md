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

LLM 三层架构（Catalog → Account → Binding）+ 多 Provider 抽象 + Thinking Effort 全链路设计。涵盖：

- LLMProvider 抽象接口（单次调用职责、stream() 签名）
- Anthropic 适配（SDK 事件 → LLMStreamEvent 映射、TokenUsage 采集）
- OpenAI 兼容适配（thinking_format 三模式、stream_options usage 采集）
- 内置 Catalog JSON + Loader（provider/model 元数据、校验规则）
- LLMAccountRecord（连接与凭据、catalog_provider_id / base_url_override）
- LLMCustomModelRecord（自定义 provider 模型元数据）
- AgentLLMBindingRecord（agent_type PK、account_id + model_id、thinking_effort）
- LLMProviderRegistry 三层解析（binding → account → model_spec → ResolvedProvider）
- Thinking Effort 控制：thinking_capability 五档能力模型、effort 翻译表、全链路透传
- 前端 Binding 编辑页（account + model + effort 三级选择）
- Gateway CRUD 路由（Catalog / Account / Custom Model / Binding 四组 API）

| 版本 | 状态 | 最后更新 |
|------|------|---------|
| 3.0 | implemented | 2026-04-25 |

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

### [context-compaction.md](context-compaction.md) — 上下文自动压缩

Session 短期上下文的运行时压缩系统。涵盖：

- `sebastian/context/` 包结构（TokenUsage、TokenEstimator、ContextTokenMeter、CompactionWorker、prompts）
- Exchange 字段语义与分配流程（exchange_id / exchange_index / next_exchange_index）
- Provider Token Usage 归一化（Anthropic / OpenAI-compatible 映射）
- 触发策略（usage 0.70/0.85、estimate 0.65 三档阈值）
- 压缩范围选择（按完整 exchange 切分、保留最近 N 个、跳过不完整 tool chain）
- Summary 契约（7-section Markdown handoff、memory-relevant facts）
- Timeline 原子更新（compact_range 事务：archive 源记录 + 插入 context_summary）
- Per-turn 模型窗口（context_window_resolver 动态解析，不再硬编码 200k）
- API（POST /compact 手动压缩 + GET /compaction/status 状态查询）

| 版本 | 状态 | 最后更新 |
|------|------|---------|
| 1.0 | implemented | 2026-04-25 |

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
