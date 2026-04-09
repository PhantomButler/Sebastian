# UI Mobile Guide

> 上级：[项目根](../../INDEX.md)

本 README 面向 `ui/mobile/` 目录，帮助快速理解当前 React Native / Expo App 的目录结构、页面信息架构与主要功能模块。

## 目录定位

`ui/mobile/` 是 Sebastian 的主交互入口，当前以 Android 优先开发，但界面与交互正在向 iOS 风格靠拢，便于后续双端统一。

当前主要承担：

- `Sebastian` 主对话入口
- `Sub-Agents` 浏览与 Session 详情
- 设置页与本地连接配置
- REST + SSE 前端接入

建议配合阅读：

- `docs/superpowers/specs/2026-04-01-android-app-design.md`
- [sebastian/README.md](../../sebastian/README.md)
- `AGENTS.md`
- `CLAUDE.md`

## 顶层结构

```text
ui/mobile/
├── app/              # Expo Router 页面入口
│   ├── _layout.tsx
│   ├── index.tsx     # ChatScreen（Stack 根，直接渲染）
│   ├── subagents/    # Sub-Agent 页面
│   └── settings/     # 设置页面
├── assets/           # 静态资源
├── src/                  → [src/README.md](src/README.md)
│   ├── api/              → [src/api/README.md](src/api/README.md)（HTTP / SSE 请求封装）
│   ├── components/       → [src/components/README.md](src/components/README.md)（UI 组件，按领域分组）
│   │   ├── chat/         → [chat/README.md](src/components/chat/README.md)
│   │   ├── common/       → [common/README.md](src/components/common/README.md)
│   │   ├── composer/     → [composer/README.md](src/components/composer/README.md)
│   │   ├── conversation/ → [conversation/README.md](src/components/conversation/README.md)
│   │   ├── settings/     → [settings/README.md](src/components/settings/README.md)
│   │   └── subagents/    → [subagents/README.md](src/components/subagents/README.md)
│   ├── hooks/            → [src/hooks/README.md](src/hooks/README.md)（React Query / SSE 订阅封装）
│   ├── store/            → [src/store/README.md](src/store/README.md)（Zustand 本地 UI 状态）
│   └── types.ts          # 前端共享类型
├── android/          # Android 原生工程（expo run:android 生成/维护）
├── ios/              # iOS 原生工程（expo run:ios 生成/维护）
├── app.json
├── package.json
└── tsconfig.json
```

## 页面结构

### `app/`

当前采用 Expo Router 文件系统路由，Stack 导航器为根，Chat 页作为栈根，无底部 Tab Bar。

```text
app/
├── _layout.tsx            # 纯 Stack 导航器
├── index.tsx              # ChatScreen（栈根，直接渲染）
├── subagents/
│   ├── index.tsx          # Sub-Agent 列表页（Stack push）
│   ├── [agentId].tsx      # 某个 Sub-Agent 的 Session 列表
│   └── session/[id].tsx   # Session 详情页
└── settings/
    ├── index.tsx          # 设置首页（状态面板）
    ├── connection.tsx     # 连接与账户详细页
    ├── appearance.tsx     # 外观详细页
    ├── advanced.tsx       # 高级详细页
    └── providers/
        ├── index.tsx      # 模型与 Provider 列表页
        ├── new.tsx        # 新增 Provider
        └── [providerId].tsx # 编辑 Provider
```

### 当前导航信息架构

- 打开 App → 直接进入 ChatScreen（无 redirect，无 Tab Bar）
- 右滑或点击汉堡按钮 → 打开左侧边栏（AppSidebar）
  - 侧边栏顶部：Sub-Agents、设置、系统总览（占位）入口
  - 侧边栏中部：历史 Session 列表，点击切换会话
  - 侧边栏底部：新对话按钮
- 左滑（在对话内容区域任意位置） → 打开右侧 Todo 侧边栏（TodoSidebar），与左侧呈镜像；点击外部或右滑收起
- 点击 Sub-Agents → `router.push('/subagents')`，Stack push，顶部有返回键
- 点击设置 → `router.push('/settings')`，Stack push，顶部有返回键

## 子模块

- [src/](src/README.md) — 业务逻辑层（API / 组件 / Hooks / Store）

## `src/` 模块说明

### `src/api/`

与后端 `sebastian/gateway/` 对接的 API 封装层。

- `client.ts`：axios 实例与公共请求配置
- `auth.ts`：登录、健康检查、登出
- `turns.ts`：主对话请求
- `sessions.ts`：Session 列表、详情、任务
- `agents.ts`：Sub-Agent 列表相关接口
- `approvals.ts`：审批相关接口
- `sse.ts`：SSE 连接层

适合在以下场景进入：

- 调整请求路径或响应格式
- 处理网关联调问题
- 修复 SSE 协议兼容性

