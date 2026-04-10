# Sebastian 架构设计文档

**版本**：v0.5
**日期**：2026-04-04
**状态**：Phase 1 已完成，Phase 2a 规划中

> v0.5 更新：Phase 1 标记为已完成；Phase 2 拆分为 2a（完整链路优先）和 2b（记忆与高级能力）；新增 LLM Provider 管理子系统（DB 持久化、多 provider 切换、per-agent 模型选择）；目录结构新增 `sebastian/llm/`；数据模型新增 `LLMProviderRecord`；App Settings 页补充 LLM provider 管理。

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

### 2.1 城堡管理体系（垂直树）

Sebastian 是一个城堡管家团队。用户是城堡主人，Sebastian 是总管家，SubAgents 是各司其职的专属角色（金融顾问、技术工匠、日常管家等）。

```
你（城堡主人）
    │
    ├── Sebastian（总管家）
    │     └── 负责与主人对话、分解目标、协调下属
    │
    ├── StockAgent（金融顾问）
    ├── CodeAgent（技术工匠）
    ├── LifeAgent（日常管家）
    └── ... 其他专属角色
```

**日常模式**：用户只与 Sebastian 交互，Sebastian 理解目标后协调 SubAgents 执行。
**磨合期**：用户可直接督导任意 SubAgent，观察进度、发送纠偏指令，不需要经过 Sebastian 路由。
**成熟期**：系统能力增长后，用户逐步回归只与 Sebastian 交流，由他管理一切。

### 2.2 Session（会话）——一等公民

Session 是 Sebastian 的核心实体，代表**一次对话线程**。每个工作节点（Sebastian 本体 + 每个 SubAgent）各自维护独立的 Session 列表。

**Session 层级关系**：
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
- SubAgent 的 Session 由 Sebastian 委派创建，不由用户直接发起
- 跨设备可见：App 随时可查看任意 Session 的进度和消息流

**Task 状态机**（Task 是 Session 的子集）：
```
Created → Planning → Running → [Paused] → Running → Completed
                                         ↘ Failed
                                         ↘ Cancelled
```

**Task 组成**：
- `goal`：本次任务的目标描述
- `plan`：Planner 分解的子任务 DAG
- `checkpoints`：每步执行结果（append-only，存于 Session 文件夹）
- `assigned_agent`：负责执行的 Agent
- `resource_budget`：并发/成本限额

### 2.2.1 非阻塞执行机制（实现细节）

Sebastian 内部维护两条执行路径以保证对话永不被后台任务阻塞：

- **对话路径**：同步响应用户，永不等待 Task 结果
- **任务路径**：异步后台执行，通过 Event Bus 上报进展

两条路径通过 Event Bus 解耦，Task 的任何状态变更都以事件形式通知对话路径，不直接调用。这是内部实现保证，不对外暴露为独立概念。

### 2.3 Agent 继承模型

所有 Agent（包括 Sebastian 主体和所有 Sub-Agent）继承自 `BaseAgent`：

```
BaseAgent
├── 完整 Agent Loop（计划 → 工具调用 → 执行 → 上报）
├── 所有基础工具（Shell、文件、Web 搜索等）
├── MCP Client（接入外部工具）
├── Memory 接入（读写共享记忆）
├── Task Queue（并行任务管理）
├── A2A 接口（接收委派 / 上报结果 / 升级请求）
└── Approval 机制（敏感操作触发审批）

Sebastian（主管家）extends BaseAgent
├── 额外：Goal Decomposer
├── 额外：Agent Router（选择合适 Sub-Agent 委派）
└── 额外：Conversation Manager（用户交互层）

StockAgent extends BaseAgent
├── 额外工具：行情 API、技术指标、回测引擎
├── 专属知识库：金融分析框架、持仓历史（ChromaDB）
└── 专属系统 Prompt：金融分析师人格

CodeAgent extends BaseAgent
├── 额外工具：沙箱执行、单测生成、工具注册
├── 专属知识库：代码库 RAG、常用模式
└── 特殊角色：Dynamic Tool Factory

LifeAgent extends BaseAgent
├── 额外工具：日历、智能家居、外卖/预订
├── 专属知识库：家庭成员档案、个人偏好
└── 权限特殊：访客部分可用（Identity 层控制）
```

**Sub-Agent 进程模型**（Phase 1-2 采用，Phase 3+ 可按需迁移）：

所有 Agent 运行在同一个 Python 进程中，以 `asyncio` 协程并发执行。A2A 消息通过内存队列传递，接口设计完全符合 A2A 规范，迁移到独立进程时只需替换传输层。
选择同进程模型原因：无需进程管理、调试简单、内存共享省去序列化开销。隔离性靠沙箱（代码执行）和权限系统（数据访问）来补偿，不靠进程隔离。

> **⚠️ 已废弃** — AgentPool / Worker 多开模型已被三层 Agent 架构替代。Agent 改为单例 + per-session 并发，移除 worker/agent_id 概念。详见 [三层 Agent 架构设计](2026-04-06-three-tier-agent-architecture-design.md) §3.1。

~~**AgentPool / Worker 多开模型**~~：

