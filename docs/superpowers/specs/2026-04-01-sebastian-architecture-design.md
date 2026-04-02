# Sebastian 架构设计文档

**版本**：v0.3
**日期**：2026-04-02
**状态**：待实施

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

### 2.4 三层协议栈

| 协议 | 用途 | 使用方 |
|------|------|--------|
| **MCP** | 工具接入（外部服务、资源） | 所有 Agent 作为 MCP Client |
| **A2A** | Agent 间通信（任务委派/上报/升级） | Sebastian ↔ Sub-Agent |
| **SSE / FCM** | 前端实时流 / Mobile 推送通知 | Gateway → 用户界面 |

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
| LLM 接入 | Anthropic SDK + OpenAI SDK | 多模型支持，可按 Agent 选不同模型 |
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

### manifest.toml 格式

```toml
[agent]
name = "StockAgent"
description = "金融市场分析与投资研究专家"
version = "0.1.0"

# 该 Agent 擅长处理的任务类型（用于 Agent Router 路由决策）
capabilities = [
  "stock_analysis",
  "market_research",
  "portfolio_review",
  "financial_news"
]

# 继承所有基础工具，并额外激活以下专属工具
[tools]
builtin = ["shell", "web_search", "file_read"]   # 来自 capabilities/tools/
domain  = ["market_data_api", "technical_indicators", "backtest_engine"]  # 来自 agents/stock/tools/

# 额外挂载的 MCP（在通用 MCP 之外）
[mcps]
extra = ["bloomberg_mcp"]  # 来自 capabilities/mcps/bloomberg_mcp/

# 专属知识库（在全局语义记忆之外附加）
[knowledge]
sources = ["knowledge/finance/", "agents/stock/knowledge/"]
index   = "chroma://stock_agent"

# 专属系统 Prompt（附加到 BaseAgent 默认 Prompt）
[prompt]
persona = """
你是 Sebastian 的金融分析顾问，专注于股票市场研究与投资分析。
你拥有扎实的技术分析和基本面分析能力，能够从多维度评估投资机会。
遇到超出金融领域的问题，优先上报 Sebastian 处理。
"""

# 权限配置
[permissions]
level = "owner_only"          # owner_only / family / guest
require_approval = ["execute_trade", "modify_portfolio"]

# 该 Agent 内部并发限制
[concurrency]
max_parallel_tasks = 3
max_llm_calls_per_minute = 20
```

### 新增 Sub-Agent 步骤

1. 在 `agents/` 目录下创建新目录，如 `agents/research/`
2. 创建 `manifest.toml`（最小配置即可运行）
3. 可选：创建 `agent.py` 覆盖特定 BaseAgent 行为
4. 可选：在 `agents/<name>/tools/` 下添加专属工具（`@tool` 装饰器）
5. 重启 Sebastian（或调用热加载 API），自动注册，A2A 立即可达

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

### Session 文件存储结构

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
└── subagents/
    ├── stock/
    │   └── 2026-04-02T11-00-00_def456/
    │       ├── meta.json
    │       ├── messages.jsonl
    │       └── tasks/
    └── life/
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

```python
class Session(BaseModel):
    id: str                        # 时间戳_短UUID
    agent: str                     # "sebastian" 或 subagent name
    title: str                     # 会话标题（首条消息自动生成）
    status: SessionStatus          # active / idle / archived
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

```python
# Jarvis → Sub-Agent
class DelegateTask(BaseModel):
    task_id: str
    goal: str
    context: dict          # 相关上下文（记忆片段、已有结果等）
    constraints: dict      # 时间限制、资源限额
    callback_url: str      # 结果回传地址（同进程时为内存队列 ID）

# Sub-Agent → Jarvis（遇阻时）
class EscalateRequest(BaseModel):
    task_id: str
    reason: str            # 为什么需要上报
    options: list[str]     # 建议的处理选项
    blocking: bool         # 是否阻塞等待回复

# Sub-Agent → Jarvis（完成时）
class TaskResult(BaseModel):
    task_id: str
    ok: bool
    output: dict
    artifacts: list[Artifact]          # 生成的文件、报告等
    new_tools_registered: list[str]    # Dynamic Tool Factory 新注册的工具
```

### 事件类型（Event Bus）

```
# Task 生命周期
task.created
task.planning_started / task.planning_failed
task.started / task.paused / task.resumed
task.completed / task.failed / task.cancelled

# Agent 协同
agent.delegated              # Sebastian 成功委派给 Sub-Agent
agent.delegated.failed       # 委派失败（Sub-Agent 不可用、容量满）
agent.escalated              # Sub-Agent 向 Sebastian 上报请求决策
agent.escalated.failed       # 上报失败（超时、无响应）
agent.result_received        # Sub-Agent 返回结果

# 用户交互
user.interrupted             # 用户打断当前对话/任务
user.intervened              # 用户直接向 SubAgent 发送纠偏指令（静默通知 Sebastian）
user.approval_requested      # 等待用户审批（敏感操作）
user.approval_granted        # 用户批准
user.approval_denied         # 用户拒绝

