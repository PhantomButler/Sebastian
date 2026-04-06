# Sebastian 的 AGENTS 指南
本指南面向本仓库中的自治编码代理。
请使用可复现命令，遵循现有模式，并验证改动。

## 项目概述

Sebastian 是一个目标驱动的个人全能 AI 管家系统，灵感来自黑执事的塞巴斯蒂安与 Overlord 的 Sebas Tian，对标钢铁侠贾维斯愿景。
核心定位：个人主用 + 受控多用户（家人/访客），自托管部署，Android App 为主要交互入口。

**架构 Spec**：`docs/superpowers/specs/2026-04-01-sebastian-architecture-design.md`
开始工作前必读，包含完整架构决策（双平面、Task 一等公民、BaseAgent 继承、A2A 协议、三层能力目录等）。

**关系说明**：OpenJax（`/Users/ericw/work/code/ai/openJax`）是前驱技术探索，Sebastian 继承其设计经验，不继承代码。

**目录 README 索引**：
- `sebastian/README.md`：后端主包结构、模块职责、常见开发入口
- `ui/mobile/README.md`：移动端目录结构、页面导航、前端模块说明

## 1) 项目概览

- 主语言：Python 3.12+
- 包名：`sebastian`
- 主要交互入口：Android App（React Native），其次 iOS，辅以 Web UI

## 2) 关键路径

- `sebastian/core/` — BaseAgent 引擎（agent_loop、task_manager、planner、checkpoint）
- `sebastian/orchestrator/` — 主管家（conversation 对话平面、agent_router、goal_decomposer）
- `sebastian/agents/` — Sub-Agent 插件目录（manifest.toml 驱动自动注册）
- `sebastian/capabilities/tools/` — 通用基础工具（所有 Agent 可用，启动自动扫描）
- `sebastian/capabilities/mcps/` — MCP Server 集成（config.toml 驱动）
- `sebastian/capabilities/skills/` — Skill 复合能力（manifest.toml 驱动）
- `sebastian/protocol/` — A2A 协议 + Event Bus
- `sebastian/gateway/` — FastAPI HTTP/SSE 网关（REST API + 事件流）
- `sebastian/store/` — SQLite 持久化（Task、事件日志、SQLAlchemy async）
- `sebastian/memory/` — 三层记忆（working/episodic/semantic）
- `sebastian/identity/` — 身份与权限（Phase 5，当前仅 JWT）
- `sebastian/trigger/` — 主动触发引擎（Phase 4）
- `sebastian/sandbox/` — 代码执行沙箱（Docker 隔离）
- `ui/mobile/` — React Native App（Android 优先）
- `ui/web/` — React Web UI（辅助管理）

### 模块 README 导航

在针对某模块工作前，优先读对应 README（若存在）以快速获取上下文，避免全量搜索引入无关内容：
- `sebastian/README.md`
- `ui/mobile/README.md`
- `sebastian/core/README.md`
- `sebastian/llm/README.md`
- `sebastian/gateway/README.md`
- `sebastian/store/README.md`
- `sebastian/protocol/README.md`
- `sebastian/capabilities/README.md`
- `sebastian/agents/README.md`
- `sebastian/orchestrator/README.md`

## 3) 构建与启动

```bash
# 安装依赖（开发模式）
pip install -e ".[dev,memory]"

# 本地启动（gateway）
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload

# Docker 一键启动
docker compose up

# 本地预览统一用 127.0.0.1 而非 localhost
# Gateway: http://127.0.0.1:8000
```

## 3.1) Android App 开发（macOS）

### 前置条件

- Android Studio 已安装，SDK 路径：`~/Library/Android/sdk`
- AVD 已创建（推荐 `Medium_Phone_API_36.1`）
- Node.js 已安装

### 初次安装依赖

```bash
cd ui/mobile
npm install --legacy-peer-deps   # react-query-devtools 有 peer conflict，必须加此 flag
```

> **注意**：`@tanstack/react-query-devtools` 是 Web-only 包，**不能** import 进 React Native 代码，否则 crash。

### 启动 Android 模拟器

```bash
# 列出可用 AVD
~/Library/Android/sdk/emulator/emulator -list-avds

# 启动（-no-snapshot-load 跳过快照，避免状态污染）
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -no-snapshot-load &

# 等待启动完成（返回 "1" 即 ready）
~/Library/Android/sdk/platform-tools/adb wait-for-device shell getprop sys.boot_completed

# 确认设备在线
~/Library/Android/sdk/platform-tools/adb devices
```