~~每个 `agent_type`（如 stock、code）可同时运行最多 **3 个** worker 实例，worker 有固定身份（`stock_01` / `stock_02` / `stock_03`），用完释放回 pool，超限任务进队列等待。~~

```
# 已废弃，保留仅作历史参考
StockAgent（agent_type，队长）
├── stock_01（worker，状态: busy，当前 session: xxx）
├── stock_02（worker，状态: busy，当前 session: yyy）
├── stock_03（worker，状态: idle）
└── 等待队列: [task_004, task_005]
```

~~Worker 采用持久身份（非临时实例），理由：App 需展示具体 worker 状态，Phase 2 可为每个 worker 建立专属 episodic memory。Sebastian 本体只有 1 个 worker（`sebastian_01`）。~~

### 2.4 三层协议栈

> **⚠️ A2A 部分已废弃** — Agent 间通信不再使用 A2A 协议的 queue + future 机制，改为直接调用 + asyncio.create_task 异步委派。详见 [三层 Agent 架构设计](2026-04-06-three-tier-agent-architecture-design.md) §4。

| 协议 | 用途 | 使用方 | 状态 |
|------|------|--------|------|
| **MCP** | 工具接入（外部服务、资源） | 所有 Agent 作为 MCP Client | 不变 |
| ~~**A2A**~~ | ~~Agent 间通信（任务委派/上报/升级）~~ | ~~Sebastian ↔ Sub-Agent~~ | 已废弃，改为直接调用 |
| **SSE / FCM** | 前端实时流 / Mobile 推送通知 | Gateway → 用户界面 | 不变 |

### 2.5 Memory 三层结构

```
工作记忆（Working Memory）
└── 当前 Task 上下文，内存存储，Task 结束即清理

情景记忆（Episodic Memory）
└── 历史交互记录，SQLite，支持时序查询

语义记忆（Semantic Memory）
└── 领域知识、用户偏好、工具文档，ChromaDB 向量检索（RAG）
```

所有 Agent 共享全局语义记忆，Sub-Agent 可扩展专属知识集合。

### 2.6 Dynamic Tool Factory

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
| Session 持久化 | 文件系统（JSON + JSONL） | 人类可读，调试直观，个人规模够用；架构成熟后可迁移至数据库 |
| 系统持久化 | SQLite + SQLAlchemy（async） | 用于非 Session 数据（触发器配置、工具注册、事件日志等） |
| 向量记忆 | ChromaDB | 轻量，本地运行，无需外部服务 |
| Agent 通信 | Google A2A 规范（同进程内存队列实现） | 开放标准，接口稳定，之后可迁独立进程 |
| 工具接入 | MCP Python SDK | Anthropic 官方，生态最成熟 |
| LLM 接入 | `sebastian/llm/` 抽象层（Anthropic SDK + OpenAI chat completion） | provider 配置持久化在 SQLite，运行时切换，per-agent 模型选择 |
| 任务调度 | APScheduler | 轻量，支持 cron/interval/date 三种触发 |
| 沙箱执行 | Docker + subprocess | 代码隔离，资源限制 |
| 语音识别 | faster-whisper | 本地运行，速度快（Phase 3） |
| 声纹/人脸识别 | resemblyzer / DeepFace | 生物识别（Phase 5） |
| 部署 | Docker + docker-compose | 解决 Python 分发问题，一键启动 |
| Web UI | React + TypeScript | 辅助管理界面 |
| Mobile | React Native（Android → iOS） | 主要交互入口，共享组件逻辑 |
| Mobile 推送 | FCM（Android）/ APNs（iOS） | 后台任务通知 |

---

## 4. 项目目录结构

