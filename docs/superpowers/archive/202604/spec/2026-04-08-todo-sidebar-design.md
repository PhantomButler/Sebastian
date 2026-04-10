# Todo 侧边栏与 todo_write 工具设计

> 创建日期：2026-04-08
> 状态：Draft

## 1. 背景与目标

### 1.1 当前状态

- `app/subagents/session/[id].tsx` 顶部有「消息 / 任务」切换栏，任务视图渲染后端 `TaskRecord`（由 orchestrator goal_decomposer 拆出的系统级调度单元）
- 主对话页 `app/index.tsx` 没有任何任务追踪视图
- 现有侧边栏 `Sidebar.tsx` 从屏幕左边缘 25px 触发区右滑开启，承载会话列表与功能入口
- Agent 和用户缺少一个**轻量、实时、LLM 自维护**的进度清单机制

### 1.2 目标

1. 新增一个右侧滑出的侧边栏，集中展示**当前 session** 的进度信息
2. 侧边栏内容分两段：
   - **Tasks 区**：渲染后端已有的 `TaskRecord`（粗粒度、系统创建、只读展示）
   - **Todos 区**：渲染 LLM 通过新工具 `todo_write` 维护的扁平待办清单（细粒度、LLM 自维护）
3. 新增 `todo_write` 工具，参考 Claude Code V1 `TodoWrite` 的设计：单工具、覆盖式、扁平列表
4. 主对话页和 sub-agent session 详情页**共用**这套右侧边栏
5. 用这套侧边栏**取代** sub-agent session 详情页的顶部「消息/任务」切换栏
6. 把当前左侧边栏"从边缘 25px 滑动触发"升级为"内容区任意位置横向滑动触发"，为平板/iPad 体验铺路

### 1.3 非目标

- 本期**不**让 LLM 通过 tool 创建/修改后端 `TaskRecord`（Claude Code V2 Task 风格）。Task 仍然由 orchestrator 逻辑创建。未来若有需要按「未来演进」章节的约定低成本扩展。
- 本期**不**实现 Todo 与 Task 的数据层关联（无 `task_id` 外键）。视觉上分两段展示即可。

## 2. 数据模型

### 2.1 TodoItem

严格对齐 Claude Code V1 TodoWrite 的字段：

```typescript
type TodoStatus = 'pending' | 'in_progress' | 'completed';

interface TodoItem {
  content: string;      // 祈使形式，描述待办（"Run tests"）
  activeForm: string;   // 进行时形式，in_progress 时展示（"Running tests"）
  status: TodoStatus;
}

type TodoList = TodoItem[];
```

- **无 id**：列表位置即身份。LLM 整体覆盖，不需要维护稳定标识
- **无 task_id**：本期扁平存储，不与 `TaskRecord` 做数据层关联
- **无 created_at / updated_at**：列表整体的 mtime 就是最后修改时间，单项时间戳是过度设计

### 2.2 存储位置

与现有 Task 存储相邻，便于未来迁移：

```
SEBASTIAN_DATA_DIR/sessions/
  <agent_type>/<session_id>/
    session.json
    tasks/<task_id>.json     ← 现有
    todos.json               ← 新增，整个 session 的 todo 列表单文件
```

`todos.json` 结构：

```json
{
  "todos": [
    {"content": "...", "activeForm": "...", "status": "pending"}
  ],
  "updated_at": "2026-04-08T12:34:56Z"
}
```

**子 session 隔离**：子 agent 运行时 `ToolCallContext.session_id` 是子 session 的 id，`todos.json` 物理位于子 session 目录下，天然与父 session 隔离，不共享不串扰。

### 2.3 与 Claude Code V1 的一处关键偏离

Claude Code V1 `TodoWriteTool.call()` 有 `const newTodos = allDone ? [] : todos`——当所有项为 completed 时自动清空列表。

