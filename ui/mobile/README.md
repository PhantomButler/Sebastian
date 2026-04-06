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
│   ├── index.tsx
│   ├── (tabs)/       # Tab 导航页面
│   └── subagents/    # Sub-Agent 详情页
├── assets/           # 静态资源
├── src/                  → [src/README.md](src/README.md)
│   ├── api/              → [src/api/README.md](src/api/README.md)（HTTP / SSE 请求封装）
│   ├── components/       → [src/components/README.md](src/components/README.md)（UI 组件，按领域分组）
│   │   ├── chat/         → [chat/README.md](src/components/chat/README.md)
│   │   ├── common/       → [common/README.md](src/components/common/README.md)
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

当前采用 Expo Router 文件系统路由。

```text
app/
├── _layout.tsx
├── index.tsx
├── (tabs)/
│   ├── _layout.tsx
│   ├── chat/index.tsx         # Sebastian 主对话页
│   ├── subagents/index.tsx    # Sub-Agent 列表页
│   └── settings/index.tsx     # 设置页
└── subagents/
    ├── [agentId].tsx          # 某个 Sub-Agent 的 Session 列表
    └── session/[id].tsx       # Session 详情页
```

### 当前导航信息架构

- `Sebastian`
  - 主对话页
  - 使用左侧 sidebar 切换历史 Session
- `Sub-Agents`
  - 先展示 agent 列表
  - 点进某个 agent 后看它的 session 列表
  - 再点 session 进入详情页
- `设置`
  - 配置 server、登录、provider、memory 占位

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

- `ChatSidebar.tsx`：Sebastian 对话历史列表
- `MessageList.tsx` / `MessageBubble.tsx` / `StreamingBubble.tsx`
- `MessageInput.tsx`

#### `components/subagents/`

- `AgentList.tsx`：Sub-Agent 列表
- `SessionList.tsx`：某个 Agent 下的 Session 列表
- `SessionDetailView.tsx`：Session 内任务视图
- `AgentStatusBadge.tsx`

#### `components/settings/`

- `ServerConfig.tsx`
- `LLMProviderConfig.tsx`
- `MemorySection.tsx`

当前这一组正在向 iOS `Settings.app` 风格靠拢。

#### `components/common/`

- `Sidebar.tsx`：通用侧边栏容器
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

### `Session 详情页`

- 显示消息与任务双视图
- 支持继续向 session 发送内容
- 当前也支持 mock 数据用于 UI 验证

### `设置` 页

- 设置 Server URL 并测试连接
- Owner 登录 / 登出
- 配置 LLM Provider 与 API Key
- 预留 Memory 管理入口

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改页面路由或 Tab 导航结构 | `app/_layout.tsx`、`app/(tabs)/_layout.tsx` |
| 改主对话体验（消息/流式/输入） | `app/(tabs)/chat/index.tsx`、`src/components/chat/` |
| 改 Sub-Agent 浏览链路 | `app/(tabs)/subagents/`、`app/subagents/`、`src/components/subagents/` |
| 改设置页 | `app/(tabs)/settings/index.tsx`、`src/components/settings/` |
| 改 API 请求或响应处理 | `src/api/` |
| 改本地 UI 状态 | `src/store/` |
| 改 React Query 数据装配 | `src/hooks/` |
| 改 SSE 订阅逻辑 | `src/api/sse.ts`、`src/hooks/useSSE.ts` |
| 改通用组件（侧边栏、审批弹窗等） | `src/components/common/` |

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

## 联调约定

- 模拟器访问宿主机 gateway 用 `http://10.0.2.2:8000`
- 真机用局域网 IP：`http://192.168.x.x:8000`
- 前端是服务端状态的镜像，不应自行发明持久化真相
- API / SSE 变更时，需同步检查 `sebastian/gateway/` 与相关 spec

## 维护约定

- 页面信息架构变化时，同步更新本 README 与 Android app spec
- 组件优先按领域归类，不把 chat / settings / subagents 混在一起
- mock 数据只用于 UI 验证，不应悄悄演变成业务 fallback

---

> 修改目录结构或页面导航后，请同步更新本 README 中的目录树与修改导航表。
