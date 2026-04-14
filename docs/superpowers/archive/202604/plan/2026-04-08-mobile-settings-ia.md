# Mobile Settings 信息架构重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将移动端设置页从单页长表单重构为“状态面板首页 + 分类详细页 + Provider 独立编辑流”的清晰信息架构。

**Architecture:** 保持现有 Expo Router、Zustand、SecureStore 和现有 API/store 真相层不变，只重组设置相关路由、组件边界与首页摘要规则。首页只展示状态与少量快捷操作，复杂编辑逻辑迁入分类页；Provider 保留列表页与新增/编辑页分离的三级编辑流。

**Tech Stack:** Expo Router 6、React Native 0.81、TypeScript 5.9、Zustand、expo-secure-store、Vitest（新增，用于纯逻辑单测）

---

## File Map

### Create

- `ui/mobile/app/settings/connection.tsx` — 连接与账户详细页路由
- `ui/mobile/app/settings/appearance.tsx` — 外观详细页路由
- `ui/mobile/app/settings/advanced.tsx` — 高级详细页路由
- `ui/mobile/app/settings/providers/index.tsx` — Provider 列表页路由
- `ui/mobile/app/settings/providers/new.tsx` — Provider 新增页路由
- `ui/mobile/app/settings/providers/[providerId].tsx` — Provider 编辑页路由
- `ui/mobile/src/components/settings/SettingsCategoryCard.tsx` — 首页状态卡组件
- `ui/mobile/src/components/settings/SettingsScreenLayout.tsx` — 设置页通用容器（标题、返回、滚动布局）
- `ui/mobile/src/components/settings/AccountSettingsSection.tsx` — Owner 登录/登出区域
- `ui/mobile/src/components/settings/ProviderListSection.tsx` — Provider 列表与空状态
- `ui/mobile/src/components/settings/ProviderForm.tsx` — Provider 新增/编辑表单
- `ui/mobile/src/components/settings/settingsSummary.ts` — 首页摘要规则与文案计算
- `ui/mobile/src/components/settings/settingsSummary.test.ts` — 摘要状态单测
- `ui/mobile/vitest.config.ts` — Vitest 配置

### Modify

- `ui/mobile/app/settings/index.tsx` — 从长表单页改为状态面板首页
- `ui/mobile/package.json` — 增加测试脚本与 Vitest 依赖
- `ui/mobile/package-lock.json` — 锁定新增测试依赖版本
- `ui/mobile/src/components/settings/ServerConfig.tsx` — 拆成可复用的连接区块
- `ui/mobile/src/components/settings/ThemeSettings.tsx` — 迁入独立外观页时收敛为区块组件
- `ui/mobile/src/components/settings/MemorySection.tsx` — 明确为不可点击占位项
- `ui/mobile/src/components/settings/DebugLogging.tsx` — 迁入高级页并保留登录态控制
- `ui/mobile/src/components/settings/LLMProviderConfig.tsx` — 拆分遗留逻辑到列表/表单组件后删除
- `ui/mobile/src/store/settings.ts` — 增加共享的连接测试状态
- `ui/mobile/src/store/llmProviders.ts` — 增加 Provider 列表初始化状态
- `ui/mobile/app/index.tsx` — 首页错误横幅改跳转到新的 Provider 页
- `ui/mobile/app/subagents/session/[id].tsx` — Sub-Agent 会话错误横幅改跳转到新的 Provider 页
- `ui/mobile/src/components/conversation/ErrorBanner.tsx` — 更新无 Provider 错误的动作文案
- `ui/mobile/src/components/settings/README.md` — 同步组件职责与修改导航
- `ui/mobile/README.md` — 同步设置页路由树与修改导航

### Verify

- `ui/mobile/app/_layout.tsx` — 确认新增 settings 子路由不需要额外 Stack 配置
- `ui/mobile/src/store/settings.ts` — 确认首页摘要直接读取现有 store 字段
- `ui/mobile/src/store/llmProviders.ts` — 确认 Provider 列表状态继续作为详细页真相

---

### Task 1: 建立设置摘要规则与最小测试基础

**Files:**
- Create: `ui/mobile/src/components/settings/settingsSummary.ts`
- Create: `ui/mobile/src/components/settings/settingsSummary.test.ts`
- Create: `ui/mobile/vitest.config.ts`
- Modify: `ui/mobile/package.json`
- Modify: `ui/mobile/package-lock.json`

