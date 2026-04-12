# Mobile Settings Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复本次移动端设置页重构在 review 中暴露出的状态一致性、Provider 状态机、sub-agent 会话工作态以及 README 同步问题。

**Architecture:** 沿用现有设置页重构结构，不重做信息架构，只修正状态真相、缓存失效、路由直达加载和会话工作态判断。把与服务器/登录态强绑定的缓存显式重置，把 Provider 未初始化/加载/失败/空态区分清楚，并让错误引导与 README 完全对齐。

**Tech Stack:** Expo Router 6、React Native 0.81、TypeScript 5.9、Zustand、React Query、Vitest

---

## File Map

### Modify

- `ui/mobile/src/store/settings.ts` — 增加 server-scoped reset 能力，修复 connectionStatus / hydration 行为
- `ui/mobile/src/store/llmProviders.ts` — 明确 `initialized/loading/error` 状态机并提供 reset
- `ui/mobile/src/store/session.ts` — 增加 reset，避免切换 server / logout 后残留旧会话索引
- `ui/mobile/src/store/conversation.ts` — 视需要增加 reset，清除旧 banner / 会话态
- `ui/mobile/src/store/composer.ts` — 视需要增加 reset，避免旧 provider capability 影响新 server
- `ui/mobile/src/api/client.ts` — 401 时统一清理 server-bound 本地状态
- `ui/mobile/src/components/settings/ServerConfig.tsx` — 输入框跟随 hydration，同步切换 server 后的本地状态清理
- `ui/mobile/src/components/settings/ProviderListSection.tsx` — 删除失败处理
- `ui/mobile/app/settings/index.tsx` — 修正 Models 卡片未登录/未初始化摘要
- `ui/mobile/app/settings/providers/index.tsx` — Provider 列表页拉取策略
- `ui/mobile/app/settings/providers/[providerId].tsx` — 直达编辑页时的 fetch / loading / error / not-found 分流
- `ui/mobile/app/subagents/session/[id].tsx` — 使用真实 active turn 状态控制 composer working / stop
- `ui/mobile/README.md` — 补齐 settings 相关组件清单
- `ui/mobile/src/components/settings/README.md` — 补齐 `SettingToggleRow.tsx`、`ThemeSettings.tsx`、`DebugLogging.tsx`

### Test

- `ui/mobile/src/components/settings/settingsSummary.test.ts` — 补未登录和未初始化摘要行为
- `ui/mobile/src/store/` 下新增纯逻辑测试文件（如有必要）— 覆盖 reset / initialized 状态机

---

### Task 1: 修正 server-bound 状态缓存与 hydration

**Files:**
- Modify: `ui/mobile/src/store/settings.ts`
- Modify: `ui/mobile/src/store/llmProviders.ts`
- Modify: `ui/mobile/src/store/session.ts`
- Modify: `ui/mobile/src/store/conversation.ts`
- Modify: `ui/mobile/src/store/composer.ts`
- Modify: `ui/mobile/src/api/client.ts`
- Modify: `ui/mobile/src/components/settings/ServerConfig.tsx`

- [ ] **Step 1: 写失败中的 store/reset 测试**

为纯逻辑状态增加最小测试，覆盖：

- logout/401 后 Provider 缓存被清空
- 切换 `serverUrl` 后 `initialized` 被重置
- `ServerConfig` hydration 后不会用空输入覆盖已存 URL

- [ ] **Step 2: 运行测试确认先红**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npm test
```

Expected: 新增测试先失败，原因是缺少 reset/同步逻辑。

- [ ] **Step 3: 为 server-bound store 增加 reset 能力**

要求：

- `settings.ts` 能在 server 切换时重置 `connectionStatus`、`currentThinkingCapability`
- `llmProviders.ts` 增加 `reset()`，清空 `providers/loading/error/initialized`
- `session.ts` 增加 `reset()`，清空 `sessionIndex/currentSessionId/draftSession/streamingMessage`
- `conversation.ts` 清空所有会话和 banner
- `composer.ts` 至少清除 session 级 effort 映射，不保留受旧 provider capability 影响的脏状态

- [ ] **Step 4: 将 reset 接入真实流程**

要求：

- `api/client.ts` 的 401 分支调用统一 reset
- `ServerConfig.tsx` 在 `serverUrl` 变更保存前后触发 reset，并且输入框跟随 hydration 更新
- 不能把“切换 server”实现成仅改 `baseURL` 而保留旧缓存

- [ ] **Step 5: 跑测试与类型检查**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npm test
npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add ui/mobile/src/store/settings.ts ui/mobile/src/store/llmProviders.ts ui/mobile/src/store/session.ts ui/mobile/src/store/conversation.ts ui/mobile/src/store/composer.ts ui/mobile/src/api/client.ts ui/mobile/src/components/settings/ServerConfig.tsx
git commit -m "fix(mobile): 重置与服务器绑定的本地状态缓存"
```

---

### Task 2: 修正 Provider 状态机与设置首页 Models 卡片

**Files:**
- Modify: `ui/mobile/src/components/settings/settingsSummary.ts`
- Modify: `ui/mobile/src/components/settings/settingsSummary.test.ts`
- Modify: `ui/mobile/app/settings/index.tsx`
- Modify: `ui/mobile/app/settings/providers/index.tsx`
- Modify: `ui/mobile/app/settings/providers/[providerId].tsx`
- Modify: `ui/mobile/src/components/settings/ProviderListSection.tsx`

