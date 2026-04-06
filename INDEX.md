# Sebastian

> 指导文档：[CLAUDE.md](CLAUDE.md)

## 项目简介

Sebastian 是一个目标驱动的个人全能 AI 管家系统，灵感来自黑执事的塞巴斯蒂安与 Overlord 的 Sebas Tian，对标钢铁侠贾维斯愿景。自托管部署，Android App 为主要交互入口，支持受控多用户（家人/访客）。

## 仓库结构

```
sebastian/         — 后端 Python 包（核心引擎、网关、Agent 等）
ui/mobile/         — React Native 移动端 App（Android 优先）
ui/web/            — Web 管理界面（辅助）
tests/             — 测试套件（unit / integration / e2e）
docs/              — 架构文档与设计 Spec
```

## 快速索引

### 后端模块

| 模块 | 说明 |
|------|------|
| [sebastian/](sebastian/README.md) | 后端主包入口 |
| [core/](sebastian/core/README.md) | BaseAgent 引擎、任务执行循环 |
| [gateway/](sebastian/gateway/README.md) | FastAPI HTTP/SSE 网关 |
| [orchestrator/](sebastian/orchestrator/README.md) | 主管家对话平面与编排逻辑 |
| [agents/](sebastian/agents/README.md) | Sub-Agent 插件目录 |
| [capabilities/](sebastian/capabilities/README.md) | 工具 / MCP / Skill 能力层 |
| [protocol/](sebastian/protocol/README.md) | A2A 协议 + 事件总线 |
| [store/](sebastian/store/README.md) | SQLite 持久化层 |
| [llm/](sebastian/llm/README.md) | LLM 提供商适配层 |
| [memory/](sebastian/memory/README.md) | 三层记忆系统 |
| [config/](sebastian/config/README.md) | 全局配置解析 |
| [identity/](sebastian/identity/README.md) | 身份与权限（Phase 5） |
| [trigger/](sebastian/trigger/README.md) | 主动触发引擎（Phase 4） |
| [sandbox/](sebastian/sandbox/README.md) | 代码执行沙箱 |

### 前端 & 测试

| 目录 | 说明 |
|------|------|
| [ui/mobile/](ui/mobile/README.md) | React Native App（Android 优先） |
| [tests/](tests/README.md) | 测试套件（unit / integration / e2e） |

## 开发快速入门

```bash
# 安装后端依赖
pip install -e ".[dev,memory]"

# 启动后端网关
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload

# 启动 Android App（需先启动模拟器）
cd ui/mobile && npx expo start
```

> 详细开发指引（环境变量、Android 模拟器配置、测试命令等）见 [CLAUDE.md](CLAUDE.md)

---

> 修改本仓库结构后，请同步更新此 README。