### 首次构建并安装 APK

```bash
cd ui/mobile

# 配置 Android SDK 路径（仅首次，不提交）
echo "sdk.dir=$HOME/Library/Android/sdk" > android/local.properties

# 构建 + 安装到已连接设备
npx expo run:android
```

### 日常开发（APK 已装，只改 JS）

```bash
cd ui/mobile
npx expo start          # 启动 Metro，App 内自动热更新
```

> Expo Router 默认路由：`app/index.tsx` 用 `<Redirect>` 控制落地页，**不要**在 `_layout.tsx` 用 `initialRouteName`（此版本不支持）。

> **Metro 热更新注意**：热更新依赖 app 连上 Metro；不确定改动是否生效时，用 `npx expo run:android` 重新 build 更可靠。

> **React Native SSE**：RN 原生 `fetch` streaming 不支持 SSE 长连接，需用 `react-native-sse` 包实现 EventSource。

> **Anthropic SDK 0.87+**：`AsyncMessageStream.current_message` 已改名为 `current_message_snapshot`。

### 启动 Gateway 供 App 联调

```bash
# 根目录执行，确保 .env 已配置
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload

# App 内 Settings 页填写 Server URL：http://10.0.2.2:8000（模拟器访问宿主机）
# 真机用局域网 IP：http://192.168.x.x:8000
```

> 模拟器内访问宿主机 localhost 需用 `10.0.2.2`，不是 `127.0.0.1`。

### 生成测试用密码 Hash

```bash
python3 -c "from sebastian.gateway.auth import hash_password; print(hash_password('你的密码'))"
# 将输出写入 .env：SEBASTIAN_OWNER_PASSWORD_HASH=<输出值>
```

### .env 最小配置（本地开发）

```bash
ANTHROPIC_API_KEY=sk-ant-...
SEBASTIAN_OWNER_NAME=Eric
# SEBASTIAN_DATA_DIR 默认 ~/.sebastian，本地开发通常无需设置
SEBASTIAN_JWT_SECRET=local-dev-secret
SEBASTIAN_OWNER_PASSWORD_HASH=<用上面命令生成>
SEBASTIAN_GATEWAY_HOST=127.0.0.1
SEBASTIAN_GATEWAY_PORT=8000
```

## 4) Lint 与格式化

```bash
ruff check sebastian/ tests/
ruff format sebastian/ tests/
mypy sebastian/
```

## 5) 测试命令

```bash
# 全量
pytest

# 单模块
pytest tests/unit/test_base_agent.py
pytest tests/integration/test_gateway.py

# 带输出
pytest -s -v tests/unit/test_task_store.py
```

## 6) 运行时环境变量

```bash
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...                  # 可选，多模型支持

SEBASTIAN_OWNER_NAME=...
SEBASTIAN_DATA_DIR=./data
SEBASTIAN_SANDBOX_ENABLED=true
SEBASTIAN_GATEWAY_HOST=0.0.0.0
SEBASTIAN_GATEWAY_PORT=8000
SEBASTIAN_JWT_SECRET=...

# Phase 3（语音）
# SEBASTIAN_FCM_KEY=...
```

## 7) Python 代码风格

- Python 版本：3.12+，使用 `from __future__ import annotations`
- 4 空格缩进，PEP 8 命名
- 命名：
  - 函数/模块/变量：`snake_case`
  - 类/类型：`PascalCase`
  - 常量：`SCREAMING_SNAKE_CASE`
- 所有公共函数和内部函数均需类型注解（含 `-> None`）
- 使用 `str | None` 联合类型语法（不用 `Optional`）
- 对可能失败的操作优先抛出具体异常（`SebastianError` 子类），不静默吞掉非清理类错误
- `contextlib.suppress(...)` 仅用于清理/关闭路径

## 8) 导入顺序

1. `from __future__ import annotations`
2. 标准库
3. 第三方包（fastapi、pydantic、sqlalchemy 等）
4. 本地包（`from sebastian.xxx import ...`）

## 9) 模块化原则

- 单文件推荐 500 行以下，不超过 800 行；超出时提醒用户规划拆分
- 每个模块职责单一，通过明确接口通信
- 新增工具：放 `capabilities/tools/<name>.py`，加 `@tool` 装饰器，重启自动注册
- 新增 MCP：在 `capabilities/mcps/<name>/` 创建 `config.toml`，重启自动连接
- 新增 Sub-Agent：在 `agents/<name>/` 创建 `manifest.toml`，重启自动注册
- 不改核心代码来扩展能力