- [ ] **Step 1: 为移动端添加最小 Vitest 基础**

在 `ui/mobile/package.json` 增加脚本与开发依赖：

```json
{
  "scripts": {
    "test": "vitest run"
  },
  "devDependencies": {
    "vitest": "^3.2.4"
  }
}
```

不要引入 React Native 组件测试库；本次只测试纯 TypeScript 摘要逻辑，避免测试基础设施超出需求。

- [ ] **Step 2: 抽出首页卡片摘要规则**

在 `ui/mobile/src/components/settings/settingsSummary.ts` 新建纯函数，至少包含：

```ts
export type ConnectionStatus = 'idle' | 'ok' | 'fail';

export function getConnectionSummary(input: {
  serverUrl: string;
  connectionStatus: ConnectionStatus;
  isLoggedIn: boolean;
}): { title: string; subtitle: string } { /* ... */ }

export function getProviderSummary(input: {
  providers: Array<{ provider_type: string; model: string; is_default: boolean }>;
  isLoading: boolean;
  initialized: boolean;
  error: string | null;
}): { title: string; subtitle: string } { /* ... */ }

export function getAppearanceSummary(input: {
  themeMode: 'system' | 'light' | 'dark';
  isDark: boolean;
}): { title: string; subtitle: string } { /* ... */ }

export function getAdvancedSummary(input: {
  isLoggedIn: boolean;
}): { title: string; subtitle: string } { /* ... */ }
```

要求严格对齐 spec：

- connection：`serverUrl` 必须来自状态，不可硬编码示例地址
- provider 加载态：`正在加载 / 正在加载 Provider…`
- provider 未初始化态：首屏不可误判为 `未配置`
- provider 空状态：`未配置 / 尚未添加 Provider`
- provider 无默认项：`未设默认 / N 个 Provider · 请选择默认项`
- advanced 未登录：`1 项设置 / Memory`

- [ ] **Step 3: 写失败中的摘要单测**

在 `ui/mobile/src/components/settings/settingsSummary.test.ts` 覆盖至少这些 case：

```ts
it('returns unconfigured provider summary when list is empty', () => {
  expect(getProviderSummary({ providers: [] })).toEqual({
    title: '未配置',
    subtitle: '尚未添加 Provider',
  });
});

it('returns fallback summary when providers exist without default', () => {
  expect(getProviderSummary({
    providers: [{ provider_type: 'anthropic', model: 'claude', is_default: false }],
  })).toEqual({
    title: '未设默认',
    subtitle: '1 个 Provider · 请选择默认项',
  });
});
```

再补：

- provider loading
- provider uninitialized
- connection logged-in / logged-out
- advanced logged-in / logged-out
- appearance `system + isDark=true`