```
sebastian/
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
│
├── sebastian/                    # 主包
│   ├── core/                    # BaseAgent 引擎（所有 Agent 的基础）
│   │   ├── base_agent.py        # BaseAgent 抽象类
│   │   ├── agent_loop.py        # 推理-执行-上报循环
│   │   ├── task_manager.py      # Task 队列与并行执行
│   │   ├── planner.py           # 目标 → 子任务 DAG
│   │   └── checkpoint.py        # 检查点读写
│   │
│   ├── orchestrator/            # Sebastian 主管家
│   │   ├── sebas.py             # 主 Agent 入口
│   │   ├── conversation.py      # 对话平面（永不阻塞）
│   │   ├── agent_router.py      # 任务 → Sub-Agent 路由
│   │   └── goal_decomposer.py   # 高层目标分解
│   │
│   ├── agents/                  # Sub-Agent 插件目录
│   │   ├── _loader.py           # 自动扫描注册（读 manifest.toml）
│   │   ├── stock/
│   │   │   ├── manifest.toml    # 能力声明（必需，唯一注册入口）
│   │   │   ├── agent.py         # 可选：覆盖 BaseAgent 特定行为
│   │   │   ├── tools/           # 该 Agent 专属工具（@tool 装饰器）
│   │   │   │   ├── market_data.py
│   │   │   │   └── backtest.py
│   │   │   └── knowledge/       # 专属知识库文件（RAG 索引源）
│   │   ├── code/
│   │   │   ├── manifest.toml
│   │   │   ├── agent.py         # Tool Factory 逻辑
│   │   │   └── tools/
│   │   ├── life/
│   │   │   ├── manifest.toml
│   │   │   └── tools/
│   │   └── <new_agent>/         # 新增 Sub-Agent：只需这个目录 + manifest.toml
│   │       └── manifest.toml
│   │
│   ├── capabilities/            # Capability Bus（统一能力注册与分发）
│   │   ├── registry.py          # 工具/MCP/Skill 统一注册表
│   │   │
│   │   ├── tools/               # 通用基础工具（所有 Agent 可用）
│   │   │   ├── _loader.py       # 启动时自动扫描注册
│   │   │   ├── shell.py         # Shell 命令执行
│   │   │   ├── file_ops.py      # 文件读写
│   │   │   ├── web_search.py    # 网页搜索
│   │   │   ├── http_request.py  # HTTP 请求
│   │   │   └── <new_tool>.py    # 新增工具：放入此目录即自动注册
│   │   │
│   │   ├── mcps/                # MCP Server 集成（每个 MCP 独立子目录）
│   │   │   ├── _loader.py       # 扫描并连接各 MCP Server
│   │   │   ├── github/
│   │   │   │   └── config.toml  # MCP Server 地址、认证、能力声明
│   │   │   ├── filesystem/
│   │   │   │   └── config.toml
│   │   │   └── <new_mcp>/       # 新增 MCP：创建目录 + config.toml 即可
│   │   │       └── config.toml
│   │   │
│   │   ├── skills/              # Skill（复合多步能力，可跨工具编排）
│   │   │   ├── _loader.py       # 扫描注册
│   │   │   ├── research/        # 示例：研究类 Skill
│   │   │   │   ├── manifest.toml
│   │   │   │   └── steps.py     # Skill 步骤定义
│   │   │   └── <new_skill>/     # 新增 Skill：目录 + manifest.toml
│   │   │       └── manifest.toml
│   │   │
│   │   ├── mcp_client.py        # MCP Client 封装
│   │   └── tool_factory.py      # Dynamic Tool 注册与生命周期
│   │
│   ├── llm/                     # LLM Provider 抽象层（Phase 2a）
│   │   ├── provider.py          # LLMProvider 抽象基类（stream / complete 接口）
│   │   ├── anthropic.py         # Anthropic SDK 适配
│   │   ├── openai_compat.py     # OpenAI chat completion 格式适配（兼容所有 /v1/chat/completions）
│   │   └── registry.py          # 从 DB 加载 provider，提供 get_provider(agent_type?) 接口
│   │
│   ├── memory/                  # 记忆系统
│   │   ├── working_memory.py    # 工作记忆（内存）
│   │   ├── episodic_memory.py   # 情景记忆（SQLite）
│   │   ├── semantic_memory.py   # 语义记忆（ChromaDB RAG）
│   │   └── store.py             # 统一 Memory 接口
│   │
│   ├── protocol/                # 通信协议实现
│   │   ├── a2a/
│   │   │   ├── server.py        # A2A Server（接收委派/上报）
│   │   │   ├── client.py        # A2A Client（发送委派/查询）
│   │   │   └── types.py         # Task/Result/Escalation 类型
│   │   └── events/
│   │       ├── bus.py           # Event Bus（解耦双平面）
│   │       └── types.py         # 事件类型定义（见第 7 节）
│   │
│   ├── gateway/                 # HTTP/SSE 网关
│   │   ├── app.py               # FastAPI 应用
│   │   ├── sse.py               # SSE 实时流推送
│   │   ├── push.py              # FCM/APNs Mobile 推送通知
│   │   ├── auth.py              # 认证（JWT）
│   │   └── routes/
│   │       ├── turns.py         # POST /turns（发送消息/指令）
│   │       ├── tasks.py         # Task CRUD API
│   │       ├── approvals.py     # 审批 API
│   │       ├── agents.py        # Agent 状态 API
│   │       └── stream.py        # GET /stream SSE 事件流
│   │
│   ├── identity/                # 身份与权限（Phase 5）
│   │   ├── voiceprint.py        # 声纹识别（resemblyzer）
│   │   ├── faceprint.py         # 人脸识别（DeepFace）
│   │   ├── anti_spoof.py        # 抗 AI 仿冒检测
│   │   ├── permission.py        # 权限分级（Owner/Family/Guest）
│   │   └── policy.py            # 权限决策引擎
│   │
│   ├── trigger/                 # 主动触发引擎（Phase 4）
│   │   ├── scheduler.py         # APScheduler 封装（cron/interval）
│   │   ├── event_trigger.py     # 事件驱动触发
│   │   ├── condition_engine.py  # 条件触发（if X then task Y）
│   │   └── trigger_loader.py    # 触发器配置自动加载
│   │
│   ├── sandbox/                 # 代码执行沙箱
│   │   ├── executor.py          # 安全执行入口
│   │   ├── docker_backend.py    # Docker 隔离执行
│   │   ├── resource_limits.py   # CPU/内存限制
│   │   └── audit.py             # 执行审计日志
│   │
│   ├── store/                   # 持久化层
│   │   ├── models.py            # SQLAlchemy 数据模型
│   │   ├── task_store.py        # Task 状态持久化
│   │   ├── event_log.py         # Append-only 事件日志
│   │   └── migrations/          # Alembic 数据库迁移
│   │
│   └── config.py                # 全局配置（env 变量）
│
├── knowledge/                   # 知识库文件（RAG 索引源，agents 共享）
├── data/                        # 运行时数据（SQLite、ChromaDB 索引等）
│
├── ui/
│   ├── web/                     # React Web UI（辅助管理界面）
│   └── mobile/                  # React Native App（主要交互入口）
│       ├── android/
│       ├── ios/
│       └── src/
│           ├── screens/
│           ├── components/
│           └── api/             # Gateway API 客户端
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## 5. Sub-Agent 扩展规范

> **⚠️ 已更新** — manifest.toml 格式已简化，移除 worker/concurrency 概念，新增 `max_children`、`stalled_threshold_minutes`、agent 呈现名（`name`）。详见 [三层 Agent 架构设计](2026-04-06-three-tier-agent-architecture-design.md) §10。

### manifest.toml 格式（新版）

```toml
[agent]
name = "铁匠"                          # 呈现名，暴露给 Sebastian 和用户
class_name = "CodeAgent"
description = "编写代码、调试问题、构建工具"
max_children = 5                        # 第三级组员并发上限，默认 5
stalled_threshold_minutes = 5           # 卡住检测阈值，默认 5 分钟

