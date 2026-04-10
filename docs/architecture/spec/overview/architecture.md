---
version: "1.0"
last_updated: 2026-04-10
status: in-progress
---

# Sebastian 总体架构设计

*← [Overview 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 项目愿景

Sebastian 是一个目标驱动的个人全能 AI 管家系统，灵感来自黑执事的塞巴斯蒂安与 Overlord 的 Sebas Tian——外表优雅克制，内在能力无上限，随着工具和知识的积累越来越少需要干预，始终随叫随到。

**核心定位**：个人主用 + 受控多用户（家人/访客），自托管部署，不面向企业或大规模用户。

**主要交互入口**：Android App（第一优先），其次 iOS App，辅以 Web UI。

**设计原则**：

- **目标驱动**：接收高层指令，自主分解、规划、执行，不是简单的对话回复
- **持续自主**：任务在后台异步运行，不因用户离开而中断
- **渐进自主**：工具和知识越丰富，需要人工干预的次数越少
- **能力可扩展**：新增工具、Sub-Agent、MCP、Skill、触发器只需创建文件，不改核心代码
- **始终响应**：无论后台运行多少任务，用户交互永远不阻塞

**参照系**：OpenJax 是前驱技术探索。Sebastian 是从零开始的完整实现，继承 OpenJax 的架构经验，不继承其代码。

---

## 2. 核心概念

### 2.1 城堡管理体系（三层垂直树）

用户是城堡主人，Sebastian 是总管家，第二层是各部门组长，第三层是组长安排的组员。

```
用户（城堡主人）
│
├── Sebastian（总管家，depth=1）
│     ├── 理解主人意图，分解目标，委派组长
│     └── 工具：delegate_to_agent, check_sub_agents, inspect_session
│
├── 铁匠（Code Agent 组长，depth=2）
│     ├── 简单任务自己干，复杂任务安排组员
│     ├── 工具：spawn_sub_agent, check_sub_agents, inspect_session + 领域工具
│     └── 组员（depth=3，最多 5 个同时工作）
│
├── 骑士团长（Stock Agent 组长，depth=2）
│     └── ...
└── ...
```

**日常模式**：用户只与 Sebastian 交互，Sebastian 理解目标后协调组长执行。
**磨合期**：用户可直接与组长（depth=2）创建新对话，或干预任意 session（包括组员 depth=3），不经 Sebastian 路由。
**成熟期**：系统能力增长后，用户逐步回归只与 Sebastian 交流。

> 三层模型的完整设计详见 [三层 Agent 架构](three-tier-agent.md)。

### 2.2 Session（会话）——一等公民

Session 是 Sebastian 的核心实体，代表**一次对话线程**。每个工作节点（Sebastian 本体 + 每个 Sub-Agent）各自维护独立的 Session 列表。

```
Session（会话）
├── messages[]              # 消息流，用户与 Agent 的对话记录
└── tasks[]                 # 本次会话触发的执行任务
    ├── Task A（已完成）
    ├── Task B（执行中）
    └── Task C（等待中）
```

**Session 特性**：
- 持久存在，不因 App 关闭或网络断开而中断
- 跨设备可见：App 随时可查看任意 Session 的进度和消息流
- 用户可为 depth≤2 的 agent 直接创建新对话，depth=3 只能干预已有 session

**Session 模型**：

```python
class Session(BaseModel):
    id: str                        # 时间戳_短UUID
    agent_type: str                # "sebastian" / "code" 等
    title: str
    goal: str                      # 会话目标
    status: SessionStatus          # active / idle / completed / failed / stalled / cancelled
    depth: int                     # 1=Sebastian, 2=组长, 3=组员
    parent_session_id: str | None  # 组员 session 指向创建它的组长 session
    last_activity_at: datetime     # 最近一次 stream 事件时间
    created_at: datetime
    updated_at: datetime
    task_count: int
    active_task_count: int
```

**Task 状态机**：

```
Created → Planning → Running → Completed
                   ↘ Failed    ↘ Failed
                               ↘ Cancelled
```

### 2.3 非阻塞执行机制

Sebastian 内部维护两条执行路径以保证对话永不被后台任务阻塞：

- **对话路径**：同步响应用户，永不等待 Task 结果
- **任务路径**：异步后台执行，通过 Event Bus 上报进展

两条路径通过 Event Bus 解耦，Task 的任何状态变更都以事件形式通知对话路径，不直接调用。

### 2.4 Agent 继承模型

所有 Agent（包括 Sebastian 主体和所有 Sub-Agent）继承自 `BaseAgent`。Agent 采用**单例模型**——每个 agent_type 只有一个实例，通过 per-session 并发处理多个任务。

```
BaseAgent
├── Agent Loop（推理 → 工具调用 → 执行 → 上报）
├── 所有基础工具（Shell、文件、Web 搜索等）
├── MCP Client（接入外部工具）
├── Memory 接入（读写共享记忆）
├── per-session 并发（_active_streams: dict[str, Task]）
└── Approval 机制（敏感操作触发审批）

Sebastian（主管家）extends BaseAgent
├── 额外：Goal Decomposer
├── 额外：delegate_to_agent 工具
└── 额外：Conversation Manager（用户交互层）

CodeAgent extends BaseAgent
├── 额外工具：沙箱执行、工具注册
├── 额外：spawn_sub_agent 工具（可分派组员）
└── 专属系统 Prompt：技术工匠人格
```

运行时维护 `state.agent_instances: dict[str, BaseAgent]`，每个 agent_type 一个实例。

### 2.5 协议栈

| 协议 | 用途 | 使用方 |
|------|------|--------|
| **MCP** | 工具接入（外部服务、资源） | 所有 Agent 作为 MCP Client |
| **直接调用 + asyncio.create_task** | Agent 间委派（替代原 A2A 协议） | Sebastian ↔ 组长 ↔ 组员 |
| **SSE** | 前端实时流 | Gateway → 用户界面 |
| **FCM / APNs** | Mobile 推送通知（Phase 3） | Gateway → Mobile App |

### 2.6 Memory 三层结构

```
工作记忆（Working Memory）
└── 当前 Task 上下文，内存存储，Task 结束即清理

情景记忆（Episodic Memory）
└── 历史交互记录，SQLite，支持时序查询

语义记忆（Semantic Memory）
└── 领域知识、用户偏好、工具文档，ChromaDB 向量检索（RAG）
```

所有 Agent 共享全局语义记忆，Sub-Agent 可扩展专属知识集合。

### 2.7 Dynamic Tool Factory

当 Task Executor 发现所需工具不存在时：

1. 委派 Code Agent：描述工具需求
2. Code Agent 生成 Python 代码
3. 沙箱环境测试执行
4. 测试通过后选择：**临时使用** 或 **注册为永久工具**
5. 注册成功后通知所有 Agent 该工具可用（发出 `tool.registered` 事件）

---

## 3. 技术栈

| 层次 | 技术选型 | 理由 |
|------|----------|------|
| 主语言 | Python 3.12+ | 最佳 AI/ML 生态，动态工具创建自然适配 |
| Gateway | FastAPI + asyncio | 高性能异步，SSE 支持好 |
| 数据模型 | Pydantic v2 | 类型安全，序列化性能好 |
| Session 持久化 | 文件系统（JSON + JSONL） | 人类可读，调试直观，个人规模够用 |
| 系统持久化 | SQLite + SQLAlchemy（async） | 非 Session 数据（LLM Provider、事件日志等） |
| 向量记忆 | ChromaDB | 轻量，本地运行，无需外部服务 |
| Agent 间通信 | 直接调用 + asyncio.create_task | 简单高效，同进程无序列化开销 |
| 工具接入 | MCP Python SDK | Anthropic 官方，生态最成熟 |
| LLM 接入 | `sebastian/llm/` 抽象层 | provider 配置持久化在 SQLite，运行时切换，per-agent 模型选择 |
| 沙箱执行 | Docker + subprocess | 代码隔离，资源限制 |
| 部署 | Docker + docker-compose | 解决 Python 分发问题，一键启动 |
| Mobile | React Native（Android → iOS） | 主要交互入口，共享组件逻辑 |
| Web UI | React + TypeScript | 辅助管理界面 |

---

## 4. 项目目录结构

```
sebastian/
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
│
├── sebastian/                    # 主包
│   ├── core/                    # BaseAgent 引擎
│   │   ├── base_agent.py        # BaseAgent 抽象类（单例 + per-session 并发）
│   │   ├── agent_loop.py        # 推理-执行循环（async generator）
│   │   ├── stream_events.py     # LLMStreamEvent 类型定义
│   │   ├── task_manager.py      # Task 状态机
│   │   └── types.py             # Session / Task / EventType 等核心类型
│   │
│   ├── orchestrator/            # Sebastian 主管家
│   │   ├── sebas.py             # 主 Agent 入口
│   │   ├── conversation.py      # 对话平面
│   │   └── goal_decomposer.py   # 高层目标分解
│   │
│   ├── agents/                  # Sub-Agent 插件目录
│   │   ├── _loader.py           # 自动扫描注册（读 manifest.toml）
│   │   └── code/                # Code Agent
│   │       ├── manifest.toml    # 能力声明
│   │       └── agent.py         # 自定义行为
│   │
│   ├── capabilities/            # 统一能力注册与分发
│   │   ├── registry.py          # 工具/MCP/Skill 统一注册表
│   │   ├── tools/               # 通用基础工具 + Agent 专用工具
│   │   │   ├── _loader.py       # 启动时自动扫描注册
│   │   │   ├── delegate_to_agent/  # Sebastian 专用
│   │   │   ├── spawn_sub_agent/    # 组长专用
│   │   │   ├── check_sub_agents/   # Sebastian + 组长共用
│   │   │   ├── inspect_session/    # Sebastian + 组长共用
│   │   │   ├── bash/            # 通用基础工具
│   │   │   ├── read/
│   │   │   ├── write/
│   │   │   ├── edit/
│   │   │   ├── glob/
│   │   │   ├── grep/
│   │   │   └── todo_write/
│   │   ├── mcps/                # MCP Server 集成
│   │   │   └── _loader.py
│   │   └── skills/              # Skill 复合能力
│   │       └── _loader.py
│   │
│   ├── llm/                     # LLM Provider 抽象层
│   │   ├── provider.py          # LLMProvider 抽象基类
│   │   ├── anthropic.py         # Anthropic SDK 适配
│   │   ├── openai_compat.py     # OpenAI 兼容格式适配
│   │   ├── registry.py          # Provider 注册表
│   │   └── crypto.py            # API key Fernet 加密
│   │
│   ├── memory/                  # 记忆系统（Phase 2b）
│   ├── protocol/                # 通信协议
│   │   └── events/              # Event Bus
│   │       ├── bus.py
│   │       └── types.py
│   │
│   ├── gateway/                 # HTTP/SSE 网关
│   │   ├── app.py               # FastAPI 应用
│   │   ├── sse.py               # SSE 实时流推送
│   │   ├── auth.py              # JWT 认证
│   │   └── routes/
│   │       ├── turns.py
│   │       ├── sessions.py
│   │       ├── agents.py
│   │       ├── llm_providers.py
│   │       ├── approvals.py
│   │       ├── stream.py
│   │       └── debug.py
│   │
│   ├── log/                     # 日志系统
│   │   ├── manager.py           # LogManager
│   │   └── schema.py            # LogState / LogConfigPatch
│   │
│   ├── store/                   # 持久化层
│   │   ├── models.py            # SQLAlchemy 数据模型
│   │   ├── session_store.py     # Session 文件存储
│   │   ├── index_store.py       # Session 索引
│   │   ├── task_store.py
│   │   └── event_log.py
│   │
│   ├── identity/                # 身份与权限（Phase 5）
│   ├── trigger/                 # 主动触发引擎（Phase 4）
│   ├── sandbox/                 # 代码执行沙箱
│   └── config.py                # 全局配置
│
├── ui/
│   ├── mobile/                  # React Native App（主要交互入口）
│   └── web/                     # React Web UI（辅助管理）
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## 5. 扩展规范

### 5.1 Sub-Agent 扩展

新增 Sub-Agent 只需在 `agents/` 目录下创建目录 + `manifest.toml`，重启自动注册。

**manifest.toml 格式**：

```toml
[agent]
name = "铁匠"                          # 呈现名，暴露给 Sebastian 和用户
class_name = "CodeAgent"
description = "编写代码、调试问题、构建工具"
max_children = 5                        # 第三级组员并发上限，默认 5
stalled_threshold_minutes = 5           # 卡住检测阈值，默认 5 分钟
allowed_tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
allowed_skills = []
```

**扩展目录**：`{DATA_DIR}/extensions/agents/` 为用户外置扩展目录，同名时用户目录优先。

### 5.2 Tool 扩展

通用工具放 `capabilities/tools/<name>/`，加 `@tool` 装饰器，重启自动注册：

```python
@tool(
    name="fetch_stock_price",
    description="获取指定股票的实时价格",
    requires_approval=False,
    permission_level="owner",
)
async def fetch_stock_price(symbol: str, exchange: str = "A") -> ToolResult:
    ...
```

### 5.3 MCP 扩展

在 `capabilities/mcps/<name>/` 创建 `config.toml`，重启自动连接：

```toml
[mcp]
name = "github"
transport = "stdio"
command = ["uvx", "mcp-server-github"]
env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }
description = "GitHub 仓库、PR、Issues 操作"
```

### 5.4 Skill 扩展

在 `capabilities/skills/<name>/` 创建 `SKILL.md`（frontmatter + 自然语言步骤），重启自动注册。Agent 调用时获取 SKILL.md 正文，按步骤执行。

用户外置扩展目录：`{DATA_DIR}/extensions/skills/`，同名时用户目录优先。

---

## 6. 关键数据模型

### 6.1 LLM Provider

Provider 配置持久化在 SQLite，Agent 启动时通过 `LLMProviderRegistry` 获取对应 provider 实例。

```python
class LLMProviderRecord(Base):
    __tablename__ = "llm_providers"
    id: str                        # uuid
    name: str                      # 用户命名，如 "Claude Opus 家用"
    provider_type: str             # "anthropic" | "openai"
    base_url: str | None           # 自定义 base URL（本地模型/代理）
    api_key_enc: str               # Fernet 加密存储，密钥从 JWT secret 派生
    model: str                     # "claude-opus-4-6" / "gpt-4o" 等
    thinking_format: str | None    # 返回侧 thinking 解析方式
    thinking_capability: str | None  # 请求侧 thinking 能力档位
    is_default: bool               # 全局默认 provider
    created_at: datetime
    updated_at: datetime