- [ ] **Step 4: 运行测试确认先红后绿**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npm install --legacy-peer-deps
npm test -- settingsSummary.test.ts
```

Expected:

- 第一次在实现前失败
- 完成 `settingsSummary.ts` 后全部通过

- [ ] **Step 5: 提交**

```bash
git add ui/mobile/package.json ui/mobile/package-lock.json ui/mobile/vitest.config.ts ui/mobile/src/components/settings/settingsSummary.ts ui/mobile/src/components/settings/settingsSummary.test.ts
git commit -m "test(mobile): 为设置首页摘要规则补充单测"
```

---

### Task 2: 搭建设置页通用骨架与首页状态卡组件

**Files:**
- Create: `ui/mobile/src/components/settings/SettingsScreenLayout.tsx`
- Create: `ui/mobile/src/components/settings/SettingsCategoryCard.tsx`
- Modify: `ui/mobile/app/settings/index.tsx`
- Modify: `ui/mobile/src/store/settings.ts`
- Modify: `ui/mobile/src/store/llmProviders.ts`

- [ ] **Step 1: 抽出设置页通用容器**

在 `SettingsScreenLayout.tsx` 封装当前首页已有的通用结构：

```tsx
export function SettingsScreenLayout({
  title,
  subtitle,
  children,
  showBack = true,
}: Props) {
  return (
    <ScrollView /* safe area + padding */>
      {showBack ? <BackButton /> : null}
      <View>{/* hero title/subtitle */}</View>
      {children}
    </ScrollView>
  );
}
```

要求：

- 保留当前 `BackButton` 和 safe area 处理方式
- 首页与二级页共用这一层，避免后续多页复制 hero 区域样式

- [ ] **Step 2: 实现首页状态卡组件**

在 `SettingsCategoryCard.tsx` 实现统一卡片：

```tsx
export function SettingsCategoryCard({
  label,
  title,
  subtitle,
  onPress,
  actions,
}: Props) {
  return (
    <TouchableOpacity onPress={onPress}>
      {/* label + title + subtitle + chevron + optional action buttons */}
    </TouchableOpacity>
  );
}
```

要求：

- 卡片本身是入口
- 快捷操作按钮必须阻止冒泡，避免误触整卡跳转
- 样式沿用当前深色设置页风格，但呈现为“状态入口卡”而不是表单卡

- [ ] **Step 3: 将 `settings/index.tsx` 改为状态面板首页**

先在 `ui/mobile/src/store/settings.ts` 增加共享连接状态：

```ts
interface SettingsState {
  connectionStatus: 'idle' | 'ok' | 'fail';
  setConnectionStatus: (status: 'idle' | 'ok' | 'fail') => void;
}
```

处理规则：

- 默认值为 `idle`
- 与 `serverUrl` 一样持久化到 SecureStore
- 首页和连接详情页都从 store 读取，不再依赖页面局部 state

然后重写首页，只保留：

```tsx
<SettingsScreenLayout title="设置" subtitle="查看状态并进入对应分类调整。">
  <SettingsCategoryCard label="Connection" ... />
  <SettingsCategoryCard label="Models" ... />
  <SettingsCategoryCard label="Appearance" ... />
  <SettingsCategoryCard label="Advanced" ... />
</SettingsScreenLayout>
```

首页数据来源：

- connection：`useSettingsStore` 中的 `serverUrl`、登录态、`connectionStatus`
- provider：`useLLMProvidersStore()` 中的 `providers`、`loading`、`error`、`initialized`
- appearance：`themeMode` + `useIsDark()`
- advanced：`jwtToken`

首页快捷操作仅允许：

- `测试连接`
- 已登录时显示 `退出登录`

首页 4 张卡的跳转必须一次性全部接通：

- `连接与账户` → `/settings/connection`
- `模型与 Provider` → `/settings/providers`
- `外观` → `/settings/appearance`
- `高级` → `/settings/advanced`

首页 Provider 卡片文案规则额外要求：

- `initialized === false` 时显示 `正在加载 / 正在加载 Provider…`
- `loading === true` 时继续显示 `正在加载 / 正在加载 Provider…`
- 只有 `initialized === true`、`loading === false` 且 `error === null` 时，才进入空状态/默认项/无默认项判断
- 如 `error` 存在，首页副标题可显示 `Provider 加载失败`

在 `ui/mobile/src/store/llmProviders.ts` 增加：

```ts
interface LLMProvidersState {
  initialized: boolean;
}
```

规则：

- 初始值为 `false`
- 第一次 `fetch()` 成功或失败后都置为 `true`
- 首页 Provider 卡片必须使用它来区分“尚未加载”和“真的为空”

- [ ] **Step 3.5: 给首页快捷操作接上真实行为**

在 `settings/index.tsx` 为 `SettingsCategoryCard.actions` 明确接线：

- `测试连接`：复用 `ServerConfig` 的测试逻辑，更新 `connectionStatus`
- `退出登录`：直接调用现有 `logout()` + `setJwtToken(null)`

要求：

- action 点击不能触发整卡导航
- 未登录时不显示 `退出登录`
- 这一步是必须项，不能只留组件扩展点不接行为

- [ ] **Step 4: 类型检查**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx tsc --noEmit
```

Expected: no new TypeScript errors.

- [ ] **Step 5: 提交**

```bash
git add ui/mobile/app/settings/index.tsx ui/mobile/src/components/settings/SettingsScreenLayout.tsx ui/mobile/src/components/settings/SettingsCategoryCard.tsx ui/mobile/src/store/settings.ts ui/mobile/src/store/llmProviders.ts
git commit -m "feat(mobile): 设置首页改为状态面板"
```

---

### Task 3: 拆出连接与账户详细页

