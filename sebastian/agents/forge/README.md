# forge

> 上级索引：[agents/](../README.md)

## 目录职责

Forge Agent 是负责编程任务的 Sub-Agent，能够编写、运行和调试 Python 及 Shell 脚本。由 `manifest.toml` 驱动自动注册，可由 Sebastian 通过 `delegate_to_agent` 工具委派任务，亦可通过 `spawn_sub_agent` 分派最多 5 个并发子任务（depth=3）。

目录名 `forge` 即 `agent_type`，是系统内唯一标识；UI 展示时由前端做 capitalize（`forge` → `Forge`），manifest 不再有独立的 display_name 字段。

## 目录结构

```
forge/
├── __init__.py           # 包入口，ForgeAgent 类定义
├── manifest.toml         # Agent 声明（class_name、worker 数、允许工具列表）
├── tools/
│   └── __init__.py       # Agent 专属工具包（当前为空，预留扩展位）
└── knowledge/
    └── engineering_guidelines.md  # 注入给 Agent 的工程规范知识
```

## manifest.toml 说明

```toml
[agent]
class_name                = "ForgeAgent"                   # 必须精确匹配 __init__.py 中类名
description               = "编写代码、调试问题、构建工具"
max_children              = 5                              # 最大并发 depth=3 子任务数
stalled_threshold_minutes = 5                              # 多少分钟无活动判定为 stalled
allowed_tools             = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "todo_read", "send_file"]
allowed_skills            = []
```

- `max_children`：允许同时运行的 depth=3 子任务上限
- `stalled_threshold_minutes`：超过此时长无 tool 调用则被 watchdog 标记为 stalled
- `allowed_tools`：Agent 可调用的基础工具白名单；不写则仅自动注入协议工具，若需全量工具必须显式写 `"ALL"`
- `class_name`：对应 `__init__.py` 中实际的 Agent 类名

## knowledge/ 目录

`engineering_guidelines.md` 会在 Agent 初始化时注入到系统提示，作为 Forge Agent 的工程约束和行为准则参考。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| Agent 基本声明（名称、子任务上限、工具权限） | [manifest.toml](manifest.toml) |
| Agent 专属工具（扩展代码执行能力） | [tools/\_\_init\_\_.py](tools/__init__.py) |
| Agent 工程规范知识注入 | [knowledge/engineering_guidelines.md](knowledge/engineering_guidelines.md) |

---

> 修改本目录或模块后，请同步更新此 README。
