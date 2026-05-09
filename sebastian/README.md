# Sebastian Backend Guide

> 上级：[项目根](../INDEX.md) · [CLAUDE.md](../CLAUDE.md)

本 README 面向在 `sebastian/` 目录中工作的开发者与编码代理，帮助快速理解后端目录结构、模块职责与常见切入点。

## 目录定位

`sebastian/` 是整个 Sebastian 系统的 Python 后端主包，负责：

- Agent runtime 与任务执行
- 主管家 orchestration
- FastAPI gateway 与 SSE 实时推送
- Session / Task / Event 持久化
- Memory、Sandbox、Protocol 等基础能力
- `sebastian` CLI、自升级、服务化启动与 Skill 包管理

如果你刚进入仓库，建议先配合阅读：

- `docs/superpowers/specs/2026-04-01-sebastian-architecture-design.md`
- `docs/superpowers/specs/2026-04-01-android-app-design.md`
- `AGENTS.md`
- `CLAUDE.md`

## 顶层结构

```text
sebastian/
├── agents/         → agents/README.md
├── capabilities/   → capabilities/README.md
│   ├── tools/      → capabilities/tools/README.md
│   ├── mcps/       → capabilities/mcps/README.md
│   └── skills/     → capabilities/skills/README.md
├── cli/            → cli/README.md
├── config/         → config/README.md
├── context/        → context/README.md
├── core/           → core/README.md
├── gateway/        → gateway/README.md
│   └── routes/     → gateway/routes/README.md
├── identity/       → identity/README.md
├── llm/            → llm/README.md
├── log/            → log/README.md
├── memory/         → memory/README.md
├── orchestrator/   → orchestrator/README.md
├── permissions/    → permissions/README.md
├── protocol/       → protocol/README.md
│   ├── a2a/        → protocol/a2a/README.md
│   └── events/     → protocol/events/README.md
├── sandbox/        → sandbox/README.md
├── skills_registry/ # Skill package registry client、installer、本地 show、lockfile、安全解压
├── store/          → store/README.md
├── trigger/        → trigger/README.md
├── main.py         # 启动入口
└── __init__.py
```

## 模块说明

### `core/`

系统运行时核心。这里定义了 Agent 的基础行为和任务执行骨架。

- `base_agent.py`：Agent 基类与通用生命周期
- `agent_loop.py`：主执行循环
- `task_manager.py`：Task 生命周期与调度协作
- `session_runner.py`：Sub-Agent session 独立执行入口
- `stalled_watchdog.py`：检测僵死 session 并触发恢复的守护逻辑
- `tool.py`：工具抽象与注册接口
- `types.py`：核心类型定义

适合在以下场景进入：

- 修复 Agent 行为问题
- 调整任务执行与中断逻辑
- 接入新的基础工具调用能力

### `context/`

session 短期上下文的运行时压缩，包含 token usage 归一化、估算器、阈值判断、压缩 worker 与 prompt。详见 [context/README.md](context/README.md)。

- `usage.py`：`TokenUsage` 与 provider usage 归一化
- `estimator.py`：本地兜底 token 估算
- `token_meter.py`：阈值判断
- `compaction.py`：压缩 worker + turn 后调度器
- `prompts.py`：summary prompt

适合在以下场景进入：

- 调整压缩触发阈值或 retain 窗口
- 修改 summary prompt 结构
- 新增 provider usage 字段

### `orchestrator/`

Sebastian 主管家的编排层，负责把用户请求拆解成目标，并通过 `spawn_sub_agent` / `delegate_to_agent` 等工具调用实现三层 Agent 协作。

- `sebas.py`：主管家主入口，继承 `BaseAgent`，管理顶层对话
- `conversation.py`：对话平面与用户交互相关逻辑

适合在以下场景进入：

- 修改 Sebastian 如何委派 / 介入 / 升级任务
- 调整对话面与任务面的衔接逻辑

### `gateway/`

移动端 / Web 端访问后端的 HTTP 与 SSE 入口。

- `app.py`：FastAPI app 装配
- `routes/`：按资源拆分的 REST API 路由
- `auth.py`：登录与 JWT 逻辑
- `sse.py`：事件流输出协议
- `completion_notifier.py`：子代理完成事件触发父 Agent 新 turn
- `state.py`：gateway 运行时依赖装配

适合在以下场景进入：

- API 设计、请求/响应修复
- SSE 事件协议与前端联调
- 登录认证与路由权限调整