**本实现不做此自动清空**。按用户需求：只要 LLM 没写新列表，完成项保留显示（划线 + 绿色成功图标），给用户留下"已完成了什么"的可见痕迹。清除由 LLM 在下次 `todo_write` 时自行决定。

## 3. 后端设计

### 3.1 新增 tool：`todo_write`

位置：`sebastian/capabilities/tools/todo_write/__init__.py`

```python
from __future__ import annotations

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.store.todo_store import TodoStore

@tool(
    name="todo_write",
    description=(
        "Create or update the session's todo list. Use proactively for "
        "multi-step tasks (3+ steps). Overwrites the entire list each call. "
        "Each item needs {content, activeForm, status}. "
        "Keep exactly one item in_progress at a time when working."
    ),
    permission_tier=PermissionTier.LOW,
)
async def todo_write(todos: list[dict]) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None or not ctx.session_id:
        return ToolResult(ok=False, error="todo_write requires session context")

    try:
        items = _validate_todos(todos)
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))

    store = TodoStore()
    old = await store.read(ctx.agent_type, ctx.session_id)
    await store.write(ctx.agent_type, ctx.session_id, items)

    return ToolResult(
        ok=True,
        output={
            "old_count": len(old),
            "new_count": len(items),
            "session_id": ctx.session_id,
        },
    )
```

关键点：

- `permission_tier=LOW`：只读/改本地状态文件，无外部副作用
- `session_id` / `agent_type` 从 `get_tool_context()` 运行时注入，**不**出现在函数签名
- 参数 `todos` 是完整列表（覆盖式语义）
- 校验：每项必须有 `content`（非空）、`activeForm`（非空）、`status ∈ {pending, in_progress, completed}`
- `_validate_todos` 实现放同目录 `_validation.py`（如果简单也可内联）

#### 3.1.1 覆盖式语义说明

这是本设计最反直觉、但也最关键的一点：**LLM 从不"更新"或"增量修改"单个 todo，也不传 id 或序号**。每次调用 `todo_write`，LLM 传入完整的新列表，工具整体覆盖 `todos.json`。没有 create/update/delete 的动作区分——只有一个动作：**写入当前完整状态**。

所有操作都通过"重传整个列表"实现：

**场景 A — 首次创建**

LLM 发现要做 3 步工作，写入初始列表：

```json
{
  "todos": [
    {"content": "写 LoginForm 组件", "activeForm": "正在写 LoginForm 组件", "status": "in_progress"},
    {"content": "接入 auth API",     "activeForm": "正在接入 auth API",     "status": "pending"},
    {"content": "加路由守卫",        "activeForm": "正在加路由守卫",        "status": "pending"}
  ]
}
```

文件不存在则创建。

**场景 B — 完成一项、开始下一项**

LLM 重传**整个**列表，只改动相关项的 status：

```json
{
  "todos": [
    {"content": "写 LoginForm 组件", "activeForm": "...", "status": "completed"},
    {"content": "接入 auth API",     "activeForm": "...", "status": "in_progress"},
    {"content": "加路由守卫",        "activeForm": "...", "status": "pending"}
  ]
}
```

**场景 C — 中途插入新项**

LLM 自行决定新项的插入位置，重写整个列表：

```json
{
  "todos": [
    {"content": "写 LoginForm 组件",     "activeForm": "...", "status": "completed"},
    {"content": "写通用 error handler",  "activeForm": "...", "status": "in_progress"},
    {"content": "接入 auth API",         "activeForm": "...", "status": "pending"},
    {"content": "加路由守卫",            "activeForm": "...", "status": "pending"}
  ]
}
```

**场景 D — 开启全新任务**

用户抛出无关的新任务时，LLM 写一个全新列表，旧列表被整体替换（包括已 completed 的历史项）：

```json
{
  "todos": [
    {"content": "写 RegisterForm 组件", "activeForm": "...", "status": "in_progress"},
    {"content": "加表单校验",           "activeForm": "...", "status": "pending"}
  ]
}
```

旧的登录页 todo 全部消失。"创建新列表"和"更新现有列表"是同一个动作，由 LLM 自己决定是否携带历史项。