**Files:**
- Create: `ui/mobile/app/settings/connection.tsx`
- Create: `ui/mobile/src/components/settings/AccountSettingsSection.tsx`
- Modify: `ui/mobile/src/components/settings/ServerConfig.tsx`
- Modify: `ui/mobile/src/store/settings.ts`
- Modify: `ui/mobile/app/settings/index.tsx`

- [ ] **Step 1: 将账户登录逻辑从首页迁移到独立组件**

在 `AccountSettingsSection.tsx` 中移动当前 `index.tsx` 里的登录/登出逻辑：

```tsx
export function AccountSettingsSection() {
  const { jwtToken, setJwtToken } = useSettingsStore();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  // handleLogin / handleLogout
}
```

要求：

- 行为保持不变
- 仅迁移职责，不顺手扩展账户功能

- [ ] **Step 2: 收敛 `ServerConfig.tsx` 为可嵌入连接区块**

保留 `Server URL`、状态显示、`保存并测试`，但移除“它一定在首页”的假设。必要时增加可选 props：

```tsx
export function ServerConfig({
  status,
  onStatusChange,
}: {
  status?: ConnectionStatus;
  onStatusChange?: (status: ConnectionStatus) => void;
}) { /* ... */ }
```

这样首页和连接详情页都能复用同一连接表单，而不是复制网络逻辑。

实现时优先直接接入 `useSettingsStore().connectionStatus` 与 `setConnectionStatus()`，不要继续保留局部 `useState('idle')` 作为连接状态真相。

- [ ] **Step 3: 新建 `settings/connection.tsx`**

页面结构：

```tsx
<SettingsScreenLayout title="连接与账户" subtitle="配置 Server 连接并管理 Owner 登录。">
  <ServerConfig />
  <AccountSettingsSection />
</SettingsScreenLayout>
```

首页卡片点击后跳转到这个页面。

- [ ] **Step 4: 验证连接与账户链路**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx tsc --noEmit
```

然后手工检查：

1. 首页进入“连接与账户”
2. Server URL 可保存并测试
3. 未登录时可输入密码登录
4. 已登录时可退出登录

- [ ] **Step 5: 提交**

```bash
git add ui/mobile/app/settings/connection.tsx ui/mobile/src/components/settings/AccountSettingsSection.tsx ui/mobile/src/components/settings/ServerConfig.tsx ui/mobile/src/store/settings.ts ui/mobile/app/settings/index.tsx
git commit -m "feat(mobile): 拆出连接与账户设置页"
```

---

### Task 4: 拆出外观与高级详细页

**Files:**
- Create: `ui/mobile/app/settings/appearance.tsx`
- Create: `ui/mobile/app/settings/advanced.tsx`
- Modify: `ui/mobile/src/components/settings/ThemeSettings.tsx`
- Modify: `ui/mobile/src/components/settings/MemorySection.tsx`
- Modify: `ui/mobile/src/components/settings/DebugLogging.tsx`

- [ ] **Step 1: 新建外观页**

在 `settings/appearance.tsx` 中直接复用 `ThemeSettings`：

```tsx
<SettingsScreenLayout title="外观" subtitle="调整主题模式与显示风格。">
  <ThemeSettings />
</SettingsScreenLayout>
```

不要在这一轮新增字体、密度等扩展项。

- [ ] **Step 2: 明确 Memory 为不可点击占位项**

在 `MemorySection.tsx` 中保留当前“即将推出”表现，但补齐视觉暗示：

```tsx
<View accessibilityState={{ disabled: true }}>
  <Text>Memory 管理</Text>
  <Text>即将推出</Text>
</View>
```

要求：

- 不出现箭头
- 不包裹 `TouchableOpacity`
- 不产生新路由

- [ ] **Step 3: 新建高级页**

在 `settings/advanced.tsx` 中组合：

```tsx
<SettingsScreenLayout title="高级" subtitle="低频设置、调试项与预留功能。">
  <MemorySection />
  <DebugLogging />