## 10) 测试期望

- 任何行为变更都应包含测试新增/更新
- 测试模式：
  - 单元测试：`tests/unit/test_*.py`，使用 `pytest` + `pytest-asyncio`
  - 集成测试：`tests/integration/test_*.py`，可访问真实 SQLite（不 mock 数据库）
  - e2e：`tests/e2e/`，覆盖完整请求链路
- 方法名描述单一行为，覆盖 happy path 和失败/边界场景

## 项目级工作规则

### 第一性原理
请使用第一性原理思考。从原始需求和问题本质出发，不从管理或模板出发。
- 不要假设我行出自己想要什么，动机或目标不清晰时，停下来讨论。
- 目标清晰但路径不是最短的，直接告诉我并建议更好的办法。
- 遇到问题追根溯源，不打补丁。每个决策都要能回答“为什么“。
- 输出说重点，减少一切不改变决策的信息。

### 方案规范
当需要你给出修改或重构方案时必须符合以下规范：

- 不允许给出兼容性或补丁性的方案
- 不允许过度设计，保持最短路径实现且不能违反第一条要求
- 不允许自行给出我提供的需求以外的方案，例如一些兜底和降级方案，这可能导致业务逻辑偏移问题
- 必须确保方案的逻辑正确，必须经过全链路的逻辑验证

### 其他
- (重要)在处理 python 项目文件时，优先使用 JetBrains pycharm MCP 进行符号、引用、实现、类型层级和文本索引查询；不要先使用 `rg`、`grep`、`find` 等本地搜索。只有在确认当前会话无法使用该 MCP，或其能力不足以完成当前任务时，才允许退回本地搜索；退回前必须明确说明失败点属于“未配置 / 未连接 / 当前 agent 无工具暴露 / 其他”中的哪一类。
- (重要)在分派subagent 任务时记得告知subagent 也可以使用JetBrains pycharm MCP
- 尽量使用 Read/Edit/Write 等内置工具编辑文件，非必要不使用 echo/cat heredoc/sed 等 shell命令写文件，除非系统内置工具一直出问题得不到解决
- 在修改过程中如果发现某个文件内容过多，记得提醒用户规划拆分计划
- 在针对某部分做修改时优先根据 README 了解对应模块上下文
- （重要）探索查询或修改任何功能模块前，必须先读对应的 README：
  - 从根目录 `INDEX.md` 开始，沿树状链接向下定位目标模块
  - 每个模块 README 包含「修改导航」表，直接指向需要修改的文件
  - 如果修改了某目录的内容，同步更新该目录的 README（以及受影响的上级 README）
  - README 索引树：根 `INDEX.md` → `sebastian/README.md` → 各子模块 README
- 写代码过程中尽量遵循模块化可扩展原则，推荐 500 行以下，不超过 800 行
- 不要随意拉新分支，需要拉新分支时提前说明

## 11) 代码提交与 PR 工作流

### 提交前准备（同步 main）
1. 确认当前分支不是 `main`
2. `git fetch origin main` 拉取最新 main
3. 若有未提交改动先 `git stash`，完成 rebase 后 `git stash pop`
4. `git rebase origin/main`，有冲突手动解决后继续

### 提交规范
- 用 `git add <具体文件>` 逐一添加，**禁止** `git add .` 或 `git add -A`
- commit message 格式：`类型(范围): 中文摘要`
  - 类型：`feat` / `fix` / `docs` / `refactor` / `chore` / `test`
  - 可在类型前加 emoji（参考现有历史记录风格）
- message 末尾附：`Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`
- 保持改动原子化，一个 commit 只做一件事

### 推送与 PR
- push 使用 `-u` 绑定远程：`git push -u origin <branch>`
- 用 `gh pr create` 创建 PR，base branch 统一指向 `main`
- PR title 与 commit message 风格一致，控制在 70 字以内
- PR body 必须包含两部分：
  - **Summary**：改了什么、为什么改（1-3 条要点）
  - **Test plan**：验证步骤 checklist
- 可直接调用 `/commit-pr` skill 自动完成上述全流程

## 12) 安全规范

- 绝不硬编码密钥，通过环境变量注入（参考 `.env.example`）
- 沙箱执行（Dynamic Tool Factory 生成的代码）必须走 `sebastian/sandbox/executor.py`，不允许直接 `exec()`
- 高危操作（文件删除、网络请求、系统命令）需要 Approval 机制
