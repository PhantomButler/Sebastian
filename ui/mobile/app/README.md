# App 路由目录

> 上级：[ui/mobile/README.md](../README.md)

Expo Router 文件系统路由实现，Stack 导航器为根，无 Tab Bar。

## 目录结构

```text
app/
├── _layout.tsx              # RootLayout：全局 Provider 栈 + Stack 导航器
├── index.tsx                # ChatScreen（栈根，不可弹出）
├── subagents/
│   ├── index.tsx            # Sub-Agent 列表（Stack push）
│   ├── [agentId].tsx        # Agent 的 Session 列表
│   └── session/
│       └── [id].tsx         # Session 详情页（含 Composer + Todo 侧边栏）
└── settings/
    ├── index.tsx            # 设置首页（4 张分类状态卡）
    ├── connection.tsx       # 连接与账户详细页
    ├── appearance.tsx       # 外观详细页
    ├── advanced.tsx         # 高级详细页
    └── providers/
        ├── index.tsx        # 模型与 Provider 列表
        ├── new.tsx          # 新增 Provider
        └── [providerId].tsx # 编辑 Provider
```

## 全局布局（_layout.tsx）

RootLayout 的 Provider 嵌套顺序：

```
SafeAreaProvider
└── GestureHandlerRootView
    └── QueryClientProvider
        └── KeyboardProvider
            └── AppInit
                ├── ThemeProvider
                ├── Stack (headerShown: false)
                └── ApprovalModal
```

### AppInit 职责

- 加载本地设置（`useSettingsStore.load()`）
- 注册 SSE 监听（审批事件）
- 注册推送 token（FCM）
- 水合待审批项（`getApprovals()`）
- 同步当前 provider 的 thinking capability
- 监听 AppState 变化（前台时刷新审批状态）
- 监听通知点击（路由到对应页面）
- 设置 401 全局处理（清 token + 跳转设置页）

## 页面说明

### `index.tsx` — ChatScreen

主对话页，栈根页面：
- 左侧边栏：AppSidebar（功能入口 + 历史对话 + 新对话）
- 右侧边栏：TodoSidebar（任务/Todo 列表）
- 键盘适配：KeyboardGestureArea + KeyboardChatScrollView + KeyboardStickyView
- 核心操作：`sendTurn()`、`cancelTurn()`、`deleteSession()`

### `subagents/` — Sub-Agent 浏览

三层页面链路：
1. `index.tsx`：Agent 列表
2. `[agentId].tsx`：某 Agent 的 Session 列表（含 NewChatFAB 懒创建）
3. `session/[id].tsx`：Session 详情（含 Composer + Todo 侧边栏，复用键盘适配方案）

### `settings/` — 设置

首页 4 张分类状态卡，点击进入对应详细页：
- `connection.tsx`：服务器地址、登录/登出、账户信息
- `appearance.tsx`：主题切换
- `advanced.tsx`：Memory 管理、Debug Logging 开关
- `providers/`：LLM Provider 的 CRUD

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 修改全局 Provider 栈或初始化逻辑 | `_layout.tsx` |
| 修改主对话页体验 | `index.tsx` |
| 修改 Sub-Agent 浏览链路 | `subagents/` |
| 修改设置页结构或分类 | `settings/index.tsx` |
| 修改 LLM Provider 管理 | `settings/providers/` |

---

> 新增页面后，请同步更新本 README 与 `ui/mobile/README.md` 中的页面结构。
