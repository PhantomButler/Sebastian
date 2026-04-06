# tools

> 上级索引：[orchestrator/](../README.md)

## 目录职责

Orchestrator 专属工具目录。这里存放仅供 Sebastian 主管家使用的 `@tool` 装饰器工具，与 `capabilities/tools/`（所有 Agent 通用工具）相对。当前仅有任务委派工具，用于将用户请求下发给具体 Sub-Agent 处理。

## 目录结构

```
tools/
├── __init__.py    # 空文件，包标识
└── delegate.py    # delegate_to_agent 工具：将任务委派给指定 Sub-Agent 并返回结果
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| `delegate_to_agent` 工具的委派逻辑、参数或描述 | [delegate.py](delegate.py) |
| 委派工具的权限等级（`PermissionTier`） | [delegate.py](delegate.py) |
| A2A 委派协议的调用方式（`DelegateTask` / `A2ADispatcher`） | [delegate.py](delegate.py) |

---

> 修改本目录或模块后，请同步更新此 README。