# 工具 / 技能权限
allowed_tools = ["bash_execute", "file_read", "file_write", "web_search"]
allowed_skills = ["research"]
```

### 新增 Sub-Agent 步骤

1. 在 `agents/` 目录下创建新目录，如 `agents/research/`
2. 创建 `manifest.toml`（最小配置即可运行）
3. 可选：创建 `agent.py` 覆盖特定 BaseAgent 行为
4. 可选：在 `agents/<name>/knowledge/` 下添加专属知识库文件
5. 重启 Sebastian，自动注册

---

## 6. 工具扩展规范

**通用工具**（放 `capabilities/tools/`，所有 Agent 可用）：

```python
# capabilities/tools/fetch_stock_price.py
from sebastian.core.tool import tool, ToolResult

@tool(
    name="fetch_stock_price",
    description="获取指定股票的实时价格",
    requires_approval=False,
    permission_level="owner",
)
async def fetch_stock_price(symbol: str, exchange: str = "A") -> ToolResult:
    """
    Args:
        symbol: 股票代码
        exchange: 交易所 (A=A股, HK=港股, US=美股)
    """
    ...
    return ToolResult(ok=True, output={"price": 42.0, "symbol": symbol})
```

**MCP 扩展**（放 `capabilities/mcps/<name>/config.toml`）：

```toml
[mcp]
name = "github"
transport = "stdio"           # stdio / sse
command = ["uvx", "mcp-server-github"]
env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }
description = "GitHub 仓库、PR、Issues 操作"
```

**Skill 扩展**（放 `capabilities/skills/<name>/`）：

```toml
# manifest.toml
[skill]
name = "deep_research"
description = "多轮搜索 + 综合分析 + 报告生成"
steps = ["web_search", "content_extract", "summarize", "write_report"]
```

工具/MCP/Skill 各自目录在启动时被对应 `_loader.py` 自动扫描注册，所有 Agent 立即可用。

---

## 7. 关键数据模型

### LLM Provider 管理

**设计原则**：provider 配置持久化在 SQLite，Agent 启动时通过 `LLMProviderRegistry` 获取对应 provider 实例，`AgentLoop` 依赖注入 `LLMProvider` 抽象，不直接 import 任何 SDK。

**加密方案**：`api_key_enc` 使用 Fernet（AES-128-CBC + HMAC）加密存储。加密密钥从 `SEBASTIAN_JWT_SECRET` 派生（`SHA-256(jwt_secret)` → 32 字节 → Base64 编码），无需额外 env var。实现位于 `sebastian/llm/crypto.py`，对外暴露 `encrypt(plain) -> str` / `decrypt(enc) -> str` 两个函数。GET 接口不返回 `api_key_enc` 字段。

**SQLite 数据模型**：

```python
class LLMProviderRecord(Base):
    __tablename__ = "llm_providers"

    id: str               # uuid
    name: str             # 用户命名，如 "Claude Opus 家用"
    provider_type: str    # "anthropic" | "openai"（决定请求格式）
    base_url: str | None  # 自定义 base URL（本地模型/代理；None 则用 SDK 默认）
    api_key_enc: str      # Fernet 加密存储，密钥从 SEBASTIAN_JWT_SECRET 派生，启动时解密
    model: str            # "claude-opus-4-5" / "gpt-4o" 等
    is_default: bool      # 全局默认 provider
    created_at: datetime
    updated_at: datetime
```

**per-agent 模型选择**：在 `manifest.toml` 中声明（可选，不填则使用全局默认）：

```toml
[llm]
provider_type = "anthropic"   # 指定 provider 类型
model = "claude-haiku-4-5"    # 指定模型（LifeAgent 用轻量模型节省成本）
```

**LLMProvider 抽象接口**（`sebastian/llm/provider.py`）：

```python
class LLMProvider(ABC):
    @abstractmethod
    async def stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncGenerator[LLMStreamEvent, None]: ...