### `src/store/`

Zustand 本地 UI 状态层，只放前端状态，不作为业务真数据源。

- `session.ts`：当前 Session、草稿 Session、流式消息
- `agents.ts`：Sub-Agent 相关 UI 状态
- `approval.ts`：待审批项
- `settings.ts`：serverUrl、jwtToken、provider 等本地配置

### `src/hooks/`

面向页面的 query / subscription 封装。

- `useSessions.ts`
- `useMessages.ts`
- `useAgents.ts`
- `useSSE.ts`

通常在需要：

- 为页面接入 React Query
- 复用 SSE 订阅逻辑
- 做页面级数据装配

时优先修改这里。

### `src/components/`

按领域分组的 UI 组件目录。

#### `components/chat/`

- `AppSidebar.tsx`：左侧边栏内容（功能入口区 + 历史对话区 + 新对话按钮）
- `TodoSidebar.tsx`：右侧 Todo 侧边栏内容（任务区 + Todo 区，session 级绑定）
- `MessageList.tsx` / `MessageBubble.tsx` / `StreamingBubble.tsx`

#### `components/subagents/`

- `AgentList.tsx`：Sub-Agent 列表
- `SessionList.tsx`：某个 Agent 下的 Session 列表（含 `NewChatFAB` 浮动按钮，点击后调用 `POST /api/v1/agents/{type}/sessions` 懒创建 session）
- `AgentStatusBadge.tsx`
- `NewChatFAB.tsx`：Sub-Agent session 创建的浮动操作按钮

#### `components/settings/`

- `SettingsScreenLayout.tsx`
- `SettingsCategoryCard.tsx`
- `settingsSummary.ts`
- `ServerConfig.tsx`
- `AccountSettingsSection.tsx`
- `ProviderListSection.tsx`
- `ProviderEditorLayout.tsx`
- `ProviderForm.tsx`
- `ThemeSettings.tsx`
- `MemorySection.tsx`
- `DebugLogging.tsx`

当前这一组正在向 iOS `Settings.app` 风格靠拢。

#### `components/common/`

- `Sidebar.tsx`：通用侧边栏容器，通过 `side: 'left' | 'right'` 参数控制方向（含手势开/关支持）
- `ContentPanGestureArea.tsx`：页面级横向 pan 手势识别区（左右滑切换左右侧边栏，纵向手势失败让出）
- `EmptyState.tsx`
- `ApprovalModal.tsx`
- `StatusBadge.tsx`

## 主要页面功能

### `Sebastian` 页

- 主对话入口
- 支持新建/切换 Session
- 显示消息历史与流式响应
- 输入框支持发送与中断

### `Sub-Agents` 页

- 直接展示当前可用的 Sub-Agent 列表
- 无真实数据时可用 mock 数据验证导航链路
- 点击 agent 后进入二级 Session 列表页
- Session 列表页右下角的 `NewChatFAB` 触发懒创建：首次发送内容时才通过 `POST /api/v1/agents/{type}/sessions` 在后端创建 session

### `Session 详情页`

- 显示 sub-agent session 的对话消息（顶部任务/消息切换栏已移除）
- 任务进度通过左滑唤出的 Todo 侧边栏查看
- 支持继续向 session 发送内容
- 当前也支持 mock 数据用于 UI 验证

### `设置` 页