</SettingsScreenLayout>
```

保留 `DebugLogging` 现有 `jwtToken` 控制，不做权限逻辑改写。

- [ ] **Step 4: 类型检查**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: 提交**

```bash
git add ui/mobile/app/settings/appearance.tsx ui/mobile/app/settings/advanced.tsx ui/mobile/src/components/settings/ThemeSettings.tsx ui/mobile/src/components/settings/MemorySection.tsx ui/mobile/src/components/settings/DebugLogging.tsx
git commit -m "feat(mobile): 拆出外观与高级设置页"
```

---

### Task 5: 将 Provider 管理拆成列表页与独立表单页

**Files:**
- Create: `ui/mobile/app/settings/providers/index.tsx`
- Create: `ui/mobile/app/settings/providers/new.tsx`
- Create: `ui/mobile/app/settings/providers/[providerId].tsx`
- Create: `ui/mobile/src/components/settings/ProviderListSection.tsx`
- Create: `ui/mobile/src/components/settings/ProviderForm.tsx`
- Modify: `ui/mobile/src/components/settings/LLMProviderConfig.tsx`
- Modify: `ui/mobile/src/store/llmProviders.ts`

- [ ] **Step 1: 从 `LLMProviderConfig.tsx` 提取 Provider 表单**

把当前文件里的 `ProviderForm` 提取到独立文件 `ProviderForm.tsx`，保留原有字段：

```tsx
export function ProviderForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: LLMProvider;
  onSave: (data: LLMProviderCreate) => Promise<void>;
  onCancel: () => void;
}) { /* existing form fields */ }
```

这一轮不要改字段集合或 thinking capability 逻辑。

- [ ] **Step 2: 提取 Provider 列表与空状态区块**

在 `ProviderListSection.tsx` 中承载：

- 列表渲染
- 默认项标识
- 删除按钮
- loading 状态
- error 状态
- 空状态文案
- “添加 Provider” 按钮

空状态必须对齐 spec：

```tsx
<Text>尚未配置模型 Provider</Text>
<TouchableOpacity onPress={() => router.push('/settings/providers/new')}>
  <Text>添加 Provider</Text>
</TouchableOpacity>
```

同时保留现有 `LLMProviderConfig.tsx` 的状态语义：

```tsx
if (loading) return <ActivityIndicator />;
if (error) return <Text>{error}</Text>;
```

只有在 `loading === false` 且没有 `error` 且 `providers.length === 0` 时，才允许展示空状态。

- [ ] **Step 3: 新建 Provider 路由**

`settings/providers/index.tsx`：

```tsx
<SettingsScreenLayout title="模型与 Provider" subtitle="管理默认模型与各 Provider 配置。">
  <ProviderListSection />
</SettingsScreenLayout>
```

并将原先位于 `LLMProviderConfig.tsx` 内的拉取责任迁移到这里：

```tsx
const { jwtToken } = useSettingsStore();
const { fetch } = useLLMProvidersStore();

useEffect(() => {
  if (jwtToken) {
    void fetch();
  }
}, [jwtToken, fetch]);
```

`settings/providers/new.tsx`：

```tsx
<SettingsScreenLayout title="添加 Provider" subtitle="新增一个可用模型提供商。">
  <ProviderForm onSave={handleCreate} onCancel={router.back} />
</SettingsScreenLayout>
```

`settings/providers/[providerId].tsx`：

```tsx
const { jwtToken } = useSettingsStore();
const { providers, initialized, loading, fetch } = useLLMProvidersStore();

useEffect(() => {
  if (jwtToken && (!initialized || !providers.length)) {
    void fetch();
  }
}, [jwtToken, initialized, providers.length, fetch]);

const provider = providers.find((p) => p.id === providerId);
if (!initialized || loading) { /* show loading */ }
if (initialized && !loading && !provider) { /* show not found state */ }
<ProviderForm initial={provider} onSave={handleUpdate} onCancel={router.back} />
```

约束：

- 新增必须走 `new.tsx`
- 编辑必须走 `[providerId].tsx`
- 不使用特殊 id 混用两种语义
- `/settings/providers/index.tsx` 与 `/settings/providers/[providerId].tsx` 都必须能在直达路由时自行触发 `fetch()`
- `LLMProviderConfig.tsx` 完成拆分后直接删除，不保留桥接层

- [ ] **Step 4: 让首页 Provider 卡片跳到列表页**

首页“模型与 Provider”卡片点击后跳转 `/settings/providers`。

如果 `jwtToken` 存在但 provider 尚未加载，首页显示稳定占位文案，不允许因 `providers=[]` 误判为空状态。实现时优先：

```ts
const hasFetchedProviders = !loading && !error;
```

在未完成首次 fetch 前，卡片副标题可用 `正在加载 Provider…`。

- [ ] **Step 5: 类型检查 + 关键手工验证**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx tsc --noEmit
```