```

**Gateway 新增路由**：

```
GET    /api/v1/llm/providers              # 列出所有 provider（api_key 不返回明文）
POST   /api/v1/llm/providers              # 新增
PUT    /api/v1/llm/providers/{id}         # 修改
DELETE /api/v1/llm/providers/{id}         # 删除
POST   /api/v1/llm/providers/{id}/set-default  # 设为全局默认
```

---

### Session 文件存储结构

> **⚠️ 已更新** — 移除 `subagents/` 中间层和 `agent_id` 目录，所有 agent 的 session 直接按 `agent_type/session_id/` 存储。详见 [三层 Agent 架构设计](2026-04-06-three-tier-agent-architecture-design.md) §12.2。

```
data/sessions/
├── index.json                          # 全局索引，App 快速加载列表用
├── sebastian/
│   └── 2026-04-02T10-30-00_abc123/    # session_id = 时间戳 + 短 UUID
│       ├── meta.json                   # session 元信息
│       ├── messages.jsonl              # 消息流（append-only，一行一条）
│       └── tasks/
│           ├── task_001.json           # task 元信息 + 最终状态
│           └── task_001.jsonl          # task checkpoint 流（append-only）
├── stock/                              # agent_type 直接作为顶层目录
│   └── 2026-04-02T11-00-00_def456/
│       ├── meta.json
│       ├── messages.jsonl
│       └── tasks/
└── code/
```

**`meta.json`** — session 元信息：
```json
{
  "id": "2026-04-02T10-30-00_abc123",
  "agent": "sebastian",
  "title": "研究近期股票行情",
  "status": "active",
  "created_at": "2026-04-02T10:30:00Z",
  "updated_at": "2026-04-02T11:45:00Z",
  "task_count": 2,
  "active_task_count": 1
}
```

**`messages.jsonl`** — append-only，一行一条：
```jsonl
{"role":"user","content":"帮我研究近期行情","ts":"2026-04-02T10:30:01Z"}
{"role":"assistant","content":"好的，我来安排...","ts":"2026-04-02T10:30:03Z"}
```

**`index.json`** — 轻量索引，App 启动时一次加载，按需读取详情：
```json
{
  "version": 1,
  "sessions": [
    {"id": "...", "agent": "sebastian", "title": "...", "status": "active", "updated_at": "..."},
    {"id": "...", "agent": "stock", "title": "...", "status": "idle", "updated_at": "..."}
  ]
}
```

**索引维护**：Session 创建/更新/结束时同步更新 `index.json`，in-process 写入，无需事务。

### Session 与 Task

> **⚠️ 已更新** — Session 模型移除 `agent_id`，新增 `depth`、`parent_session_id`、`last_activity_at`，status 新增 `completed`/`failed`/`stalled`/`cancelled`。详见 [三层 Agent 架构设计](2026-04-06-three-tier-agent-architecture-design.md) §3.2。

```python
class Session(BaseModel):
    id: str                        # 时间戳_短UUID
    agent_type: str                # "sebastian" / "stock" 等（agent 类型）
    title: str                     # 会话标题（首条消息自动生成）
    status: SessionStatus          # active / idle / completed / failed / stalled / cancelled
    depth: int                     # 1=Sebastian, 2=组长, 3=组员
    parent_session_id: str | None  # 组员 session 指向创建它的组长 session
    last_activity_at: datetime     # 最近一次 stream 事件时间
    created_at: datetime
    updated_at: datetime

class Task(BaseModel):
    id: str                          # task_001, task_002...
    session_id: str                  # 所属 Session
    goal: str                        # 任务目标描述
    plan: TaskPlan | None            # 分解后的子任务 DAG
    status: TaskStatus               # Created/Planning/Running/Paused/Completed/Failed/Cancelled
    assigned_agent: str              # 负责的 Agent name
    parent_task_id: str | None       # 父任务（支持嵌套）
    resource_budget: ResourceBudget  # 并发/成本限额
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    # checkpoints 单独存于 task_<id>.jsonl，不内联
```

### A2A 消息类型

> **⚠️ 已废弃** — A2A 消息类型（`DelegateTask`、`EscalateRequest`、`TaskResult`）不再使用。Agent 间通信改为工具调用 + asyncio.create_task + event bus 事件通知。详见 [三层 Agent 架构设计](2026-04-06-three-tier-agent-architecture-design.md) §4、§5。

```python
# 已废弃，保留仅作历史参考
# Jarvis → Sub-Agent
class DelegateTask(BaseModel): ...
# Sub-Agent → Jarvis（遇阻时）
class EscalateRequest(BaseModel): ...
# Sub-Agent → Jarvis（完成时）
class TaskResult(BaseModel): ...
```

### 事件类型（Event Bus）

SSE 帧格式：`id: {seq}\ndata: {"type":"...","data":{...},"ts":"..."}\n\n`
服务端维护 500 条滑动缓冲，断线重连带 `Last-Event-ID` 重放。

```
# Turn 生命周期（对话平面）
turn.received                # 用户消息进入
turn.delta                   # LLM 文字 token（含 block_id）
turn.thinking_delta          # LLM thinking token（含 block_id，extended thinking）
turn.response                # 整个 turn 正常结束（含完整 content）
turn.interrupted             # 用户打断，生成取消（含 partial_content）