**LLM 如何知道"当前列表长什么样"**：通过 system prompt 注入（见下）。LLM 每轮都能在上下文里看到最新的 todos 快照，然后在其基础上做增删改，再整体回写。它**不需要 read tool**。

**为什么不引入 id / 序号**：

1. 有 id 就要维护 id 的稳定性、生命周期、引用一致性，LLM 容易传错 id 更新错项
2. 覆盖式让 LLM 用最自然的方式表达意图——它脑子里维护的就是"一份列表"，不需要翻译成"update id=3 的 status"
3. 列表通常只有 3-10 项，整体传输的 token 成本可忽略
4. 位置即身份，LLM 可以自然表达"在第 2 位插入"这类人类思维

#### 3.1.2 LLM 获取当前 todo 状态的路径

本期**不提供独立的 read tool**。Todo 列表通过两条路径让 LLM 可见：

1. **System prompt 注入**：每轮 agent loop 开始前，把当前 `todos.json` 的内容拼接进 system prompt（或 user-turn prefix），避免 LLM 额外 tool call
2. **tool 返回结构化 diff**：`todo_write` 返回 `old_count / new_count`，LLM 写入时得到反馈

注入位置：`sebastian/core/base_agent.py` 或 `session_runner.py` 的 turn 起点（实现阶段由 plan 决定具体位置）。

### 3.2 新增 store：`TodoStore`

位置：`sebastian/store/todo_store.py`

职责：`todos.json` 文件的原子读写。

接口：

```python
class TodoStore:
    def __init__(self, data_dir: Path | None = None) -> None: ...

    async def read(self, agent_type: str, session_id: str) -> list[TodoItem]:
        """返回当前 session 的 todo 列表，文件不存在返回空列表。"""

    async def write(
        self, agent_type: str, session_id: str, todos: list[TodoItem]
    ) -> None:
        """原子写入（tmp + rename），更新 updated_at。"""
```

- 使用 `session_store` 的 `data_dir` 解析规则，定位到 `sessions/<agent_type>/<session_id>/todos.json`
- 路径遵循 `_path_utils` 规范
- 写入采用 tmp-file + rename，防止并发损坏（与 `index_store.py` 一致的做法）
- `TodoItem` 用 dataclass 或 Pydantic（跟现有 `sebastian/core/types.py` 风格一致）

### 3.3 Gateway endpoints

位置：`sebastian/gateway/routes/sessions.py`（或新建 `todos.py`）

```
GET  /api/v1/sessions/{session_id}/todos?agent={agent_type}
     → {"todos": [...], "updated_at": "..."}
```

- 仅 GET，不提供 POST/PUT（前端只读，写入路径只有 LLM tool 调用）
- 权限：复用现有 session 权限检查
- 404 / 空文件 → 返回 `{"todos": [], "updated_at": null}`

### 3.4 SSE 事件

新增事件类型：`todo_updated`

```json
{
  "type": "todo_updated",
  "session_id": "...",
  "agent_type": "...",
  "count": 5
}
```

触发点：`todo_write` tool 成功写入后，通过现有 event bus 发布。

前端订阅后 `queryClient.invalidateQueries(['session-todos', sessionId])` 即可刷新。事件不携带完整列表（避免 payload 膨胀），前端靠 invalidate + refetch 拉取。

## 4. 前端设计

### 4.1 Sidebar 参数化

修改 `ui/mobile/src/components/common/Sidebar.tsx`：

```typescript
interface Props {
  visible: boolean;
  onOpen: () => void;
  onClose: () => void;
  children: React.ReactNode;
  side?: 'left' | 'right';  // 新增，默认 'left'
}
```

内部改动：

- `translateX` 初值与目标值按 `side` 符号翻转
  - `left`: 关闭时 `-WIDTH`，打开时 `0`
  - `right`: 关闭时 `+WIDTH`，打开时 `0`
