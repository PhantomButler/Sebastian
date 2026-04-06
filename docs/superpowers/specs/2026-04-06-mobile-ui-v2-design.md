# Mobile App UI v2 设计文档

**日期**：2026-04-06
**状态**：已确认，待实施

## 背景与目标

对移动端 App UI 进行一次较大重构，提升沉浸感与质感，交互方式对齐 ChatGPT 移动端思路。核心变化是移除底部 Tab Bar，改用右滑侧边栏作为唯一导航入口，主对话页作为 App 的落地页和栈根。

**不在本次范围内**：夜间/日间主题切换（主题系统作为独立任务规划，本次只做 light 默认背景）。

---

## 1. 导航架构重组

### 方案：Stack 根 + 侧边栏驱动导航

拆除 `(tabs)` 文件夹，`app/_layout.tsx` 改为纯 Stack 导航器，Chat 页作为栈根，Sub-Agents 和设置通过 Stack push 进入。

### 目录变化

**改前：**
```
app/
├── _layout.tsx         ← Stack（含 Tabs）
├── index.tsx           ← redirect 到 (tabs)/chat
├── (tabs)/
│   ├── _layout.tsx     ← Tabs 导航器
│   ├── chat/index.tsx
│   ├── subagents/index.tsx
│   └── settings/index.tsx
└── subagents/
    ├── [agentId].tsx
    └── session/[id].tsx
```

**改后：**
```
app/
├── _layout.tsx         ← 纯 Stack 导航器
├── index.tsx           ← ChatScreen（栈根，直接渲染）
├── subagents/
│   ├── index.tsx       ← Sub-Agents 列表（原 (tabs)/subagents/index.tsx）
│   ├── [agentId].tsx   ← 不变
│   └── session/[id].tsx ← 不变
└── settings/
    └── index.tsx       ← 设置页（原 (tabs)/settings/index.tsx）
```

`(tabs)/` 整组删除。

### 导航流程

| 场景 | 行为 |
|------|------|
| App 启动 | 直接进入 ChatScreen，无 redirect，无 Tab Bar |
| 侧边栏点 Sub-Agents | `router.push('/subagents')`，Stack push，顶部有返回键 |
| 侧边栏点设置 | `router.push('/settings')`，Stack push，顶部有返回键 |
| 侧边栏点系统总览 | 占位，暂无跳转（后续规划） |
| 点击历史 Session | 关闭侧边栏，切换 currentSessionId，停留在 ChatScreen |
| 新对话按钮 | `startDraft()` + 关闭侧边栏，停留在 ChatScreen |

---

## 2. 侧边栏（Sidebar + AppSidebar）

### 2.1 Sidebar 容器（`src/components/common/Sidebar.tsx`）

**宽度**：屏幕宽度 × 75%（不变）。右侧 25% 为遮罩区，点击或左滑关闭。

**手势支持**（新增）：
- 使用 `react-native-gesture-handler` 的 `PanGestureHandler`（Expo 已内置，无需额外安装）
- **打开**：侧边栏关闭时，手势起点 x < 30px 且向右滑动 → 开启
- **关闭**：侧边栏开启时，在面板内向左滑动 → 关闭
- **点击关闭**：点击右侧 25% 遮罩区
- 拖动时跟手动画，松开后根据位移判断是回弹还是完成（阈值：拖动超过宽度 30% 则完成）
- 现有 `Animated.timing` 250ms 保留用于按钮触发和回弹

### 2.2 侧边栏内容（`src/components/chat/AppSidebar.tsx`，替换现有 ChatSidebar）

内容分三个区域，从上到下：

**顶部：功能入口区**
- 3 个全宽行，每行带左侧图标、标题、右侧 `›` 箭头
- Sub-Agents（`🤖`）：点击后关闭侧边栏，`router.push('/subagents')`
- 设置（`⚙️`）：点击后关闭侧边栏，`router.push('/settings')`
- 系统总览（`📊`）：显示"即将推出"标签，不可点击，作为占位

**中间：历史对话区**
- 复用现有 Session 列表逻辑（`useSessions` 数据）
- 当前激活 session 高亮
- 点击切换 session + 关闭侧边栏
- 删除逻辑保持不变（`onDelete` 回调）

**底部：新对话按钮**
- 黑色胶囊按钮（`background: #111; border-radius: 22px`）
- 文案：`✏️ 新对话`
- 点击：`startDraft()` + 关闭侧边栏
- `draftSession === true` 时按钮 disabled（用户已在草稿状态）

---

## 3. 主对话页（`app/index.tsx`）

### 3.1 背景色

从 `#0d0d0d`（黑色）改为 `#ffffff`（白色）。
这是 light 默认背景。主题系统上线后，此值成为 light token，无需返工。

### 3.2 输入框浮动

`MessageInput` 改为绝对定位，脱离 flex 文档流：

```
position: 'absolute'
bottom: insets.bottom（safe area）
left: 0
right: 0
```

`ConversationView` 加对应 `paddingBottom`（等于输入框高度 + safe area），确保最后一条消息不被遮挡。

`MessageInput` 背景使用轻微半透明或纯白，视觉上与消息区分离，体现悬浮质感。

---

## 4. Session 列表刷新 Bug 修复

**根因**：新建 session 后 `handleSend` 调用 `persistSession`（Zustand 本地状态），但侧边栏读取的是 React Query 的 `useSessions()` 数据，两者未同步，导致侧边栏不显示新 session。

**修复**：在 `app/index.tsx` 的 `handleSend` 里，新建 session 分支加一行：

```ts
if (!currentSessionId) {
  persistSession({ ... });
  queryClient.invalidateQueries({ queryKey: ['sessions'] }); // ← 新增
}
```

`persistSession` 保留——确保新 session 立即反映在当前页面状态，不依赖网络请求延迟。`invalidateQueries` 触发后台重新获取，让侧边栏列表与服务端同步。

---

## 5. 受影响文件清单

| 文件 | 动作 |
|------|------|
| `app/_layout.tsx` | 改为纯 Stack 导航，移除 Tabs 引用 |
| `app/index.tsx` | 改为直接渲染 ChatScreen；输入框改绝对定位；修 session 刷新 Bug |
| `app/(tabs)/` | 整组删除 |
| `app/subagents/index.tsx` | 新建（内容来自 `(tabs)/subagents/index.tsx`） |
| `app/settings/index.tsx` | 新建（内容来自 `(tabs)/settings/index.tsx`） |
| `src/components/common/Sidebar.tsx` | 加 PanGestureHandler 手势支持 |
| `src/components/chat/AppSidebar.tsx` | 新建，替代 ChatSidebar；含功能区 + 历史区 + 新对话按钮 |
| `src/components/chat/ChatSidebar.tsx` | 删除（被 AppSidebar 替代） |
| `src/components/chat/MessageInput.tsx` | 改为绝对定位浮动样式 |

`app/subagents/[agentId].tsx` 和 `app/subagents/session/[id].tsx` 内部路由不变，无需修改。

---

## 6. 范围外事项（后续独立规划）

- **主题系统**：夜间/日间模式切换，需建 theme context + 全量 token 替换
- **系统总览页**：当前作为侧边栏占位入口，页面待规划