# Block 边界（前端用于构建 thinking/tool 折叠卡片，block_id 格式：b{iteration}_{index}）
thinking_block.start / thinking_block.stop
text_block.start / text_block.stop
tool_block.start / tool_block.stop   # tool_block.start 时 name 已知，stop 时 inputs 完整

# Task 生命周期
task.created
task.planning_started / task.planning_failed
task.started / task.paused / task.resumed
task.completed / task.failed / task.cancelled

# Agent 协同
agent.delegated              # Sebastian 成功委派给 Sub-Agent worker
agent.delegated.failed       # 委派失败（worker 全忙且队列满）
agent.escalated              # Sub-Agent 向 Sebastian 上报请求决策
agent.escalated.failed       # 上报失败（超时、无响应）
agent.result_received        # Sub-Agent 返回结果

# 用户交互
user.intervened              # 用户直接向 SubAgent 发送纠偏指令（静默通知 Sebastian）
approval.requested           # 等待用户审批（敏感操作）
approval.granted             # 用户批准
approval.denied              # 用户拒绝

# 工具生命周期
tool.registered              # 工具注册成功（含 Dynamic Tool）
tool.registered.failed       # 工具注册失败（代码错误、沙箱验证失败）
tool.running                 # 工具开始执行
tool.executed                # 工具执行成功
tool.failed                  # 工具执行失败（含错误信息）

# 触发器
trigger.scheduled            # 触发器已安排
trigger.fired                # 触发器激活，开始执行目标任务
trigger.fired.failed         # 触发器激活后任务创建/启动失败

# 身份
identity.verified            # 身份验证通过
identity.failed              # 身份验证失败
identity.downgraded          # 行为异常，权限降级
```

---

## 8. Mobile App 设计

### 交互定位

Mobile（Android 优先，iOS 跟进）是 Sebastian 的**主要交互入口**。Web UI 定位为辅助管理界面（配置、调试）。

### 核心功能

| 功能模块 | 说明 |
|----------|------|
| 对话界面（Chat） | 主屏幕，与 Sebastian 实时对话，消息流式显示 |
| SubAgents 页面 | 督导面板：SubAgent 列表 → 点进查看该 Agent 的 Session 列表 |
| Session 详情 | 消息流 + Task 进度列表 + 纠偏输入框（可向 SubAgent 直接发指令） |
| 审批通知 | Sebastian 请求决策时推送通知，App 内一键批准/拒绝 |
| 语音输入 | 按住说话，STT 转文字后发送（Phase 3） |
| 快捷指令 | 常用命令快捷入口（可配置） |
| 设置页面 | 服务器地址、通知偏好；LLM Provider 管理（增删改、设为默认）；Agent 状态总览 |

### SubAgent 督导模型

> **⚠️ 已更新** — 用户现在可以直接和组长（depth=2）创建新对话，不再局限于 Sebastian 委派创建。详见 [三层 Agent 架构设计](2026-04-06-three-tier-agent-architecture-design.md) §2.2、§8。

用户可以通过两种方式与 SubAgent 交互：
1. **创建新对话**：在组长 session 列表页点击「新对话」，直接与该 agent 开始对话
2. **干预已有 session**：点进已有 session 发消息，消息直达该 agent，不经 Sebastian 路由

### 移动端与服务端数据协议

**连接方式**：

| 场景 | 协议 |
|------|------|
| App 在前台 | SSE 长连接（`GET /api/v1/stream`） |
| App 在后台/熄屏 | FCM（Android）/ APNs（iOS）推送通知 |
| 数据读取/操作 | REST（JSON over HTTPS） |

**REST API（Gateway 暴露）**：

```
# 认证
POST   /api/v1/auth/login

# 对话（Sebastian 主入口）
POST   /api/v1/turns                          # 立即返回 {session_id, ts}，内容走 SSE

# Session
GET    /api/v1/sessions                       # 全局索引，支持 agent_type/status 过滤
GET    /api/v1/sessions/{id}                  # Session 详情（meta + messages）
GET    /api/v1/agents/{agent_type}/sessions   # 指定 agent_type 的所有 sessions（跨 worker）
GET    /api/v1/agents/{agent_type}/workers/{agent_id}/sessions  # 指定 worker 的 sessions

# Turn（SubAgent 纠偏 / 继续对话）
POST   /api/v1/sessions/{id}/turns            # 向指定 Session 发送消息，触发 user.intervened

# Task
GET    /api/v1/sessions/{id}/tasks
GET    /api/v1/sessions/{id}/tasks/{task_id}
POST   /api/v1/sessions/{id}/tasks/{task_id}/cancel

# 审批
GET    /api/v1/approvals
POST   /api/v1/approvals/{id}/grant
POST   /api/v1/approvals/{id}/deny

# SSE
GET    /api/v1/stream                         # 全局实时事件流（Sebastian 主页用）
GET    /api/v1/sessions/{id}/stream           # 单 Session 事件流（SubAgent 详情页用）

# 语音（Phase 3）
POST   /api/v1/voice/transcribe

