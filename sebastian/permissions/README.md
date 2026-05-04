# Permissions 模块

> 上级：[sebastian/README.md](../README.md)

三层权限审查与 workspace 边界强制执行系统，所有 Agent 通过 PolicyGate 访问工具。

## 目录结构

```text
permissions/
├── __init__.py    # 包定义
├── types.py       # PermissionTier、ALL_TOOLS、ToolCallContext、ToolReviewPreflight、ReviewDecision
├── gate.py        # PolicyGate：权限执行代理
└── reviewer.py    # PermissionReviewer：LLM 审查器
```

## 三层权限模型

| Tier | 枚举值 | 行为 | 典型工具 |
|------|--------|------|---------|
| LOW | `low` | 直接执行，无审查 | Read、Glob、Grep |
| MODEL_DECIDES | `model_decides` | 注入 `reason` 字段，LLM reviewer 决策 | Write、Edit、Bash |
| HIGH_RISK | `high_risk` | 始终请求用户审批 | （预留） |

## PolicyGate

文件：`gate.py`

CapabilityRegistry 的权限执行代理，所有工具调用经过此 gate：

1. **工具白名单检查**：`None` / 空集合表示不允许能力工具，只有 `ALL_TOOLS` 表示全量工具。
2. **reason 注入**：`get_all_tool_specs()` 对 MODEL_DECIDES 工具的 schema 注入必填 `reason` 字段。
3. **workspace 边界检查**：含 `file_path` / `path` 参数时，路径在 workspace 外直接请求用户审批（跳过 LLM reviewer）。
4. **tier 分支执行**：
   - LOW → 直接调用 registry
   - MODEL_DECIDES → 可选 `review_preflight` → PermissionReviewer 审查 → proceed 则执行，escalate 则请求用户审批
   - HIGH_RISK → 直接请求用户审批

依赖：
- `CapabilityRegistry`：实际工具调用
- `PermissionReviewer`：LLM 审查决策
- `ApprovalManagerProtocol`：用户审批交互

## PermissionReviewer

文件：`reviewer.py`

无状态 LLM 审查器，对 MODEL_DECIDES 工具调用做 proceed/escalate 决策：

- System prompt 动态注入 `workspace_dir`，Bash 命令写 workspace 外文件时强制 ESCALATE
- 通过 `LLMProviderRegistry` 懒解析默认 provider
- 无 provider 配置时安全降级为 escalate
- LLM 返回 JSON `{"decision": "proceed"|"escalate", "explanation": "..."}`
- 解析失败时默认 escalate

## 类型定义

文件：`types.py`

| 类型 | 说明 |
|------|------|
| `PermissionTier` | `StrEnum`：LOW / MODEL_DECIDES / HIGH_RISK |
| `ALL_TOOLS` | 显式全量工具 sentinel；替代旧的 `allowed_tools=None` 全量语义 |
| `ToolCallContext` | 工具调用上下文：task_goal、session_id、task_id、agent_type、depth、allowed_tools |
| `ToolReviewPreflight` | MODEL_DECIDES 审查前的工具动态上下文结果；只进入 reviewer input，不进入真实工具参数 |
| `ReviewDecision` | 审查结果：decision（proceed/escalate）+ explanation |

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 修改权限 tier 定义或新增 tier | `types.py` |
| 修改工具调用审查流程 | `gate.py` |
| 修改 LLM 审查 prompt 或决策逻辑 | `reviewer.py` |
| 修改 workspace 边界规则 | `gate.py`（边界检查段）+ `capabilities/tools/_path_utils.py` |
| 修改工具 tier 分配 | 各工具定义处的 `permission_tier` 属性 |

---

> 相关 spec：`docs/architecture/spec/agents/permission.md`、`docs/architecture/spec/agents/workspace-boundary.md`