```

> LLM Provider 完整设计详见 [core/llm-provider.md](../core/llm-provider.md)。

### 6.2 Session 文件存储结构

```
data/sessions/
├── index.json                          # 全局索引
├── sebastian/
│   └── {session_id}/
│       ├── meta.json                   # session 元信息
│       ├── messages.jsonl              # 消息流（append-only）
│       └── tasks/
│           └── {task_id}.json
├── code/                               # agent_type 直接作为顶层目录
│   └── {session_id}/
└── stock/
```

### 6.3 事件类型（Event Bus）

SSE 帧格式：`id: {seq}\ndata: {"type":"...","data":{...},"ts":"..."}\n\n`
服务端维护 500 条滑动缓冲，断线重连带 `Last-Event-ID` 重放。

```
# Turn 生命周期
turn.received / turn.delta / turn.thinking_delta / turn.response / turn.interrupted

# Block 边界（前端构建 thinking/tool 折叠卡片）
thinking_block.start / thinking_block.stop
text_block.start / text_block.stop
tool_block.start / tool_block.stop

# Task 生命周期
task.created / task.started / task.completed / task.failed / task.cancelled

# 工具生命周期
tool.running / tool.executed / tool.failed

# 审批
approval.requested / approval.granted / approval.denied
```

> SSE 事件协议完整设计详见 [core/runtime.md](../core/runtime.md)。

---

## 7. Mobile App 设计概要

Mobile（Android 优先，iOS 跟进）是 Sebastian 的**主要交互入口**。Web UI 定位为辅助管理界面。

| 功能模块 | 说明 |
|----------|------|
| 对话界面（Chat） | 主屏幕，与 Sebastian 实时对话，消息流式显示 |
| SubAgents 页面 | 督导面板：组长列表 → 点进查看该 Agent 的 Session 列表 |
| Session 详情 | 消息流 + Task 进度 + 纠偏输入框 |
| 审批通知 | 推送通知，App 内一键批准/拒绝 |
| 设置页面 | 服务器地址、LLM Provider 管理、Agent 状态、调试日志 |

**用户对话权限**：

| 操作 | Sebastian | 组长 (depth=2) | 组员 (depth=3) |
|------|-----------|---------------|---------------|
| 用户创建新对话 | ✓ | ✓ | ✗ |
| 用户发消息干预已有 session | ✓ | ✓ | ✓ |

**连接方式**：

| 场景 | 协议 |
|------|------|
| App 在前台 | SSE 长连接（`GET /api/v1/stream`） |
| App 在后台/熄屏 | FCM / APNs 推送（Phase 3） |
| 数据读取/操作 | REST |

---

## 8. 权限与身份体系

| 角色 | Phase 1-4 认证 | Phase 5+ 认证 | 可访问能力 |
|------|---------------|--------------|------------|
| Owner（主人） | 密码 + JWT | 声纹 + 人脸 + 密码 | 全部 |
| Family（家人） | 共享 Token | 声纹 或 人脸 | 日常能力，敏感需 Owner 授权 |
| Guest（访客） | 无需认证（限速） | 语音识别 | 基础问答 |

Phase 5 增加抗 AI 仿冒设计（活体检测、随机挑战、异常降权）。

---

## 9. 部署架构

### docker-compose.yml 服务划分

```yaml
services:
  sebastian:         # 主进程（Gateway + Agent 协程）
  sandbox:           # 代码执行沙箱（隔离）
  chromadb:          # 向量数据库（Phase 2b）
  voice:             # 语音处理（Phase 3）