# 系统
GET    /api/v1/agents                         # agent 列表 + 每个 worker 状态 + queue_depth
GET    /api/v1/health
```

**`POST /api/v1/turns` 立即返回，不等 LLM**：

```json
// Request
{ "content": "帮我分析港股近期走势", "session_id": "..." }
// Response 200
{ "session_id": "2026-04-03T10-30-00_abc123", "ts": "2026-04-03T10:30:01Z" }
```

**`GET /api/v1/agents` 返回 agent 状态**：

> **⚠️ 已更新** — 移除 `workers` 数组，改为 `active_session_count` + `max_children`。详见 [三层 Agent 架构设计](2026-04-06-three-tier-agent-architecture-design.md) §7.2。

```json
{
  "agents": [
    {
      "agent_type": "stock",
      "name": "骑士团长",
      "description": "金融顾问",
      "active_session_count": 2,
      "max_children": 5
    }
  ]
}
```

**FCM/APNs Push Payload**：

```json
{
  "type": "approval.required",
  "task_id": "abc123",
  "title": "需要你的决策",
  "body": "StockAgent 发现一个买入时机，是否授权下单？",
  "data": {
    "approval_id": "ap456",
    "options": ["批准", "拒绝", "查看详情"]
  }
}
```

**认证**：JWT Token，登录时由 Gateway 颁发，后续所有请求携带 `Authorization: Bearer <token>`。Phase 5 加入生物识别后，JWT 颁发流程引入多因素验证。

---

## 9. 权限与身份体系

### 用户角色（Phase 1-4 简化版：密码/Token 认证）

| 角色 | Phase 1-4 认证方式 | Phase 5+ 认证方式 | 可访问能力 |
|------|------------------|------------------|------------|
| Owner（主人） | 密码 + JWT | 声纹 + 人脸 + 密码 | 全部能力 |
| Family（家人） | 共享 Token | 声纹 或 人脸 | 日常能力，敏感需 Owner 授权 |
| Guest（访客） | 无需认证（限速） | 语音识别（非声纹） | 基础问答、接待对话 |

### 抗 AI 仿冒设计（Phase 5）

- 声纹识别结合活体检测（liveness detection），防止播放录音
- 人脸识别结合眨眼/转头随机挑战，防止照片攻击
- 高权限操作（如金融交易、系统配置）要求多模态同时验证
- 异常行为触发降级：识别成功但行为模式异常时，悄默降为更低权限

---

## 10. 部署架构

### docker-compose.yml 服务划分

```yaml
services:
  sebastian:         # 主 Agent 进程（含所有 Sub-Agent 协程）
  gateway:           # FastAPI HTTP/SSE 网关
  trigger:           # 触发器调度进程（Phase 4）
  sandbox:           # 代码执行沙箱（隔离，Phase 2）
  chromadb:          # 向量数据库（Phase 2）
  voice:             # 语音处理进程 STT/TTS（Phase 3）