# 工具生命周期
tool.registered              # 工具注册成功（含 Dynamic Tool）
tool.registered.failed       # 工具注册失败（代码错误、沙箱验证失败）
tool.running                 # 工具开始执行（长耗时工具可用于进度跟踪）
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
| 设置页面 | 服务器地址、API Key、通知偏好、Agent 状态 |

### SubAgent 督导模型

SubAgent 页面**没有"新建对话"按钮**——SubAgent 的 Session 由 Sebastian 委派创建，不由用户直接发起。

用户在 SubAgent Session 里发消息时走**直接纠偏通道**：消息直达该 SubAgent 的当前 Session，不经 Sebastian 路由；同时触发 `user.intervened` 事件静默通知 Sebastian，令其感知全局状态而不打断当前工作。

```
用户在 StockAgent Session 里："方向偏了，重点看港股"
    │
    ├── 消息直接注入 StockAgent 当前 Session  ← 立即生效
    └── 事件 user.intervened → Sebastian     ← 静默感知，不插话
```

### 移动端与服务端数据协议

**连接方式**：

| 场景 | 协议 |
|------|------|
| App 在前台 | SSE 长连接（`GET /api/v1/stream`） |
| App 在后台/熄屏 | FCM（Android）/ APNs（iOS）推送通知 |
| 数据读取/操作 | REST（JSON over HTTPS） |

**REST API（Gateway 暴露）**：

```
# 会话（Session）
GET    /api/v1/sessions                       # 全局 Session 索引（来自 index.json）
GET    /api/v1/sessions/{id}                  # Session 详情（meta + messages）
POST   /api/v1/sessions/{id}/turns            # 向指定 Session 发送消息（含纠偏指令）
GET    /api/v1/sessions/{id}/tasks            # Session 下的 Task 列表
GET    /api/v1/agents/{agent}/sessions        # 指定 Agent 的 Session 列表

# 对话（Sebastian 主入口，语法糖封装）
POST   /api/v1/turns                          # 向 Sebastian 当前/新 Session 发送消息

# 任务管理
GET    /api/v1/sessions/{id}/tasks/{task_id}  # Task 详情
POST   /api/v1/sessions/{id}/tasks/{task_id}/pause   # 暂停任务
POST   /api/v1/sessions/{id}/tasks/{task_id}/resume  # 恢复任务
DELETE /api/v1/sessions/{id}/tasks/{task_id}         # 取消任务

# 审批
GET    /api/v1/approvals                # 待审批列表
POST   /api/v1/approvals/{id}/grant     # 批准
POST   /api/v1/approvals/{id}/deny      # 拒绝

# 事件流（SSE）
GET    /api/v1/stream                         # 全局实时事件流
GET    /api/v1/sessions/{id}/stream           # 单 Session 事件流

# 语音（Phase 3）
POST   /api/v1/voice/transcribe         # 上传音频 → 文字

# 系统
GET    /api/v1/agents                   # 已注册 Agent 列表与状态
GET    /api/v1/health                   # 健康检查
```

**SSE 事件格式**：

```json
{
  "event": "task.started",
  "data": {
    "task_id": "abc123",
    "goal": "研究近两天的股票行情",
    "assigned_agent": "StockAgent",
    "ts": "2026-04-01T10:00:00Z"
  }
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
- [x] A2A 协议：采用 Google A2A 开放规范，同进程内存队列实现

---

## 13. 分期实施计划

### Phase 1 — 核心引擎（独立仓库起步）

目标：能对话、能执行工具、任务持久化、Android App 可以连上

- BaseAgent + Agent Loop（asyncio）
- Sebastian 主管家（对话平面 + 任务平面 + Event Bus）
- Capability Bus：`capabilities/tools/` 扫描注册，基础工具（shell、file、web_search）
- MCP Client 基础实现，`capabilities/mcps/` 扫描加载
- Task Store（SQLite + SQLAlchemy + 检查点）
- Gateway（FastAPI + SSE + REST API）
- JWT 认证（Owner 密码登录）
- Android App（对话界面 + 任务列表 + SSE 接收 + FCM 推送）
- Docker Compose 单机部署

### Phase 2 — Multi-Agent + 记忆系统

目标：Sebastian 能委派任务给 Sub-Agent，有记忆，能自己写工具

- A2A 协议实现（同进程内存队列）
- Sub-Agent 自动注册机制（`agents/` 目录 + manifest.toml 扫描）
- Code Agent（沙箱执行 + Dynamic Tool Factory）
- Memory System：工作记忆 + 情景记忆 + ChromaDB 语义记忆
- `capabilities/skills/` 扫描注册
- StockAgent 基础版
- Android App：任务详情 + 审批操作

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

*本文档 v0.3，基于 v0.2 修订：Session 升为一等公民，引入城堡管理体系（垂直树）作为主叙事框架，双平面降级为内部实现细节，存储改为文件系统，新增 SubAgent 督导模型。*