- 面板 `position` 属性按 `side` 切换 `left: 0` / `right: 0`
- 阴影 `shadowOffset.width` 按 `side` 翻转符号
- **关闭手势**方向按 `side` 翻转：
  - `left`：内部 `translationX < -SWIPE_THRESHOLD` 关闭
  - `right`：内部 `translationX > SWIPE_THRESHOLD` 关闭
- **删除**内部 `edgeTrigger` 视图（打开手势提升到页面层，见 4.2）

### 4.2 页面级 ContentPanGestureArea

新建 `ui/mobile/src/components/common/ContentPanGestureArea.tsx`：

```typescript
interface Props {
  onOpenLeft?: () => void;
  onOpenRight?: () => void;
  children: React.ReactNode;
}
```

实现要点：

- 用 `PanGestureHandler`（`react-native-gesture-handler`）包裹 children
- `activeOffsetX: [-10, 10]`：横向位移超过 10px 才激活，避免误触
- `failOffsetY: [-15, 15]`：纵向位移先达 15px 则 fail，让 FlatList 正常滚动
- 在 `END` 状态判定方向：
  - `translationX > SWIPE_THRESHOLD && velocityX > 0` → `onOpenLeft?.()`
  - `translationX < -SWIPE_THRESHOLD && velocityX < 0` → `onOpenRight?.()`
- 不处理"关闭"（关闭由 Sidebar 自身和 overlay 负责）

使用位置：

- `app/index.tsx`：包住 `KeyboardGestureArea` 外层（或等价位置），不包住 header 和 Composer
- `app/subagents/session/[id].tsx`：同上

与 `KeyboardGestureArea` 共存：`KeyboardGestureArea` 消费纵向滑动（键盘收起），我们的 pan 只消费横向，两者正交无冲突。

### 4.3 TodoSidebar 组件

新建 `ui/mobile/src/components/chat/TodoSidebar.tsx`：

渲染结构：

```
┌────────────────────────────┐
│ 任务                        │  ← section header
├────────────────────────────┤
│  • Task A   [running]       │
│  • Task B   [done]          │
│  （空时："暂无任务"）         │
├────────────────────────────┤
│ 待办                        │  ← section header
├────────────────────────────┤
│  ⬤ 写 Composer 组件 (高亮)  │  ← in_progress
│  ○ 接 SSE 事件              │  ← pending
│  ✓ ~~加路由~~ (灰)          │  ← completed (strikethrough)
│  （空时："暂无待办"）         │
└────────────────────────────┘
```

Props：

```typescript
interface Props {
  sessionId: string | null;
  agentType: string;
  onClose: () => void;
}
```

数据：

- Tasks：复用现有 `useQuery(['session-tasks', sessionId, agentType])`
- Todos：新增 `useSessionTodos(sessionId, agentType)` hook，包装 `useQuery(['session-todos', sessionId, agentType])`

### 4.4 Icons 集成

修改 `ui/mobile/src/components/common/Icons.tsx`，新增两个图标组件：

```typescript
export const TodoCircleIcon = (props) => /* 渲染 todo_circle.svg */;
export const SuccessCircleIcon = (props) => /* 渲染 success_circle.svg */;
```

SVG 源文件已存在：

- `ui/mobile/src/assets/icons/todo_circle.svg`（空心圆）
- `ui/mobile/src/assets/icons/success_circle.svg`（绿色成功）

使用 `react-native-svg`（仓库已有依赖）。若 Icons.tsx 现有其他图标也用相同方式，沿用同风格；否则用 `SvgXml` 或静态 import。

TodoSidebar 渲染逻辑：

- `pending` → `<TodoCircleIcon />` + 正常文字
- `in_progress` → `<TodoCircleIcon color="#007AFF" />` + 蓝色加粗文字 + 显示 `activeForm` 而非 `content`
- `completed` → `<SuccessCircleIcon />` + 文字 `textDecorationLine: 'line-through'` + 灰色

### 4.5 页面集成