```

### 最小启动配置

```env
ANTHROPIC_API_KEY=...
SEBASTIAN_OWNER_NAME=...
SEBASTIAN_DATA_DIR=./data
SEBASTIAN_SANDBOX_ENABLED=true
SEBASTIAN_FCM_KEY=...         # Mobile 推送（Phase 3）
```

---

## 11. 与 OpenJax 的关系

OpenJax 是前驱技术探索，已验证：

- Agent loop 的基本模式（turn → tool → result）
- Streaming 事件归一化设计（SSE + 语义事件）
- Transcript-first 事件持久化模型（append-then-publish）
- Policy/审批机制的架构位置
- Gateway + Core 分层的合理性

Sebastian 继承这些**设计经验**，不继承代码。重要改进点：

| OpenJax | Sebastian |
|---------|-----------|
| Session 为核心（仅对话） | Session 一等公民（含 Task 子集）+ 垂直管理体系 |
| 对话驱动，同步执行 | 非阻塞对话 + 异步 Task 持久执行（内部双路径） |
| 手动注册工具 | 目录扫描自动注册（tools/mcps/skills 三层） |
| 无 Sub-Agent | A2A 多 Agent 编排，城堡垂直管理体系 |
| 无记忆系统 | 三层 Memory（工作/情景/语义） |
| 无主动触发 | Trigger Engine（cron/事件/条件） |
| Web UI 为主 | Mobile（Android）为主，SubAgent 督导面板 |
| 数据库存储 | 文件系统存储（可读可调试，未来可迁移至数据库） |
| 无生物识别 | 声纹 + 人脸 + 抗仿冒（Phase 5） |
| Rust | Python 3.12+ |

---

## 12. 已确认事项

- [x] Sub-Agent 进程模型：Phase 1-2 同进程协程，A2A 接口设计保持标准，后续可迁独立进程
- [x] 向量数据库：ChromaDB（轻量本地，个人规模足够）
- [x] 声纹/人脸：推迟到 Phase 5，Phase 1-4 用密码/Token
- [x] 初始仓库：不公开
- [x] 主要交互入口：Android App 优先，iOS 跟进
- [x] ~~A2A 协议：采用 Google A2A 开放规范，同进程内存队列实现~~ → **已废弃**，改为直接调用 + event bus，见[三层架构 spec](2026-04-06-three-tier-agent-architecture-design.md)
- [x] 流式输出通道：独立 SSE 通道，POST /turns 立即返回，token 走 SSE
- [x] AgentLoop 设计：async generator（yield LLMStreamEvent），不持有 EventBus
- [x] 打断机制：cancel stream + keep partial + 以新 context 重新请求（无 fork/ghost）
- [x] SSE 事件粒度：block 级（block_id 唯一标识每张卡片），解决多段 thinking 流写入同一卡片问题
- [x] ~~AgentPool：每个 agent_type 固定 3 个持久 worker，超限排队，worker 有具名身份~~ → **已废弃**，改为单例 agent + per-session 并发，见[三层架构 spec](2026-04-06-three-tier-agent-architecture-design.md)
- [x] ~~Session 模型：agent 字段拆分为 agent_type + agent_id~~ → **已更新**，移除 agent_id，新增 depth/parent_session_id/last_activity_at，见[三层架构 spec](2026-04-06-three-tier-agent-architecture-design.md)

---

## 13. 分期实施计划

### Phase 1 — 核心引擎 ✅ 已完成

目标：能对话、能执行工具、Session 文件持久化、Android App 可以连上

**已完成：**
- BaseAgent + AgentLoop（streaming async generator，yield LLMStreamEvent，分发表 publish）
- AgentPool：每个 agent_type 3 个持久 worker，acquire/release/排队
- Task 状态机：`_transition()` 统一状态变更 + 合法性校验
- Session 模型：`agent_type + agent_id` 双字段
- EventType：block 级事件（thinking_block.*、text_block.*、tool_block.*、turn.interrupted）
- Sebastian 主管家（非阻塞对话路径 + 异步任务路径 + Event Bus）
- Capability Bus：`capabilities/tools/` + `capabilities/mcps/` 扫描注册，基础工具
- SessionStore 文件存储（meta.json + messages.jsonl + tasks/，index.json 索引）
- Gateway：FastAPI + SSE + JWT 认证，路由完整，SSEManager（event id + 500 条缓冲 + 断线重放）
- Android App：Chat 页、SubAgents 页、SSE 接收，与 Gateway 联调可用

### Phase 2a — 完整链路（Multi-Agent 基础 + LLM Provider 管理）

目标：跑通一条完整链路——Sebastian 能委派 Sub-Agent 执行任务，App 能全程跟踪；LLM provider 可配置可切换

- **LLM Provider 管理**：`sebastian/llm/` 抽象层，DB 持久化 provider 配置，AgentLoop 依赖注入，支持 Anthropic / OpenAI 两种格式，per-agent 模型选择（manifest.toml 声明）
- **A2A 协议实现**（同进程内存队列）：Sebastian → Sub-Agent 委派、Sub-Agent → Sebastian 结果上报与 Escalate
- **Sub-Agent 自动注册机制**：`agents/` 目录扫描 + `manifest.toml` 解析，启动自动注册，A2A 立即可达
- **`capabilities/skills/` 扫描注册**：与 tools/mcps 扫描机制对齐
- **Android App 后端对接**：
  - SubAgents 页完整接入 A2A 任务流（委派、进度、结果）
  - Session 详情页：消息流 + Task 进度 + block 级渲染（thinking/tool 折叠卡）
  - ApprovalModal 接入审批流程
  - Settings 页：LLM Provider 管理（增删改、设为默认）

### Phase 2b — 记忆系统 + 高级 Agent 能力

目标：Sebastian 有记忆，CodeAgent 能自己写工具

- Memory System：工作记忆 + 情景记忆（SQLite）+ ChromaDB 语义记忆
- Code Agent（沙箱执行 + Dynamic Tool Factory）
- StockAgent 基础版
- Android App：Agent 专属记忆展示

### Phase 3 — 语音 + 移动体验提升

目标：能语音交互，iOS 上线，Mobile 功能完善

- Voice Pipeline：faster-whisper STT + TTS
- Android App：语音输入 + 快捷指令
- iOS App 上线（基于 React Native 共享代码）
- APNs 推送（iOS）
- LifeAgent（日历、智能家居基础集成）
- Trigger Engine：APScheduler cron/interval，触发器配置文件自动加载

### Phase 4 — 触发器进阶 + 更多 Sub-Agent

目标：Sebastian 主动出击，能力边界大幅扩展

- 事件触发 + 条件触发（if X then task Y）
- StockAgent 完整版（技术分析、回测）
- 更多 Sub-Agent（Research、Travel 等）
- Web UI 管理界面完善（Agent 状态、触发器配置、工具注册管理）
- 性能优化：Task 并发治理、LLM 调用限速

### Phase 5 — 身份与生物识别

目标：真正的多用户安全隔离，抗 AI 仿冒

- 声纹识别（resemblyzer）+ 活体检测
- 人脸识别（DeepFace）+ 随机挑战
- 多因素权限体系：Owner/Family/Guest 全链路
- 异常行为自动降权
- 审计日志完善

---

*本文档 v0.5，基于 v0.4 修订：Phase 1 标记为已完成；Phase 2 拆分为 2a（A2A + Sub-Agent 注册 + LLM Provider 管理 + App 对接）和 2b（记忆系统 + CodeAgent）；新增 LLM Provider 管理子系统（SQLite 持久化、多 provider 切换、per-agent 模型选择、AgentLoop 依赖注入抽象）；目录结构新增 `sebastian/llm/`；数据模型新增 `LLMProviderRecord`；App Settings 页补充 LLM provider 管理。*