- 设置首页展示 4 张分类状态卡：连接与账户 / 模型与 Provider / 外观 / 高级
- 首页仅保留少量快捷操作：测试连接、退出登录
- 各分类进入后在独立详细页中完成编辑
- `no_llm_provider` 错误横幅会直接引导到 `/settings/providers`

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改页面路由或 Stack 导航结构 | `app/_layout.tsx` |
| 改主对话体验（消息/流式/输入） | `app/index.tsx`、`src/components/chat/`、`src/components/conversation/` |
| 改左侧边栏内容（功能入口/历史列表/新对话按钮） | `src/components/chat/AppSidebar.tsx` |
| 改右侧 Todo 侧边栏内容 | `src/components/chat/TodoSidebar.tsx` |
| 改侧边栏容器或手势（左右通用） | `src/components/common/Sidebar.tsx`（`side` prop） |
| 改页面级横向 pan 手势识别 | `src/components/common/ContentPanGestureArea.tsx` |
| 改 todos REST 请求封装 | `src/api/todos.ts` |
| 改 todos React Query 装配 | `src/hooks/useSessionTodos.ts` |
| 改 Sub-Agent 浏览链路 | `app/subagents/`、`src/components/subagents/` |
| 改设置首页状态面板 | `app/settings/index.tsx`、`src/components/settings/SettingsCategoryCard.tsx`、`src/components/settings/settingsSummary.ts` |
| 改连接与账户页 | `app/settings/connection.tsx`、`src/components/settings/ServerConfig.tsx`、`src/components/settings/AccountSettingsSection.tsx` |
| 改模型与 Provider 列表/新增/编辑 | `app/settings/providers/`、`src/components/settings/ProviderListSection.tsx`、`src/components/settings/ProviderForm.tsx` |
| 改外观页 | `app/settings/appearance.tsx`、`src/components/settings/ThemeSettings.tsx` |
| 改高级页 | `app/settings/advanced.tsx`、`src/components/settings/MemorySection.tsx`、`src/components/settings/DebugLogging.tsx` |
| 改 API 请求或响应处理 | `src/api/` |
| 改本地 UI 状态 | `src/store/` |
| 改 React Query 数据装配 | `src/hooks/` |
| 改 SSE 订阅逻辑 | `src/api/sse.ts`、`src/hooks/useSSE.ts` |
| 改通用组件（侧边栏、审批弹窗等） | `src/components/common/` |
| 修改输入框行为/样式 | `src/components/composer/index.tsx` |
| 修改发送/停止按钮 | `src/components/composer/SendButton.tsx` |
| 修改思考按钮（按 capability 渲染不同形态） | `src/components/composer/ThinkButton.tsx` |
| 修改思考档位选择器弹窗 | `src/components/composer/EffortPicker.tsx` |
| 修改思考档位 session 状态（effort + lastUserChoice） | `src/store/composer.ts` |
| 修改当前 provider thinking_capability 同步 / clamp 逻辑 | `src/api/llm.ts` 的 `syncCurrentThinkingCapability` |
| 修改 LLM Provider 设置表单（含 thinking_capability 选择） | `src/components/settings/ProviderForm.tsx` |

## 常用命令

```bash
# 安装依赖
npm install --legacy-peer-deps

# 启动 Metro（日常热更新开发）
npx expo start

# 完整构建并安装到设备/模拟器
npx expo run:android

# 类型检查
npx tsc --noEmit
```

## 键盘适配方案

> 技术选型：`react-native-keyboard-controller@1.21.4`（行业标准，WhatsApp/Telegram 同款方案）

### 为什么选这个方案

React Native 内置的 `KeyboardAvoidingView` 在 Android `edgeToEdgeEnabled: true` + Reanimated 4.x 环境下存在已知冲突（`useAnimatedKeyboard` 被废弃，无法可靠获取键盘高度），导致动画抖动和布局错位。`react-native-keyboard-controller` 通过原生层帧同步解决这一问题。

### 架构概览

```
SafeAreaView edges={['bottom']}           ← 仅处理底部安全区
├── Header（paddingTop: insets.top）       ← 顶部安全区手动处理
└── KeyboardGestureArea                    ← 滑动收起键盘手势区
    ├── ConversationView
    │   └── FlatList
    │       └── renderScrollComponent={KeyboardChatScrollView}
    │           ↑ 自动通过 contentInset 调整滚动区域，无需手动 paddingBottom
    └── KeyboardStickyView offset={{ opened: insets.bottom }}
        └── Composer（普通 View，无键盘感知）
            ↑ 原生帧同步跟随键盘，无 Yoga 重排抖动
```

### 关键参数

| 参数 | 位置 | 作用 |
|---|---|---|
| `KeyboardProvider` | `app/_layout.tsx` | 全局根 Provider，必须存在 |
| `stickyOffset = { opened: insets.bottom }` | 页面层 | 补偿 SafeAreaView 底部 padding，防止键盘打开时双重叠加 |
| `KeyboardChatScrollView offset={insets.bottom}` | `renderScrollComponent` | 与 stickyOffset 保持一致，确保滚动区域对齐 |
| `LIST_BOTTOM_PADDING = COMPOSER_DEFAULT_HEIGHT + 36` | `ConversationView.tsx` | Composer 静止时的消息列表底部留白 |

### 应用范围

此方案应用于所有包含 Composer 的聊天页面：
- `app/index.tsx`（主对话页）
- `app/subagents/session/[id].tsx`（Sub-Agent Session 详情页）

---

## 联调约定

- 模拟器访问宿主机 gateway 用 `http://10.0.2.2:8823`
- 真机用局域网 IP：`http://192.168.x.x:8823`
- 前端是服务端状态的镜像，不应自行发明持久化真相
- API / SSE 变更时，需同步检查 `sebastian/gateway/` 与相关 spec

## 维护约定

- 页面信息架构变化时，同步更新本 README 与 Android app spec
- 组件优先按领域归类，不把 chat / settings / subagents 混在一起
- mock 数据只用于 UI 验证，不应悄悄演变成业务 fallback

---

> 修改目录结构或页面导航后，请同步更新本 README 中的目录树与修改导航表。
