# Mobile App 日间/夜间主题系统设计文档

**日期**：2026-04-06
**状态**：已确认，待实施

## 背景与目标

为移动端 App 添加日间/夜间主题切换能力，同时修复当前 AI 回复内容颜色与页面背景不匹配的 bug。

**当前问题**：
- `MarkdownContent.tsx` 等 Conversation 组件使用暗色配色（`#d0d0d0` 浅灰文字），但主聊天页面背景是 `#ffffff`（白色），导致 AI 回复文字在白色背景上几乎看不清
- 全 App 40+ 个硬编码颜色值分布在 15+ 个文件中，无主题基础设施

**目标**：
1. 建立 React Context 主题系统，统一管理颜色 token
2. 设置页提供「跟随系统」和「手动切换」两种模式
3. 修复 AI 回复颜色 bug：普通文字跟随主题，代码块保留暗色风格
4. 用户气泡改为 ChatGPT 风格（日间黑底白字，夜间白底黑字）
5. AI 回复移除气泡背景，文字直接渲染在页面上

**不在本次范围内**：
- Sub-Agent 相关组件（`src/components/subagents/`）— 后续独立处理
- `ApprovalModal.tsx` — 后续独立处理

---

## 1. 主题系统架构

### 方案：React Context + 颜色 Token 对象

创建 `ThemeContext`，提供 `useTheme()` hook 返回当前颜色 token 对象。每个组件通过 hook 获取颜色，替换硬编码值。

### 新增文件

- `src/theme/colors.ts` — Light / Dark 两套颜色 token 定义
- `src/theme/ThemeContext.tsx` — ThemeProvider + `useTheme()` hook
- `src/theme/README.md` — 目录说明，链接到父级 `src/README.md`

### 工作机制

```
ThemeProvider (app/_layout.tsx 根部包裹)
  ├── 读取 settings store 的 themeMode
  ├── themeMode === 'system' → 监听 RN useColorScheme()
  ├── themeMode === 'light' / 'dark' → 直接使用用户选择
  └── 通过 Context 向下提供 colors 对象

组件内：
  const colors = useTheme();
  // colors.background, colors.text, colors.userBubbleBg, ...
```

### Token 结构

`colors.ts` 导出类型 `ThemeColors`，包含以下 key：

| Token 名 | 用途 | Light 值 | Dark 值 |
|----------|------|----------|---------|
| `background` | 主页面背景 | `#FFFFFF` | `#1C1C1E` |
| `secondaryBackground` | 卡片、侧边栏、输入框背景 | `#F9F9F9` | `#2C2C2E` |
| `settingsBackground` | 设置页背景 | `#F2F2F7` | `#000000` |
| `text` | 主文字 | `#111111` | `#F5F5F5` |
| `textSecondary` | 次要文字 | `#8E8E93` | `#8E8E93` |
| `textMuted` | 更弱的文字（时间戳等） | `#999999` | `#666666` |
| `border` | 分割线、边框 | `#E0E0E0` | `#38383A` |
| `accent` | 链接、图标、按钮高亮 | `#007AFF` | `#0A84FF` |
| `error` | 错误状态 | `#FF3B30` | `#FF453A` |
| `success` | 成功状态 | `#34C759` | `#30D158` |
| `userBubbleBg` | 用户气泡背景 | `#111111` | `#E5E5E5` |
| `userBubbleText` | 用户气泡文字 | `#FFFFFF` | `#111111` |
| `inputBackground` | 输入框背景 | `#FFFFFF` | `#2C2C2E` |
| `inputBorder` | 输入框边框 | `#CCCCCC` | `#38383A` |
| `overlay` | 侧边栏遮罩 | `rgba(0,0,0,0.4)` | `rgba(0,0,0,0.6)` |
| `cardBackground` | 设置页卡片背景 | `#FFFFFF` | `#2C2C2E` |
| `activeSessionBg` | 侧边栏选中 session 背景 | `#E8F0FE` | `#1A3A5C` |
| `disabledButton` | 禁用按钮背景 | `#888888` | `#555555` |

---

## 2. 设置页主题切换 UI

### 新组件：`src/components/settings/ThemeSettings.tsx`

iOS Settings.app 风格的外观设置卡片，包含两个开关：

**交互逻辑：**

| 跟随系统 | 深色模式 | themeMode | 说明 |
|---------|---------|-----------|------|
| ON | （隐藏） | `'system'` | 自动跟随系统设置切换 |
| OFF | OFF | `'light'` | 手动日间模式 |
| OFF | ON | `'dark'` | 手动夜间模式 |

**UI 布局：**
- Section label：「外观」
- 第一行：「跟随系统」+ Switch
- 第二行：「深色模式」+ Switch（仅跟随系统关闭时显示）
- Section footer：说明文字