手工检查：

1. 空状态时能进入新增页
2. 新增后返回列表并显示记录
3. 编辑页能回显已有数据
4. 删除后列表刷新
5. 首页卡片在“无默认项”时显示 `未设默认`

- [ ] **Step 6: 提交**

```bash
git add ui/mobile/app/settings/providers ui/mobile/src/components/settings/ProviderForm.tsx ui/mobile/src/components/settings/ProviderListSection.tsx ui/mobile/src/components/settings/LLMProviderConfig.tsx ui/mobile/src/store/llmProviders.ts ui/mobile/app/settings/index.tsx
git commit -m "feat(mobile): Provider 设置拆分为列表与独立编辑页"
```

- [ ] **Step 7: 删除旧的 `LLMProviderConfig.tsx`**

确认新列表页和新增/编辑页已经覆盖旧组件职责后，删除遗留组件：

```bash
git rm ui/mobile/src/components/settings/LLMProviderConfig.tsx
```

然后再次运行：

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx tsc --noEmit
```

- [ ] **Step 8: 提交删除旧组件**

```bash
git add ui/mobile/src/components/settings/README.md
git commit -m "refactor(mobile): 删除旧版 LLMProviderConfig 组件"
```

---

### Task 6: 清理旧设置页残留并统一导航入口

**Files:**
- Modify: `ui/mobile/app/settings/index.tsx`
- Modify: `ui/mobile/src/components/settings/README.md`
- Modify: `ui/mobile/README.md`

- [ ] **Step 1: 删除首页残留的旧表单逻辑**

检查 `ui/mobile/app/settings/index.tsx`，移除不再属于首页的代码：

- 密码输入与登录错误状态
- Provider 表单显示状态
- 直接嵌入的 `ThemeSettings` / `MemorySection` / `DebugLogging`

首页最终只保留：

- 摘要数据计算
- 跳转逻辑
- 快捷操作

- [ ] **Step 2: 更新 `components/settings/README.md`**

将目录结构同步为新的职责：

```text
settings/
├── SettingsCategoryCard.tsx
├── SettingsScreenLayout.tsx
├── ServerConfig.tsx
├── AccountSettingsSection.tsx
├── ProviderListSection.tsx
├── ProviderForm.tsx
├── settingsSummary.ts
├── ThemeSettings.tsx
├── MemorySection.tsx
└── DebugLogging.tsx
```

并把“修改导航”改成：

- 首页状态卡 → `SettingsCategoryCard.tsx`
- 首页摘要规则 → `settingsSummary.ts`
- Provider 列表 → `ProviderListSection.tsx`
- Provider 编辑表单 → `ProviderForm.tsx`

- [ ] **Step 3: 更新 `ui/mobile/README.md`**

同步页面结构与导航：

```text
app/
└── settings/
    ├── index.tsx
    ├── connection.tsx
    ├── appearance.tsx
    ├── advanced.tsx
    └── providers/
        ├── index.tsx
        ├── new.tsx
        └── [providerId].tsx
```

同时更新“修改导航”表：

- 改设置首页状态面板 → `app/settings/index.tsx`
- 改连接与账户页 → `app/settings/connection.tsx`
- 改 Provider 列表与编辑流 → `app/settings/providers/`
- 改外观页 → `app/settings/appearance.tsx`
- 改高级页 → `app/settings/advanced.tsx`

- [ ] **Step 4: 提交**

```bash
git add ui/mobile/app/settings/index.tsx ui/mobile/src/components/settings/README.md ui/mobile/README.md
git commit -m "docs(mobile): 同步设置页新路由与组件导航"
```

---

### Task 7: 更新无 Provider 错误横幅跳转

**Files:**
- Modify: `ui/mobile/app/index.tsx`
- Modify: `ui/mobile/app/subagents/session/[id].tsx`
- Modify: `ui/mobile/src/components/conversation/ErrorBanner.tsx`

- [ ] **Step 1: 更新主会话页横幅跳转**

在 `ui/mobile/app/index.tsx` 中区分 banner 类型：

```tsx
<ErrorBanner
  message={currentBanner.message}
  onAction={() =>
    currentBanner.code === 'no_llm_provider'
      ? router.push('/settings/providers')
      : router.push('/settings')
  }