### `store/`

当前 Phase 1 的主要持久化层，负责 Session / Task / Event 的读写与索引。

- `session_store.py`：Session 文件化存储
- `index_store.py`：Session 索引
- `task_store.py`：Task 存储
- `event_log.py`：事件日志
- `database.py` / `models.py`：SQLite 与数据模型

适合在以下场景进入：

- 修复 Session / Task 数据一致性
- 调整落盘结构、原子写、迁移策略
- 追查事件日志与索引同步问题

### `agents/`

Sub-Agent 插件目录。当前已有：

- `forge/`

这里通常放 agent manifest（`manifest.toml`）、agent 专属 prompt / 策略 / 扩展实现。重启后自动注册。

### `capabilities/`

能力注册层，负责把工具、MCP 装载进运行时，并维护 Skill 本地 catalog。

- `tools/`：所有 Agent 可共享的基础工具
- `mcps/`：MCP server 集成
- `skills/`：本地 Skill catalog 与内置 Skill 定义
- `registry.py`：能力注册表
- `mcp_client.py`：MCP client 接入

用户安装的 Skill package 默认写入
`~/.sebastian/data/extensions/skills`。`sebastian skills search` 默认只搜本地，
本地查询按空白分词并 OR 匹配 slug、frontmatter name、registered name 和 description；
远端 registry 搜索需要显式 `--source registry` 或 `--source all`。remote
search/inspect/install 使用显式 `--registry` → `SEBASTIAN_SKILLS_REGISTRY_URL` →
默认 `https://clawhub.ai` 的顺序解析 registry；`update` 不传 `--registry` 时使用该
Skill 安装时记录在 lockfile 中的 registry，显式传入 `--registry` 则覆盖该记录。
install/update/remove 等变更命令在有效 registry 非默认值时会要求确认，包括使用已存储
registry 的 update。本地 Skill 内容以磁盘当前文件为准，通过
`sebastian skills show --body` 和 `sebastian skills read` 按需读取。
内置 `skill_manager` Skill 让 Sebastian 通过 CLI 列出和读取本地 Skill，并在用户确认后
搜索、检查、安装、更新或移除 registry Skill。

适合在以下场景进入：

- 新增工具或 Skill
- 调整能力发现、工具注册或 Skill catalog 机制
- 排查工具暴露范围与权限问题
- 调整 Skill 包安装生命周期或内置 `skill_manager` 说明

### `memory/`

长期记忆系统。外部调用通过 `contracts/` + `services/`，内部实现按 `stores/`、`writing/`、`retrieval/`、`consolidation/`、`resident/` 分包组织。详见 [memory/README.md](memory/README.md)。

### `protocol/`

系统内部协议层，定义 agent 间事件与协议抽象。

- `a2a/`：A2A 协议目录（dispatcher/types 已移除，Agent 间协作通过 `asyncio.create_task` + 工具调用实现）
- `events/`：进程内事件总线（EventBus / EventType）

### `skills_registry/`

Skill package manager 的实现包，供 `sebastian skills` CLI 调用。它只实现
ClawHub-compatible registry consumer，不提供 publish/sync。

- `client.py`：registry URL 解析、search/inspect/download URL 策略
- `installer.py`：install/update/remove 事务、冲突检查、origin metadata
- `lockfile.py`：`.sebastian-skills.lock.json` 读写、file lock、atomic write
- `safety.py`：zip 安全解压、大小限制、fingerprint
- `models.py`：registry、install、list 输出模型

适合在以下场景进入：

- 修改 Skill package registry 兼容字段或安全状态规则
- 修改安装、更新、移除事务
- 修改 lockfile/origin metadata 或 archive 安全策略

### `sandbox/`

执行危险或动态代码时的隔离边界。涉及命令执行、安全限制和容器/沙箱策略时应优先查看这里。

### `cli/`

Typer CLI 子命令与进程守护工具。

- `daemon.py`：PID 文件管理与进程存活检测
- `init_wizard.py`：无头初始化向导（`sebastian init --headless`）
- `main.py`：Typer CLI 入口；`serve/status/update/version` 顶层命令；挂载 `service` 子命令。
- `cli/service.py`：systemd/launchd 服务安装、状态、重启。
- `updater.py`：自升级逻辑（`sebastian update`），含 SHA256 校验、原子替换、失败回滚
- `skills.py`：`sebastian skills search/inspect/install/list/show/read/update/remove`，
  从本地 catalog 和 ClawHub-compatible registry 管理用户 Skill 包；本地 search 使用
  multi-token OR 匹配与确定性排序。
