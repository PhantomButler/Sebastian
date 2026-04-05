# capabilities — 工具与能力注册

## 职责

统一管理所有可用能力：Native Tools（`@tool` 装饰器注册）、MCP Server Tools（外部进程，stdio 协议）。向 Agent 提供统一的 `CapabilityRegistry` 访问点。

## 关键文件

| 文件 | 职责 |
|---|---|
| `registry.py` | `CapabilityRegistry`：统一调用入口，`get_all_tool_specs()` 返回所有工具的 Anthropic API 格式 spec，`call(tool_name, **kwargs)` 执行工具（native 优先于 MCP） |
| `tools/_loader.py` | 启动时自动扫描 `tools/` 目录，import 所有非下划线 `.py` 文件，触发 `@tool` 自注册 |
| `tools/file_ops.py` | 文件操作工具（读/写/列目录等） |
| `tools/shell.py` | Shell 命令执行工具 |
| `tools/web_search.py` | Web 搜索工具 |
| `mcp_client.py` | `MCPClient`：启动 MCP server 子进程（stdio），初始化 session，将其工具注入 registry |
| `mcps/` | MCP server 配置目录，每个子目录一个 `config.toml`，启动时自动连接 |
| `skills/` | Skill 复合能力目录（Phase 2+，当前占位） |

## 公开接口（其他模块如何使用）

```python
from sebastian.capabilities.registry import CapabilityRegistry

registry = CapabilityRegistry()

# 获取所有工具 spec（直接传给 Anthropic API）
tool_specs = registry.get_all_tool_specs()

# 调用工具
result = await registry.call("file_read", path="/foo/bar.txt")
# result.ok, result.output, result.error

# 注入 MCP 工具（由 app.py lifespan 调用）
await registry.register_mcp_tools(mcp_client)
```

## 扩展方式

**新增 Native Tool**（推荐）：
```python
# 在 capabilities/tools/ 下新建文件
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult

@tool(description="做什么事")
async def my_tool(param: str) -> ToolResult:
    return ToolResult(ok=True, output="结果")
# 重启后自动注册，无需修改其他文件
```

**新增 MCP Server**：在 `capabilities/mcps/<name>/` 下创建 `config.toml`，重启后自动连接。

## 常见任务入口

- **新增工具** → `capabilities/tools/` 新建文件 + `@tool` 装饰器
- **修改工具调用优先级/错误处理** → `registry.py` 的 `call()`
- **修改工具自动加载逻辑** → `tools/_loader.py`
- **修改 MCP 连接方式** → `mcp_client.py`
- **查看所有已注册工具** → 运行时调用 `registry.get_all_tool_specs()`，或 grep `@tool` 装饰器

## 详细文档

- **Tool 系统完整指南**：[`capabilities/tools/README.md`](tools/README.md)
  — 权限档位选择、创建流程、代码示例、常见错误