/>
```

`ConversationView` 的 `onBannerAction` 也做同样处理，避免空会话和非空会话行为不一致。

- [ ] **Step 2: 更新 Sub-Agent 会话页横幅跳转**

在 `ui/mobile/app/subagents/session/[id].tsx` 中同样按 `banner.code` 分流：

```tsx
onBannerAction={() =>
  banner?.code === 'no_llm_provider'
    ? router.push('/settings/providers')
    : router.push('/settings')
}
```

- [ ] **Step 3: 更新错误横幅按钮文案**

在 `ui/mobile/src/components/conversation/ErrorBanner.tsx` 中补充可配置 action 文案，至少支持：

```tsx
<ErrorBanner
  message={message}
  actionLabel={code === 'no_llm_provider' ? '前往模型与 Provider' : '前往设置'}
  onAction={...}
/>
```

要求：

- `no_llm_provider` 时，按钮文案和路由都指向新的 Provider 页面
- 不改动其他 banner 的默认去向

- [ ] **Step 4: 类型检查**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx tsc --noEmit
```

- [ ] **Step 5: 提交**

```bash
git add ui/mobile/app/index.tsx ui/mobile/app/subagents/session/[id].tsx ui/mobile/src/components/conversation/ErrorBanner.tsx
git commit -m "fix(mobile): 无 Provider 错误跳转到新的模型设置页"
```

---

### Task 8: 完整验证

**Files:**
- No code changes expected

- [ ] **Step 1: 运行摘要单测**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npm test -- settingsSummary.test.ts
```

Expected: PASS

- [ ] **Step 2: 运行类型检查**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx tsc --noEmit
```

Expected: PASS

- [ ] **Step 3: 启动后端**

Run:

```bash
cd /Users/ericw/work/code/ai/sebastian
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload
```

Expected: gateway 正常启动，无 settings 相关错误。

- [ ] **Step 4: 启动 Android 模拟器与 App**

Run:

```bash
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -no-snapshot-load &
~/Library/Android/sdk/platform-tools/adb wait-for-device shell getprop sys.boot_completed
cd /Users/ericw/work/code/ai/sebastian/ui/mobile
npx expo run:android
```

- [ ] **Step 5: 执行手工验收清单**

逐项确认：

1. [ ] 设置首页显示 4 张卡：连接与账户 / 模型与 Provider / 外观 / 高级
2. [ ] 首页点击各卡进入对应详细页
3. [ ] 首页只存在 `测试连接` 与 `退出登录` 两类快捷操作
4. [ ] 连接卡摘要使用当前 `serverUrl`，而不是硬编码示例地址
5. [ ] 未登录时高级卡摘要为 `1 项设置 / Memory`
6. [ ] 已登录时高级卡摘要为 `2 项设置 / Memory · 调试日志`
7. [ ] Provider 为空时首页显示 `未配置 / 尚未添加 Provider`
8. [ ] Provider 非空但无默认项时首页显示 `未设默认`
9. [ ] Provider 新增、编辑、删除链路完整可用
10. [ ] Memory 在高级页表现为不可点击的“即将推出”占位项
11. [ ] 外观切换后首页摘要与实际主题一致
12. [ ] 未配置 Provider 时发送消息，错误横幅按钮跳转到 `/settings/providers`
13. [ ] `no_llm_provider` 横幅按钮文案为“前往模型与 Provider”

- [ ] **Step 6: 如有失败项，先修复再补提交**

若任何一项失败，不要带着已知问题结束；创建额外原子提交修复，再重新执行对应验证步骤。

---

## Self-Review

- Spec 中要求的 4 张首页卡、2 个快捷操作、4 个二级页、Provider 独立新增/编辑流，均已映射到具体任务。
- Spec 中要求的首页状态矩阵，已集中到 `settingsSummary.ts` 并通过单测固定，避免页面各处临时拼文案。
- `Memory` 的“不可点击占位项”与 README 同步要求，已显式纳入任务。
- 新增的 `no_llm_provider` 错误引导更新，已作为独立任务覆盖主会话与 Sub-Agent 会话两条链路。
- 计划未引入新的业务能力，也没有重写 store / API，仅在测试层新增最小 Vitest 支撑纯逻辑单测，符合最短路径。
