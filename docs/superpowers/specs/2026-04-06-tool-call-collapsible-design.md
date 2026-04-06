# Tool Call 可折叠交互设计

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 App 中 tool call 从平铺列表改为两层可折叠交互，减少视觉噪音，同时保留按需查看完整参数和输出的能力。

**范围:** 仅涉及 `ui/mobile/src/components/conversation/` 下的 tool call 渲染组件和 `Icons.tsx`。不涉及后端、数据结构或其他 UI 组件。

---

## 1. 现状

当前 `ToolCallRow` 始终平铺显示一行：状态点 + 工具名 + input 摘要（截断 80 字符）。`ToolCallGroup` 用断开的竖线段连接相邻 tool call。不显示 `result`，不支持展开/折叠。

**现有文件：**
- `ToolCallRow.tsx` — 单行渲染，包含 `extractInputSummary` 和 `KEY_PRIORITY` 逻辑
- `ToolCallGroup.tsx` — 遍历 tool 数组，渲染 ToolCallRow + 竖线连接器
- `Icons.tsx` — SVG 图标组件（DeleteIcon 等），使用 inline Path 模式
- `right_arrow.svg` — 已有的右箭头 SVG 源文件

**现有数据结构（`types.ts`）：**
```typescript
type ToolBlock = {
  type: 'tool';
  toolId: string;
  name: string;
  input: string;       // JSON 字符串
  status: 'running' | 'done' | 'failed';
  result?: string;     // 执行输出，running 时为 undefined
};
```

## 2. 设计

### 2.1 整体风格

- 极简，无卡片背景
- 竖线贯穿连接所有 tool call（不留断口）
- 箭头图标使用 `right_arrow.svg` 的 path data，创建 `RightArrowIcon` 组件，展开时 `rotate(90deg)`

### 2.2 两层折叠

**第一层：tool call 整体**

| 状态 | 显示 |
|------|------|
| 折叠（默认） | 状态点 + 工具名 + 摘要（单行截断），不显示箭头 |
| 展开 | 状态点 + 工具名 + 摘要 + ▼ 箭头（rotate 90deg），下方显示「参数」和「输出」两个区域 |

- 点击整行切换展开/折叠
- 所有 tool call 默认折叠

**第二层：参数/输出内容**

按换行符 `\n` 计算行数：

| 行数 | 显示 |
|------|------|
| ≤5 行 | 直接完整显示，不显示箭头 |
| >5 行 | 默认折叠：显示第一行摘要（单行截断省略） + ▶ 箭头 |

- 第二层折叠时，点击该行（摘要 + 箭头）展开
- 第二层展开后，点击整个展开内容块可折叠回去
- **最大显示行数上限：30 行**。展开后超过 30 行的内容截断，末尾显示 `… (共 N 行)` 提示总行数

### 2.3 参数显示格式

复用现有 `KEY_PRIORITY` 逻辑，只显示关键参数，格式为 `key: value`（每个参数一行）。

**KEY_PRIORITY 映射：**
```
Bash              → command
Read              → file_path
Write             → file_path
Edit              → file_path
Grep              → pattern, path
Glob              → pattern, path
delegate_to_agent → goal
其他              → command, file_path, path, goal, pattern, query（按序取第一个有值的）
```

如果 JSON 解析失败，直接显示原始 input 字符串。

### 2.4 输出区域的状态处理

| tool status | result | 输出区域显示 |
|-------------|--------|-------------|
| running | — | 显示 loading 指示：`● 执行中…`（● 使用 running 状态色 `#f5a623`） |
| done | 有值 | 显示 result 文本，受第二层折叠规则约束 |
| done | 空/undefined | 不显示输出区域 |
| failed | 有值 | 显示 result 文本，受第二层折叠规则约束 |
| failed | 空/undefined | 不显示输出区域 |

### 2.5 竖线连接

- `ToolCallGroup` 使用一条贯穿的绝对定位竖线，从第一个 tool call 的状态点到最后一个的状态点
- 状态点（8px 圆点）通过 `z-index` 覆盖在竖线上方
- 竖线颜色：`colors.border`

## 3. 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 重写 | `ToolCallRow.tsx` | 添加两层折叠交互、参数/输出渲染、箭头旋转 |
| 修改 | `ToolCallGroup.tsx` | 竖线从断开段改为贯穿绝对定位线 |
| 修改 | `Icons.tsx` | 新增 `RightArrowIcon`（从 right_arrow.svg 提取 path data） |
| 新增 | `CollapsibleContent.tsx` | 可复用的内容折叠组件（≤5 行直接显示，>5 行可折叠，上限 30 行） |

## 4. 不在范围内

- 数据结构变更（`types.ts` 中 `RenderBlock` 不变）
- 后端 SSE 事件格式
- `ThinkingBlock` 折叠行为（保持现状）
- `AssistantMessage` 分组逻辑（保持现状）
