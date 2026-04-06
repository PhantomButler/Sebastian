# mcps

> 上级索引：[capabilities/](../README.md)

## 目录职责

管理 MCP（Model Context Protocol）Server 集成的动态加载与注册。启动时自动扫描本目录下各子目录的 `config.toml`，实例化 `MCPClient` 并将其暴露的工具注入到 `CapabilityRegistry`，**无需修改任何核心代码**即可扩展 MCP 工具。

## 目录结构

```
mcps/
├── __init__.py        # 包入口（空）
└── _loader.py         # 扫描 config.toml、创建 MCPClient、连接并注册工具
```

## 扩展机制

新增 MCP Server 只需在本目录下创建一个子目录并放入 `config.toml`，重启服务后自动生效：

```
mcps/
└── my_mcp_server/
    └── config.toml
```

`config.toml` 格式：

```toml
[mcp]
name    = "my-server"       # 工具命名空间（可选，默认取目录名）
command = ["npx", "-y", "my-mcp-package"]
env     = { MY_KEY = "value" }  # 注入给子进程的环境变量（可选）
```

加载流程：

1. `load_mcps()` — 扫描所有 `*/config.toml`，返回未连接的 `MCPClient` 列表
2. `connect_all(clients, registry)` — 并发连接，枚举工具列表，逐一调用 `registry.register_mcp_tool()`

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 MCP Server | 在本目录下创建 `<name>/config.toml`（无需改代码） |
| 扫描逻辑、config.toml 解析规则 | [_loader.py](_loader.py) — `load_mcps()` |
| 连接和工具注册行为 | [_loader.py](_loader.py) — `connect_all()` |

---

> 修改本目录或模块后，请同步更新此 README。
