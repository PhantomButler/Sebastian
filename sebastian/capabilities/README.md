# capabilities — 工具与能力注册

> 上级索引：[sebastian/](../README.md)

## 模块职责

统一管理所有可用能力：Native Tools（`@tool` 装饰器注册）、MCP Server Tools（外部进程，stdio 协议）以及 Skill 复合能力。向 Agent 提供统一的 `CapabilityRegistry` 访问点，屏蔽底层工具来源差异。

## 目录结构

```
capabilities/
├── __init__.py          # 模块入口（空）
├── registry.py          # CapabilityRegistry：统一调用入口，get_all_tool_specs() / call()
├── mcp_client.py        # MCPClient：启动 MCP server 子进程（stdio），注入工具到 registry
├── tools/               # → [tools/README.md](tools/README.md)
│   ├── __init__.py
│   ├── _loader.py       # 启动时自动扫描 tools/ 目录，触发 @tool 自注册
│   ├── _file_state.py   # 文件读取状态追踪（Write/Edit 的前置保护）
│   ├── _path_utils.py   # 统一文件路径解析（相对路径 → workspace_dir）
│   ├── _session_lock.py # Session 级 asyncio.Lock，防止并发 turn 冲突
│   ├── _session_permission.py  # stop/resume 权限校验（depth 边界）
│   ├── ask_parent/      # 子代理主动暂停并向上级请求指示（状态置 WAITING）
│   ├── bash/            # Shell 命令执行工具
│   ├── browser/         # BrowserSessionManager + Sebastian 内置 browser_* 工具
│   ├── check_sub_agents/  # 查询当前 Sub-Agent 会话状态
│   ├── delegate_to_agent/ # Sebastian 委派任务给 Sub-Agent（工具调用形式）
│   ├── edit/            # 文件精准替换工具
│   ├── glob/            # 文件模式匹配工具
│   ├── grep/            # 文件内容搜索工具（优先 ripgrep）
│   ├── inspect_session/ # 查看指定 session 的最近消息与状态
│   ├── read/            # 文件读取工具
│   ├── resume_agent/    # 恢复 waiting/idle 子代理执行
│   ├── stop_agent/      # 暂停运行中的子代理到 idle（可恢复）
│   ├── spawn_sub_agent/ # Sebastian 创建新的 Sub-Agent session
│   ├── todo_read/       # Session 级 todo 列表只读查询工具
│   ├── todo_write/      # Session 级 todo 列表覆盖式写入工具
│   ├── send_file/       # Agent 向用户发送文件/图片工具
│   ├── screenshot_send/  # Sebastian 截图并发送工具（Sebastian-only）
│   └── write/           # 文件写入工具（含 mtime 保护）
├── mcps/                # MCP server 配置目录，每个子目录一个 config.toml，启动时自动连接
│   ├── __init__.py
│   └── _loader.py       # 扫描 mcps/ 子目录，自动连接各 MCP server
└── skills/              # Skill 复合能力目录（Phase 2+，当前占位）
    ├── __init__.py
    └── _loader.py       # Skill 自动加载（占位）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 Native 工具 | [tools/](tools/README.md) 下新建目录 + `@tool` 装饰器 |
| 修改 Sebastian 浏览器工具 | [tools/browser/](tools/browser/) 的注册入口、页面观察、下载、截图 artifact helper |
| 修改工具调用优先级/错误处理 | [registry.py](registry.py) 的 `call()` |
| 修改工具自动加载逻辑 | [tools/_loader.py](tools/_loader.py) |
| 新增 MCP Server 连接 | `mcps/<name>/config.toml`，重启自动连接 |
| 修改 MCP 连接方式 | [mcp_client.py](mcp_client.py) |
| 查看所有已注册工具 | 运行时调用 `registry.get_all_tool_specs()`，或搜索 `@tool` 装饰器 |

## 公开接口

```python
from sebastian.capabilities.registry import CapabilityRegistry

registry = CapabilityRegistry()

# 获取所有工具 spec（兼容入口，显式按 ALL_TOOLS 取全量工具）
tool_specs = registry.get_all_tool_specs()

# 调用工具
result = await registry.call("file_read", path="/foo/bar.txt")
# result.ok, result.output, result.error

# 按白名单获取工具；allowed_tools=None 表示不暴露能力工具，ALL_TOOLS 表示全量能力工具
tool_specs = registry.get_callable_specs(allowed_tools={"Read"}, allowed_skills=None)

# 注入 MCP 工具（由 app.py lifespan 调用）
await registry.register_mcp_tools(mcp_client)
```

## 扩展方式

**新增 Native Tool**（推荐）：
```python
# 在 capabilities/tools/<name>/__init__.py 中
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

@tool(
    name="my_tool",
    description="做什么事",
    permission_tier=PermissionTier.LOW,  # 必须显式指定，默认为 MODEL_DECIDES
)
async def my_tool(param: str) -> ToolResult:
    return ToolResult(ok=True, output="结果")
# 重启后自动注册，无需修改其他文件
```

> **注意**：`permission_tier` 必须显式指定，默认值为 `MODEL_DECIDES`（经过 reviewer 审查）。
> - `LOW`：只读查询、状态检查等无副作用操作
> - `MODEL_DECIDES`：有副作用但可审查的操作（文件写入、网络请求等）
> - `HIGH_RISK`：高危操作，始终请求用户确认

**新增 MCP Server**：在 `capabilities/mcps/<name>/` 下创建 `config.toml`，重启后自动连接。

## 子模块

- [tools/](tools/README.md) — Native 工具插件目录，`@tool` 装饰器驱动自注册
- [mcps/](mcps/README.md) — MCP Server 配置目录，`config.toml` 驱动自动连接
- [skills/](skills/README.md) — Skill 复合能力目录，`SKILL.md` 驱动自动加载

---

> 修改本目录或模块后，请同步更新此 README。