- `path_setup.py`：安装/升级时刷新 `~/.sebastian/bin/sebastian` shim，并按需写入
  zsh/bash PATH block。

适合在以下场景进入：

- 修改 CLI 命令或参数
- 修改自升级/回滚策略
- 修改守护进程管理逻辑
- 修改 Skill 包管理、registry override 或 CLI PATH 行为

### `log/`

三层旋转文件日志系统。

- `manager.py`：LogManager，管理 main.log（始终开启）、llm_stream.log、sse.log 三个 handler
- `schema.py`：LogState / LogConfigPatch Pydantic 模型

支持运行时通过 REST API 热切换 llm_stream 和 sse 日志。

### `permissions/`

三层权限审查与 workspace 边界强制执行。

- `types.py`：PermissionTier 枚举（LOW / MODEL_DECIDES / HIGH_RISK）、ToolCallContext、ReviewDecision
- `gate.py`：PolicyGate，权限执行代理，所有工具调用经过此 gate
- `reviewer.py`：PermissionReviewer，LLM 审查器，对 MODEL_DECIDES 工具做 proceed/escalate 决策

适合在以下场景进入：

- 修改工具权限审查流程
- 修改 workspace 边界规则
- 调整 LLM 审查 prompt 或安全策略

### `config/`、`identity/`、`trigger/`

这几个目录当前体量较小，但分别承载：

- `config/`：运行配置
- `identity/`：身份与权限能力的预留位置
- `trigger/`：主动触发引擎的预留位置

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 修改后端 API 路由或响应格式 | [gateway/README.md](gateway/README.md) → `routes/` |
| 修改 SSE 事件协议 | [gateway/README.md](gateway/README.md) → `sse.py` |
| 修改 Session / Task 持久化 | [store/README.md](store/README.md) |
| 修改 Sebastian 对话或编排逻辑 | [orchestrator/README.md](orchestrator/README.md) |
| 修改 Agent 基础行为或任务执行 | [core/README.md](core/README.md) |
| 新增基础工具（`@tool` 装饰器） | [capabilities/README.md](capabilities/README.md) → `tools/` |
| 新增 MCP 集成 | [capabilities/README.md](capabilities/README.md) → `mcps/` |
| 新增 Sub-Agent | [agents/README.md](agents/README.md) |
| 修改 LLM 提供商适配 | [llm/README.md](llm/README.md) |
| 修改上下文压缩阈值 / summary prompt | [context/README.md](context/README.md) |
| 修改日志系统或热切换 | [log/README.md](log/README.md) |
| 修改记忆系统 | [memory/README.md](memory/README.md) |
| 修改权限审查或 workspace 边界 | [permissions/README.md](permissions/README.md) |
| 修改 A2A 协议或事件总线 | [protocol/README.md](protocol/README.md) |
| 修改沙箱执行策略 | [sandbox/README.md](sandbox/README.md) |
| 修改 CLI Skill 包管理 | [cli/README.md](cli/README.md) → `skills.py` |
| 修改 Skill package registry/installer/lockfile | `skills_registry/` |
| 修改全局配置解析 | [config/README.md](config/README.md) |
| 修改 CLI 命令或自升级逻辑 | [cli/README.md](cli/README.md) |

## 与前端的接口边界

`sebastian/` 主要为 `ui/mobile/` 与未来的 `ui/web/` 提供：

- REST API
- SSE 事件流
- 认证与权限
- Session / Task / Approval 数据

如果你在排查联调问题，通常需要把本目录与 [ui/mobile/README.md](../ui/mobile/README.md) 一起看。

## 常用命令

```bash
# 启动 gateway（首次会进入 Web 初始化向导）
sebastian serve

# 开发态热重载（已初始化）
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8823 --reload

# 后端测试
pytest tests/ -q

# 代码检查
ruff check sebastian/ tests/
mypy sebastian/
```

## 维护约定

- 优先保持模块职责清晰，不在 `gateway/` 写业务编排，不在 `store/` 写 UI 逻辑
- 任何行为变化都应补测试
- 如果单文件逼近 500 行，应评估拆分
- 修改目录职责时，也请同步更新本 README、`AGENTS.md` 与相关 spec

---

> 修改模块结构后，请同步更新本 README 中的目录树与修改导航表。