**在设置页中的位置**（`app/settings/index.tsx`）：
1. ServerConfig
2. LLMProviderConfig
3. **ThemeSettings（新增）**
4. MemorySection
5. DebugLogging

**默认值**：`themeMode = 'system'`

### Store 变更：`src/store/settings.ts`

新增字段：
```typescript
themeMode: 'system' | 'light' | 'dark';
setThemeMode: (mode: 'system' | 'light' | 'dark') => Promise<void>;
```

初始值 `'system'`，通过 AsyncStorage 持久化（key: `@sebastian/themeMode`）。

---

## 3. AI 回复颜色 Bug 修复

### 根因

`MarkdownContent.tsx` 的 body text 使用 `color: '#d0d0d0'`（暗色主题残留），在白色页面背景上对比度不足。

### 修复方案

**普通文字**（body、heading、list、blockquote）：
- 颜色改为 `colors.text`（日间 `#111` / 夜间 `#F5F5F5`）

**代码块**（`<pre>` / `<code>`）：
- 日间夜间**都**保持暗色风格不变
- 背景 `#1E1E2E`，文字 `#A8D8A8`

**链接**：
- 改为 `colors.accent`（日间 `#007AFF` / 夜间 `#0A84FF`）

**ThinkingBlock.tsx**：
- 暗色容器背景保留（`#1a1a2e` pill / `#111120` expanded body），日间夜间不变
- 边框颜色保留 `#2a2a4e`，日间夜间不变
- 标签文字 `#6060a0` 和 chevron `#3a3a5a` 保留不变（在暗色容器上可读）
- 总结：ThinkingBlock 整体保持暗色风格，不跟随主题切换

**ToolCallGroup.tsx**：
- 边框/背景跟随主题 `colors.border` / `colors.secondaryBackground`

---

## 4. 气泡样式变更

### 用户气泡（`UserBubble.tsx`）

ChatGPT 风格：
- 日间：`background: #111`，`color: #FFF`
- 夜间：`background: #E5E5E5`，`color: #111`

### AI 回复气泡

**移除气泡**：
- `MessageBubble.tsx` 中 assistant 消息移除 `backgroundColor: '#F0F0F0'` 和圆角气泡样式
- `StreamingBubble.tsx` 同样移除气泡背景
- 文字直接渲染在页面背景上，颜色跟随 `colors.text`

---

## 5. 受影响文件清单

| 文件 | 动作 |
|------|------|
| `src/theme/colors.ts` | **新建** — Light / Dark 颜色 token |
| `src/theme/ThemeContext.tsx` | **新建** — ThemeProvider + useTheme hook |
| `src/theme/README.md` | **新建** — 目录说明 |
| `src/store/settings.ts` | **修改** — 新增 themeMode 字段 |
| `app/_layout.tsx` | **修改** — 包裹 ThemeProvider |
| `app/index.tsx` | **修改** — 背景色用 token |
| `app/settings/index.tsx` | **修改** — 背景色用 token，插入 ThemeSettings |
| `src/components/settings/ThemeSettings.tsx` | **新建** — 外观设置组件 |
| `src/components/chat/AppSidebar.tsx` | **修改** — 颜色 token 化 |
| `src/components/chat/MessageBubble.tsx` | **修改** — assistant 移除气泡，颜色 token 化 |
| `src/components/chat/StreamingBubble.tsx` | **修改** — 移除气泡背景，颜色 token 化 |
| `src/components/chat/MessageInput.tsx` | **修改** — 颜色 token 化 |
| `src/components/conversation/MarkdownContent.tsx` | **修改** — 普通文字跟随主题，代码块保留暗色 |
| `src/components/conversation/UserBubble.tsx` | **修改** — ChatGPT 风格气泡 |
| `src/components/conversation/ThinkingBlock.tsx` | **修改** — 标签文字适配 |
| `src/components/conversation/ToolCallGroup.tsx` | **修改** — 边框/背景跟随主题 |
| `src/components/common/Sidebar.tsx` | **修改** — 背景色 token 化 |
| `src/components/common/EmptyState.tsx` | **修改** — 颜色 token 化 |
| `src/components/settings/ServerConfig.tsx` | **修改** — 颜色 token 化 |
| `src/components/settings/LLMProviderConfig.tsx` | **修改** — 颜色 token 化 |
| `src/components/settings/MemorySection.tsx` | **修改** — 颜色 token 化 |
| `src/components/settings/DebugLogging.tsx` | **修改** — 颜色 token 化 |
| 相关 README 文件 | **修改** — 同步更新目录说明 |

### 不在范围内

- `src/components/subagents/` — 后续独立处理
- `src/components/common/ApprovalModal.tsx` — 后续独立处理
