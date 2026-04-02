# Sebastian Backend Guide

本 README 面向在 `sebastian/` 目录中工作的开发者与编码代理，帮助快速理解后端目录结构、模块职责与常见切入点。

## 目录定位

`sebastian/` 是整个 Sebastian 系统的 Python 后端主包，负责：

- Agent runtime 与任务执行
- 主管家 orchestration
- FastAPI gateway 与 SSE 实时推送
- Session / Task / Event 持久化
- Memory、Sandbox、Protocol 等基础能力

如果你刚进入仓库，建议先配合阅读：

- `docs/superpowers/specs/2026-04-01-sebastian-architecture-design.md`
- `docs/superpowers/specs/2026-04-01-android-app-design.md`
- `AGENTS.md`
- `CLAUDE.md`

## 顶层结构

```text
sebastian/
├── agents/         # Sub-Agent 插件目录
├── capabilities/   # tools / mcps / skills 能力注册与装载
├── config/         # 配置解析与运行时设置
├── core/           # BaseAgent、task loop、tool runtime 等核心引擎
├── gateway/        # FastAPI HTTP API、SSE、鉴权、路由
├── identity/       # 身份与权限（当前 Phase 较轻）
├── memory/         # working / episodic 等记忆层
├── orchestrator/   # Sebastian 主管家编排逻辑
├── protocol/       # A2A 协议与事件定义
├── sandbox/        # 代码执行隔离
├── store/          # Session / Task / Event 存储层
├── trigger/        # 主动触发引擎（后续 Phase）
├── main.py         # 启动入口
└── __init__.py
```

## 模块说明

### `core/`

系统运行时核心。这里定义了 Agent 的基础行为和任务执行骨架。

- `base_agent.py`：Agent 基类与通用生命周期
- `agent_loop.py`：主执行循环
- `task_manager.py`：Task 生命周期与调度协作
- `tool.py`：工具抽象与注册接口
- `types.py`：核心类型定义

适合在以下场景进入：

- 修复 Agent 行为问题
- 调整任务执行与中断逻辑
- 接入新的基础工具调用能力

### `orchestrator/`

Sebastian 主管家的编排层，负责把用户请求拆解成目标、任务与 Sub-Agent 协作。

- `sebas.py`：主管家的主入口
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

Sub-Agent 插件目录。当前已经有：

- `code/`
- `life/`
- `stock/`

这里通常放 agent manifest、agent 专属 prompt / 策略 / 扩展实现。

### `capabilities/`

能力注册层，负责把工具、MCP、Skill 装载进运行时。

- `tools/`：所有 Agent 可共享的基础工具
- `mcps/`：MCP server 集成
- `skills/`：复合能力定义
- `registry.py`：能力注册表
- `mcp_client.py`：MCP client 接入

适合在以下场景进入：

- 新增工具或 Skill
- 调整能力发现与注册机制
- 排查工具暴露范围与权限问题

### `memory/`

记忆层实现，目前以 working / episodic 为主。

- `working_memory.py`
- `episodic_memory.py`
- `store.py`

### `protocol/`

系统内部协议层，定义 agent 间事件与协议抽象。

- `a2a/`
- `events/`

### `sandbox/`

执行危险或动态代码时的隔离边界。涉及命令执行、安全限制和容器/沙箱策略时应优先查看这里。

### `config/`、`identity/`、`trigger/`

这几个目录当前体量较小，但分别承载：

- `config/`：运行配置
- `identity/`：身份与权限能力的预留位置
- `trigger/`：主动触发引擎的预留位置

## 常见开发入口

### 改后端 API

优先看：

- `sebastian/gateway/app.py`
- `sebastian/gateway/routes/`
- `sebastian/gateway/state.py`

### 改 Session / Task 持久化

优先看：

- `sebastian/store/session_store.py`
- `sebastian/store/index_store.py`
- `sebastian/store/task_store.py`
- `sebastian/store/models.py`

### 改 Sebastian / Sub-Agent 行为

优先看：

- `sebastian/orchestrator/sebas.py`
- `sebastian/core/base_agent.py`
- `sebastian/core/agent_loop.py`
- `sebastian/core/task_manager.py`

### 改工具 / MCP / Skill 接入

优先看：

- `sebastian/capabilities/registry.py`
- `sebastian/capabilities/tools/`
- `sebastian/capabilities/mcps/`
- `sebastian/capabilities/skills/`

## 与前端的接口边界

`sebastian/` 主要为 `ui/mobile/` 与未来的 `ui/web/` 提供：

- REST API
- SSE 事件流
- 认证与权限
- Session / Task / Approval 数据

如果你在排查联调问题，通常需要把本目录与 `ui/mobile/README.md` 一起看。

## 常用命令

```bash
# 启动 gateway
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload

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