**`app/index.tsx`**：

```tsx
const [leftOpen, setLeftOpen] = useState(false);
const [rightOpen, setRightOpen] = useState(false);

<ContentPanGestureArea
  onOpenLeft={() => setLeftOpen(true)}
  onOpenRight={() => setRightOpen(true)}
>
  <KeyboardGestureArea ...>
    {/* ConversationView + Composer */}
  </KeyboardGestureArea>
</ContentPanGestureArea>

<Sidebar visible={leftOpen} side="left" ...>
  <AppSidebar ... />
</Sidebar>

<Sidebar visible={rightOpen} side="right" ...>
  <TodoSidebar sessionId={currentSessionId} agentType="sebastian" ... />
</Sidebar>
```

**`app/subagents/session/[id].tsx`**：

- **删除** `tab` state、顶部 `<View style={styles.tabs}>` tab 栏、相关样式
- **删除** `SessionDetailView` import 和使用
- 页面主体直接渲染 `ConversationView`
- 外层包 `ContentPanGestureArea`，挂载右侧 `TodoSidebar`
- **保留** `useQuery(['session-tasks', ...])`，因为 TodoSidebar 要用（实际上 hook 移到 TodoSidebar 内部订阅即可）
- 这个页面**不挂左侧 sidebar**（左侧 sidebar 只在主对话页）

### 4.6 删除的文件/代码

- 删除 `ui/mobile/src/components/subagents/SessionDetailView.tsx`
- 删除 `app/subagents/session/[id].tsx` 的 `tab` 相关逻辑、`MOCK_TASKS`、tab 样式

## 5. 改动清单

### 5.1 后端新增

| 文件 | 动作 |
|---|---|
| `sebastian/capabilities/tools/todo_write/__init__.py` | 新建 |
| `sebastian/store/todo_store.py` | 新建 |
| `sebastian/gateway/routes/sessions.py` | 增加 `GET /api/v1/sessions/{id}/todos` |
| `sebastian/protocol/events.py`（或等价位置） | 新增 `todo_updated` 事件类型 |
| `sebastian/core/base_agent.py` 或 `session_runner.py` | 每轮 turn 开始时把 `todos.json` 内容注入 prompt |

### 5.2 后端修改

| 文件 | 动作 |
|---|---|
| `sebastian/capabilities/tools/README.md` | 增加 `todo_write` 工具条目 |
| `sebastian/store/README.md` | 增加 TodoStore 条目 |

### 5.3 前端新增

| 文件 | 动作 |
|---|---|
| `ui/mobile/src/components/chat/TodoSidebar.tsx` | 新建 |
| `ui/mobile/src/components/common/ContentPanGestureArea.tsx` | 新建 |
| `ui/mobile/src/hooks/useSessionTodos.ts` | 新建 |
| `ui/mobile/src/api/todos.ts` | 新建 |

### 5.4 前端修改

| 文件 | 动作 |
|---|---|
| `ui/mobile/src/components/common/Sidebar.tsx` | 参数化 `side` prop，删除内部 edgeTrigger |
| `ui/mobile/src/components/common/Icons.tsx` | 注册 TodoCircleIcon / SuccessCircleIcon |
| `ui/mobile/app/index.tsx` | 接入 ContentPanGestureArea + 右侧 TodoSidebar |
| `ui/mobile/app/subagents/session/[id].tsx` | 删除顶部 tab 栏，接入右侧 TodoSidebar |
| `ui/mobile/src/api/sse.ts` 或 `src/hooks/useSSE.ts` | 处理 `todo_updated` 事件 → invalidate query |
| `ui/mobile/README.md` | 更新修改导航，增加 TodoSidebar / ContentPanGestureArea 条目 |

### 5.5 删除

| 文件 | 动作 |
|---|---|
| `ui/mobile/src/components/subagents/SessionDetailView.tsx` | 删除 |
| `ui/mobile/src/components/subagents/README.md` | 同步更新 |

## 6. 测试计划

