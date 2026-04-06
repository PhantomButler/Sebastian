# code

> 上级索引：[agents/](../README.md)

## 目录职责

Code Agent 是负责编程任务的 Sub-Agent，能够编写、运行和调试 Python 及 Shell 脚本。由 `manifest.toml` 驱动自动注册，支持 3 个并发 Worker 处理任务。

## 目录结构

```
code/
├── __init__.py           # 包入口（空）
├── manifest.toml         # Agent 声明（名称、worker 数、允许工具列表）
├── tools/
│   └── __init__.py       # Agent 专属工具包（当前为空，预留扩展位）
└── knowledge/
    └── engineering_guidelines.md  # 注入给 Agent 的工程规范知识
```

## manifest.toml 说明

```toml
[agent]
name         = "Code Agent"
description  = "Executes code tasks: writes, runs, and debugs Python and shell scripts"
worker_count = 3
class_name   = "CodeAgent"
allowed_tools  = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
allowed_skills = []
```

- `worker_count`：并发处理任务的 Worker 数量
- `allowed_tools`：Agent 可调用的基础工具白名单
- `class_name`：对应 `sebastian/core/` 中实际的 Agent 类名

## knowledge/ 目录

`engineering_guidelines.md` 会在 Agent 初始化时注入到系统提示，作为 Code Agent 的工程约束和行为准则参考。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| Agent 基本声明（名称、并发数、工具权限） | [manifest.toml](manifest.toml) |
| Agent 专属工具（扩展代码执行能力） | [tools/\_\_init\_\_.py](tools/__init__.py) |
| Agent 工程规范知识注入 | [knowledge/engineering_guidelines.md](knowledge/engineering_guidelines.md) |

---

> 修改本目录或模块后，请同步更新此 README。