```

### 最小启动配置

```env
SEBASTIAN_OWNER_NAME=...
SEBASTIAN_GATEWAY_HOST=127.0.0.1
SEBASTIAN_GATEWAY_PORT=8823
# LLM API Key 通过 App Settings 页面管理（加密存储在数据库）
# JWT 签名密钥来自 <data_dir>/secret.key（setup wizard 自动生成）
```

---

## 10. 分期实施计划

### Phase 1 — 核心引擎 ✅ 已完成

- BaseAgent + AgentLoop（streaming async generator，yield LLMStreamEvent）
- Session 模型（agent_type + depth + parent_session_id，无 agent_id）
- Agent 单例模型（agent_instances dict，per-session 并发）
- Task 状态机（_transition 统一状态变更 + 合法性校验）
- EventType block 级事件
- Sebastian 主管家（非阻塞对话路径 + 异步任务路径 + Event Bus）
- Capability Bus（tools/ + mcps/ 扫描注册）
- Session 文件存储（meta.json + messages.jsonl + index.json）
- Gateway（FastAPI + SSE + JWT 认证，SSEManager 500 条缓冲 + 断线重放）
- 日志系统（LogManager 热切换）
- LLM Provider 抽象层（Anthropic + OpenAI 双适配，Fernet 加密，thinking_capability）
- 三层 Agent 架构（delegate_to_agent / spawn_sub_agent / check_sub_agents / inspect_session）
- System Prompt 构造体系（五段式 + per-agent 白名单）
- Thinking Effort 全链路（UI → API → Provider，含 signature 修复）
- Android App（Chat 页、SubAgents 页、Settings 页、SSE 接收）

### Phase 2 — 记忆系统 + 高级 Agent 能力

- Memory System：工作记忆 + 情景记忆（SQLite）+ ChromaDB 语义记忆
- Code Agent（沙箱执行 + Dynamic Tool Factory）
- StockAgent 基础版
- Skills 扫描注册（SKILL.md 格式）
- Android App：Agent 专属记忆展示

### Phase 3 — 语音 + 移动体验提升

- Voice Pipeline：faster-whisper STT + TTS
- iOS App 上线（共享 React Native 代码）
- FCM / APNs 推送
- LifeAgent（日历、智能家居）
- Trigger Engine（APScheduler cron/interval）

### Phase 4 — 触发器进阶 + 更多 Sub-Agent

- 事件触发 + 条件触发
- StockAgent 完整版
- 更多 Sub-Agent（Research、Travel 等）
- Web UI 管理界面完善

### Phase 5 — 身份与生物识别

- 声纹识别 + 人脸识别 + 抗 AI 仿冒
- 多因素权限体系
- 审计日志完善

---

## 11. 与 OpenJax 的关系

OpenJax 是前驱技术探索，已验证的设计经验：

| OpenJax | Sebastian |
|---------|-----------|
| Session 为核心（仅对话） | Session 一等公民（含 Task 子集）+ 三层管理体系 |
| 对话驱动，同步执行 | 非阻塞对话 + 异步 Task 持久执行 |
| 手动注册工具 | 目录扫描自动注册（tools/mcps/skills 三层） |
| 无 Sub-Agent | 三层 Agent 编排（单例 + per-session 并发） |
| 无记忆系统 | 三层 Memory（工作/情景/语义） |
| Web UI 为主 | Mobile（Android）为主 |
| Rust | Python 3.12+ |

---

*← [Overview 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