### 6.1 后端

- `tests/unit/test_todo_store.py`：TodoStore 读写、空态、原子写入
- `tests/unit/test_todo_write_tool.py`：
  - 正常覆盖写入
  - 校验失败（空 content、无效 status）
  - 无 session context 时报错
  - 返回 old_count / new_count
- `tests/integration/test_sessions_todos_api.py`：Gateway GET endpoint

### 6.2 前端

- 手动验证清单（Android 模拟器 + 真机各一轮）：
  1. 主对话页从内容区任意位置右滑 → 左侧栏打开
  2. 主对话页从内容区任意位置左滑 → 右侧栏打开
  3. 纵向滚动消息列表不误触发横向开启
  4. 键盘弹起时横向手势仍可用
  5. sub-agent session 页左滑 → 右侧栏打开，无左侧栏
  6. 空 session 右侧栏打开显示"暂无任务/待办"
  7. LLM 写入 todo 后右侧栏实时刷新（SSE 流）
  8. 完成项显示划线 + 绿色图标，未完成显示空心圆，in_progress 蓝色高亮
  9. sub-agent session 页顶部「消息/任务」tab 已不存在

## 7. 风险与缓解

### 风险 1：横向 pan 手势与 FlatList 纵向滚动冲突

`activeOffsetX / failOffsetY` 是标准解法，但 Android 真机上偶发首次触摸判定不准。

**缓解**：实现阶段在真机实测，若手感差，降级为"内容区前 1/3 宽度作为左开启热区，后 1/3 作为右开启热区"，相当于扩大版的边缘触发区，对 iPad 仍远好于 25px。

### 风险 2：System prompt 注入位置

把 todos 注入到 prompt 会增加每轮 token 消耗。若列表很长（>50 项）可能浪费 token。

**缓解**：本期不做截断（实际使用里 todo 很少超过 20 项）。若未来成为问题，可在注入层加"只显示 in_progress + pending，completed 折叠为计数"。

### 风险 3：子 session 的 todo 与父 session 不联动

子 agent 有独立 todo，用户在父 session 侧边栏看不到子 session 的进度。

**缓解**：这是刻意的隔离（用户确认过），不是 bug。用户进入子 session 详情页自然能看到。未来若需要跨层聚合，在 Task 层做（Task 本身有父子关系），不在 Todo 层做。

## 8. 未来演进：V2 Task Tool 预留

若未来需要让 LLM 通过 tool 直接创建/修改后端 `TaskRecord`（参考 Claude Code V2 `TaskCreate / TaskUpdate / TaskList / TaskGet`），本设计已做好零成本演进准备：

1. **命名空间不冲突**：本期工具叫 `todo_write`（不占用 `task_*` 前缀）
2. **存储位置相邻**：`todos.json` 与 `tasks/*.json` 同级，未来若要把 Todo 升级为独立 Task 记录，一次性迁移脚本只需拆 `todos.json` → `tasks/<uuid>.json`
3. **字段可平滑扩展**：V2 Task 需要的 `subject / description / activeForm / status / owner / blocks / blockedBy / metadata`，其中 `activeForm / status` 本期 TodoItem 已有，迁移时 `content` → `subject`，其余字段补默认值
4. **UI 分段不反悔**：右侧边栏 Tasks 区和 Todos 区分离，未来若合并只是把两个 Section 合成一个

V2 升级全程是**加法重构**，不拆老代码。

## 9. 参考

- Claude Code V1 TodoWrite 源码：`/Users/ericw/work/code/ai/claude_code_src/tools/TodoWriteTool/`
- Claude Code V2 Task 源码：`/Users/ericw/work/code/ai/claude_code_src/tools/Task{Create,Update,List,Get}Tool/`
- 现有 Sidebar 实现：`ui/mobile/src/components/common/Sidebar.tsx`
- 工具开发规范：`sebastian/capabilities/tools/README.md`
- 工具运行时上下文：`sebastian/core/tool_context.py`