- [ ] **Step 1: 写失败中的 Provider 状态机测试**

补测试覆盖：

- 未登录时 Models 卡片不能永远显示“正在加载”
- `initialized=false` 与 `isLoading=true` 不是同一个终态
- 编辑页拉取失败时显示错误态，而不是“未找到 Provider”

- [ ] **Step 2: 运行测试确认先红**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npm test -- src/components/settings/settingsSummary.test.ts
```

- [ ] **Step 3: 修正首页 Models 卡片摘要规则**

要求：

- 未登录时不触发 provider 拉取，也不能停在伪 loading
- `initialized=false` 只代表尚未初始化，不应在未登录场景伪装成 loading
- 加载失败要有明确错误摘要

- [ ] **Step 4: 修正 Provider 列表页与编辑页状态机**

要求：

- `providers/index.tsx` 在需要时 fetch，但不形成循环重试
- `[providerId].tsx` 直达路由时可以自拉取
- 拉取失败显示 error
- 只有“已初始化 + 非 loading + 无 error + 无该 id”时才显示 not found

- [ ] **Step 5: 补删除失败处理**

`ProviderListSection.tsx` 删除失败时必须给出错误反馈，不能留下未处理 rejection。

- [ ] **Step 6: 跑测试与类型检查**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npm test -- src/components/settings/settingsSummary.test.ts
npx tsc --noEmit
```

- [ ] **Step 7: Commit**

```bash
git add ui/mobile/src/components/settings/settingsSummary.ts ui/mobile/src/components/settings/settingsSummary.test.ts ui/mobile/app/settings/index.tsx ui/mobile/app/settings/providers/index.tsx ui/mobile/app/settings/providers/[providerId].tsx ui/mobile/src/components/settings/ProviderListSection.tsx
git commit -m "fix(mobile): 修正 Provider 摘要与编辑页状态机"
```

---

### Task 3: 修正 sub-agent 会话 working / stop 行为

**Files:**
- Modify: `ui/mobile/app/subagents/session/[id].tsx`
- Verify: `ui/mobile/src/store/conversation.ts`
- Verify: `ui/mobile/src/api/turns.ts`

- [ ] **Step 1: 写失败中的会话工作态测试或最小可验证用例**

如果该页没有现成测试基础，至少先写出明确的手工/逻辑验证点，确保实现不是拍脑袋改：

- turn 流式进行中时 composer 仍处于 working
- 不能在同一 active turn 未完成时再次发送
- stop 行为使用真实取消链路，而不是空函数

- [ ] **Step 2: 让页面使用真实 active turn 状态**

要求：

- 不再使用本地 `sending` 作为唯一 working 真相
- `isWorking` 绑定 `useConversationStore` 中该 session 的 `activeTurn`
- `onStop` 走真实取消逻辑，不能保留空实现

- [ ] **Step 3: 验证 sub-agent 发送/停止链路**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx tsc --noEmit
```

并手工确认：

- 流式返回期间无法再次发送
- stop 可点击且会调用取消

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/app/subagents/session/[id].tsx
git commit -m "fix(mobile): 修正 sub-agent 会话的工作态与停止行为"
```

---

### Task 4: 同步 README 与导航文档

**Files:**
- Modify: `ui/mobile/README.md`
- Modify: `ui/mobile/src/components/settings/README.md`

- [ ] **Step 1: 补齐 settings 组件树**

要求：

- `ui/mobile/README.md` 补上 `ThemeSettings.tsx`、`DebugLogging.tsx`
- `components/settings/README.md` 补上 `SettingToggleRow.tsx`

- [ ] **Step 2: 验证导航说明与真实文件一致**

手工核对：

- settings 路由树
- settings 组件目录
- 修改导航表

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/README.md ui/mobile/src/components/settings/README.md
git commit -m "docs(mobile): 同步 review 修复后的 settings 文档导航"
```

---

### Task 5: 全量验证

**Files:**
- No code changes expected

- [ ] **Step 1: 运行测试**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npm test
npx tsc --noEmit
```

- [ ] **Step 2: 执行手工验证**

至少验证：

1. 未登录时 Models 卡片不是永久“正在加载”
2. 切换 `serverUrl` 后首页和 Provider 页不会显示旧服务器数据
3. logout / 401 后不会保留旧 Provider 与旧 thinking capability
4. 直达 `/settings/providers/[providerId]` 时 loading / error / not-found 分流正确
5. sub-agent 会话流式返回期间无法重复发送，Stop 可用
6. `no_llm_provider` 横幅仍然正确跳到 `/settings/providers`

- [ ] **Step 3: 若发现问题，先修再结束**

任何失败项都必须修复后重新验证，不能带着已知逻辑问题结束。

---

## Self-Review

- 该计划只覆盖本轮 review 暴露的问题，没有扩展新功能。
- 任务拆分按文件写集分离：缓存/状态、Provider 状态机、sub-agent working、README，可由不同子代理并行推进。
- 高风险逻辑问题都落到了明确文件：server-bound reset、Provider 初始化状态、sub-agent active turn。
