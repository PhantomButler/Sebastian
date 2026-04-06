# Mobile App 日间/夜间主题系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sebastian 移动端 App 添加日间/夜间主题切换，修复 AI 回复颜色 bug，统一全 App 颜色管理。

**Architecture:** 新建 `src/theme/` 模块，通过 React Context 提供 `useTheme()` hook，返回当前模式对应的颜色 token 对象。ThemeProvider 在 `app/_layout.tsx` 根部包裹，读取 Zustand settings store 中的 `themeMode`（`'system' | 'light' | 'dark'`）决定最终配色。各组件将硬编码色值替换为 `colors.xxx`，`StyleSheet.create` 改为组件内动态生成。

**Tech Stack:** React Native, Expo, TypeScript, Zustand, AsyncStorage (expo-secure-store), React Context, `useColorScheme` (RN 原生)

**设计文档:** `docs/superpowers/specs/2026-04-06-mobile-theme-system-design.md`

---

## File Structure

```
ui/mobile/src/
├── theme/                     ← 新建目录
│   ├── colors.ts              ← Light / Dark 颜色 token 定义
│   ├── ThemeContext.tsx        ← ThemeProvider + useTheme hook
│   └── README.md              ← 目录说明
├── store/
│   └── settings.ts            ← 修改：新增 themeMode 字段
├── components/
│   ├── chat/
│   │   ├── AppSidebar.tsx     ← 修改：颜色 token 化
│   │   ├── MessageBubble.tsx  ← 修改：assistant 移除气泡
│   │   ├── StreamingBubble.tsx← 修改：移除气泡背景
│   │   └── MessageInput.tsx   ← 修改：颜色 token 化
│   ├── common/
│   │   ├── Sidebar.tsx        ← 修改：背景色 token 化
│   │   └── EmptyState.tsx     ← 修改：颜色 token 化
│   ├── conversation/
│   │   ├── MarkdownContent.tsx← 修改：普通文字跟随主题
│   │   ├── UserBubble.tsx     ← 修改：ChatGPT 风格
│   │   ├── ToolCallGroup.tsx  ← 修改：connector 跟随主题
│   │   └── ToolCallRow.tsx    ← 修改：文字颜色跟随主题
│   └── settings/
│       ├── ThemeSettings.tsx  ← 新建：外观设置组件
│       ├── ServerConfig.tsx   ← 修改：颜色 token 化
│       ├── LLMProviderConfig.tsx ← 修改：颜色 token 化
│       ├── MemorySection.tsx  ← 修改：颜色 token 化
│       └── DebugLogging.tsx   ← 修改：颜色 token 化
app/
├── _layout.tsx                ← 修改：包裹 ThemeProvider
├── index.tsx                  ← 修改：背景色 token 化
└── settings/index.tsx         ← 修改：插入 ThemeSettings，背景色 token 化
```

---

### Task 1: 颜色 Token 定义（`src/theme/colors.ts`）

**Files:**
- Create: `ui/mobile/src/theme/colors.ts`

- [ ] **Step 1: 创建颜色 token 文件**

```typescript
// ui/mobile/src/theme/colors.ts

export interface ThemeColors {
  // Backgrounds
  background: string;
  secondaryBackground: string;
  settingsBackground: string;
  cardBackground: string;
  inputBackground: string;

  // Text
  text: string;
  textSecondary: string;
  textMuted: string;

  // Borders
  border: string;
  borderLight: string;

  // Accent & Status
  accent: string;
  error: string;
  success: string;

  // User Bubble (ChatGPT style)
  userBubbleBg: string;
  userBubbleText: string;

  // Input
  inputBorder: string;

  // Sidebar
  overlay: string;
  activeSessionBg: string;

  // Buttons
  disabledButton: string;

  // Destructive
  destructiveBg: string;

  // Segmented control
  segmentedBg: string;
}

export const lightColors: ThemeColors = {
  background: '#FFFFFF',
  secondaryBackground: '#F9F9F9',
  settingsBackground: '#F2F2F7',
  cardBackground: '#FFFFFF',
  inputBackground: '#F2F2F7',

  text: '#111111',
  textSecondary: '#8E8E93',
  textMuted: '#999999',

  border: '#D1D1D6',
  borderLight: '#E0E0E0',

  accent: '#007AFF',
  error: '#FF3B30',
  success: '#34C759',

  userBubbleBg: '#111111',
  userBubbleText: '#FFFFFF',

  inputBorder: '#CCCCCC',

  overlay: 'rgba(0,0,0,0.4)',
  activeSessionBg: '#E8F0FE',

  disabledButton: '#888888',

  destructiveBg: '#FFF2F1',

  segmentedBg: '#F2F2F7',
};

export const darkColors: ThemeColors = {
  background: '#1C1C1E',
  secondaryBackground: '#2C2C2E',
  settingsBackground: '#000000',
  cardBackground: '#2C2C2E',
  inputBackground: '#2C2C2E',

  text: '#F5F5F5',
  textSecondary: '#8E8E93',
  textMuted: '#666666',

  border: '#38383A',
  borderLight: '#38383A',

  accent: '#0A84FF',
  error: '#FF453A',
  success: '#30D158',

  userBubbleBg: '#E5E5E5',
  userBubbleText: '#111111',

  inputBorder: '#38383A',

  overlay: 'rgba(0,0,0,0.6)',
  activeSessionBg: '#1A3A5C',

  disabledButton: '#555555',

  destructiveBg: '#3A2020',

  segmentedBg: '#2C2C2E',
};
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/theme/colors.ts
git commit -m "feat(theme): 定义 Light / Dark 颜色 token"
```

---

### Task 2: ThemeContext 与 ThemeProvider（`src/theme/ThemeContext.tsx`）

**Files:**
- Create: `ui/mobile/src/theme/ThemeContext.tsx`

**Context:** 这个文件创建 React Context，读取 settings store 的 `themeMode`，结合 RN `useColorScheme()` 决定最终使用 light 还是 dark token。需要注意 `useColorScheme` 在 Task 3 之前 settings store 还没有 `themeMode` 字段，所以本 task 先用字面量 `'system'` 作为 fallback 默认值。Task 3 完成后两者会自然衔接。

- [ ] **Step 1: 创建 ThemeContext 文件**

```typescript
// ui/mobile/src/theme/ThemeContext.tsx
import { createContext, useContext, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';
import { lightColors, darkColors, type ThemeColors } from './colors';
import { useSettingsStore } from '../store/settings';

interface ThemeContextValue {
  colors: ThemeColors;
  isDark: boolean;
}

const ThemeContext = createContext<ThemeContextValue>({
  colors: lightColors,
  isDark: false,
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const systemScheme = useColorScheme();
  const themeMode = useSettingsStore((s) => s.themeMode);

  let isDark: boolean;
  if (themeMode === 'system') {
    isDark = systemScheme === 'dark';
  } else {
    isDark = themeMode === 'dark';
  }

  const colors = isDark ? darkColors : lightColors;

  return (
    <ThemeContext.Provider value={{ colors, isDark }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeColors {
  return useContext(ThemeContext).colors;
}

export function useIsDark(): boolean {
  return useContext(ThemeContext).isDark;
}
```

- [ ] **Step 2: 验证类型检查**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 可能报错 `themeMode` 不存在于 settings store — 这是预期的，Task 3 会修复。如果报错，先暂时跳过，Task 3 完成后统一验证。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/theme/ThemeContext.tsx
git commit -m "feat(theme): 创建 ThemeProvider 和 useTheme hook"
```

---

### Task 3: Settings Store 新增 themeMode（`src/store/settings.ts`）

**Files:**
- Modify: `ui/mobile/src/store/settings.ts`

**Context:** 当前 settings store 使用 `expo-secure-store` 持久化。`themeMode` 不是敏感信息，但为保持一致性仍用同一个存储机制。新增 `themeMode` 字段（`'system' | 'light' | 'dark'`），默认 `'system'`，`load()` 时读取，`setThemeMode()` 时写入。

- [ ] **Step 1: 修改 settings store**

在 `ui/mobile/src/store/settings.ts` 中做以下修改：

1. 在 `KEYS` 对象中新增：
```typescript
  themeMode: 'settings_theme_mode',
```

2. 在 `SettingsState` 接口中新增：
```typescript
  themeMode: 'system' | 'light' | 'dark';
  setThemeMode: (mode: 'system' | 'light' | 'dark') => Promise<void>;
```

3. 在 `create<SettingsState>` 的初始状态中新增：
```typescript
  themeMode: 'system',
```

4. 在 `load` 函数中，`Promise.all` 中新增读取 `KEYS.themeMode`：
```typescript
  const [serverUrl, jwtToken, providerType, apiKey, themeMode] = await Promise.all([
    SecureStore.getItemAsync(KEYS.serverUrl),
    SecureStore.getItemAsync(KEYS.jwtToken),
    SecureStore.getItemAsync(KEYS.llmProviderType),
    SecureStore.getItemAsync(KEYS.llmApiKey),
    SecureStore.getItemAsync(KEYS.themeMode),
  ]);
```

在 `set({...})` 中新增：
```typescript
  themeMode: (themeMode as 'system' | 'light' | 'dark') ?? 'system',
```

5. 新增 `setThemeMode` 方法：
```typescript
  setThemeMode: async (mode) => {
    await SecureStore.setItemAsync(KEYS.themeMode, mode);
    set({ themeMode: mode });
  },
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误（ThemeContext.tsx 现在也能通过，因为 `themeMode` 已存在于 store）

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/store/settings.ts
git commit -m "feat(theme): settings store 新增 themeMode 持久化字段"
```

---

### Task 4: 根布局包裹 ThemeProvider（`app/_layout.tsx`）

**Files:**
- Modify: `ui/mobile/app/_layout.tsx`

**Context:** 当前 `_layout.tsx` 的组件树是 `SafeAreaProvider > GestureHandlerRootView > QueryClientProvider > AppInit > Stack`。ThemeProvider 需要放在 `AppInit` 内部（因为它依赖 `useSettingsStore` 已经被 `load()` 过），包裹 `children`（即 `Stack`）和 `ApprovalModal`。

- [ ] **Step 1: 修改 _layout.tsx**

在 `ui/mobile/app/_layout.tsx` 中：

1. 添加 import：
```typescript
import { ThemeProvider } from '@/src/theme/ThemeContext';
```

2. 修改 `AppInit` 的 return，用 `ThemeProvider` 包裹：
```typescript
  return (
    <ThemeProvider>
      {children}
      <ApprovalModal approval={pending} onGrant={grant} onDeny={deny} />
    </ThemeProvider>
  );
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/app/_layout.tsx
git commit -m "feat(theme): 根布局包裹 ThemeProvider"
```

---

### Task 5: 设置页 ThemeSettings 组件（`src/components/settings/ThemeSettings.tsx`）

**Files:**
- Create: `ui/mobile/src/components/settings/ThemeSettings.tsx`
- Modify: `ui/mobile/app/settings/index.tsx`

**Context:** iOS Settings.app 风格。两个 Switch：「跟随系统」和「深色模式」。跟随系统 ON 时隐藏深色模式开关。注意：这个组件本身也需要使用 `useTheme()` 获取颜色，因为设置页在暗色模式下也需要正确显示。

- [ ] **Step 1: 创建 ThemeSettings 组件**

```typescript
// ui/mobile/src/components/settings/ThemeSettings.tsx
import { View, Text, Switch, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import { useTheme } from '../../theme/ThemeContext';

export function ThemeSettings() {
  const { themeMode, setThemeMode } = useSettingsStore();
  const colors = useTheme();

  const isFollowSystem = themeMode === 'system';
  const isDarkManual = themeMode === 'dark';

  function handleFollowSystemChange(value: boolean) {
    if (value) {
      setThemeMode('system');
    } else {
      // 关闭跟随系统时，默认切到 light
      setThemeMode('light');
    }
  }

  function handleDarkModeChange(value: boolean) {
    setThemeMode(value ? 'dark' : 'light');
  }

  return (
    <View style={styles.group}>
      <Text style={[styles.groupLabel, { color: colors.textSecondary }]}>外观</Text>
      <View style={[styles.card, { backgroundColor: colors.cardBackground }]}>
        <View style={[styles.row, !isFollowSystem && styles.rowBorder, { borderBottomColor: colors.border }]}>
          <Text style={[styles.rowTitle, { color: colors.text }]}>跟随系统</Text>
          <Switch
            value={isFollowSystem}
            onValueChange={handleFollowSystemChange}
          />
        </View>
        {!isFollowSystem && (
          <View style={styles.row}>
            <Text style={[styles.rowTitle, { color: colors.text }]}>深色模式</Text>
            <Switch
              value={isDarkManual}
              onValueChange={handleDarkModeChange}
            />
          </View>
        )}
      </View>
      <Text style={[styles.footer, { color: colors.textSecondary }]}>
        {isFollowSystem
          ? '开启后，外观将自动跟随系统设置切换'
          : '关闭跟随系统后，可手动选择日间或深色模式'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginBottom: 28 },
  groupLabel: {
    marginBottom: 8,
    paddingHorizontal: 4,
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  card: {
    borderRadius: 14,
    overflow: 'hidden',
  },
  row: {
    minHeight: 52,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  rowBorder: {
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  rowTitle: { fontSize: 17 },
  footer: {
    paddingHorizontal: 4,
    paddingTop: 8,
    fontSize: 12,
  },
});
```

- [ ] **Step 2: 在设置页中插入 ThemeSettings**

在 `ui/mobile/app/settings/index.tsx` 中：

1. 添加 import：
```typescript
import { ThemeSettings } from '@/src/components/settings/ThemeSettings';
```

2. 在 `<LLMProviderConfig />` 和 `<MemorySection />` 之间插入：
```tsx
      <LLMProviderConfig />
      <ThemeSettings />
      <MemorySection />
```

- [ ] **Step 3: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/components/settings/ThemeSettings.tsx ui/mobile/app/settings/index.tsx
git commit -m "feat(theme): 新增外观设置组件（跟随系统 + 手动切换）"
```

---

### Task 6: 主聊天页主题化（`app/index.tsx`）

**Files:**
- Modify: `ui/mobile/app/index.tsx`

**Context:** 主聊天页需要将背景色、header 颜色、header 标题色、border 色替换为 theme token。

- [ ] **Step 1: 修改 app/index.tsx**

在 `ui/mobile/app/index.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '@/src/theme/ThemeContext';
```

2. 在 `ChatScreen` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 将 `<View style={styles.container}>` 改为：
```tsx
    <View style={[styles.container, { backgroundColor: colors.background }]}>
```

4. 将 header `<View>` 改为：
```tsx
      <View style={[styles.header, { paddingTop: insets.top, backgroundColor: colors.background, borderBottomColor: colors.borderLight }]}>
```

5. 将 headerTitle `<Text>` 改为：
```tsx
        <Text style={[styles.headerTitle, { color: colors.text }]}>Sebastian</Text>
```

6. 将 menuIcon `<Text>` 改为：
```tsx
          <Text style={[styles.menuIcon, { color: colors.text }]}>☰</Text>
```

7. 删除 styles 中的硬编码颜色：
   - `container`: 移除 `backgroundColor: '#ffffff'`
   - `header`: 移除 `backgroundColor: '#ffffff'`、`borderBottomColor: '#e0e0e0'`
   - `headerTitle`: 移除 `color: '#111'`

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/app/index.tsx
git commit -m "feat(theme): 主聊天页背景和 header 颜色主题化"
```

---

### Task 7: 设置页主题化（`app/settings/index.tsx`）

**Files:**
- Modify: `ui/mobile/app/settings/index.tsx`

**Context:** 设置页需要将背景色、文字色、卡片色、按钮色等全部替换为 theme token。这个文件有较多颜色值。

- [ ] **Step 1: 修改 app/settings/index.tsx**

在 `ui/mobile/app/settings/index.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '@/src/theme/ThemeContext';
```

2. 在 `SettingsScreen` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 将 `<ScrollView style={styles.screen}>` 改为：
```tsx
    <ScrollView style={[styles.screen, { backgroundColor: colors.settingsBackground }]}>
```

4. 将 backText 改为：
```tsx
        <Text style={[styles.backText, { color: colors.accent }]}>‹ 返回</Text>
```

5. 将 heroTitle 改为：
```tsx
        <Text style={[styles.heroTitle, { color: colors.text }]}>设置</Text>
```

6. 将 heroSubtitle 改为：
```tsx
        <Text style={[styles.heroSubtitle, { color: colors.textSecondary }]}>
```

7. 将 groupLabel 改为：
```tsx
          <Text style={[styles.groupLabel, { color: colors.textSecondary }]}>账户</Text>
```
（两处 groupLabel 都需要改）

8. 将 card 改为：
```tsx
          <View style={[styles.card, { backgroundColor: colors.cardBackground }]}>
```
（两处 card 都需要改）

9. 将 row 的 borderBottomColor 改为：
```tsx
            <View style={[styles.row, { borderBottomColor: colors.border }]}>
```

10. 将 rowTitle 改为：
```tsx
              <Text style={[styles.rowTitle, { color: colors.text }]}>Owner 登录</Text>
```
（两处 rowTitle 都需要改）

11. 将 statusOk 改为：
```tsx
              <Text style={[styles.statusOk, { color: colors.success }]}>已连接</Text>
```

12. 将 statusIdle 改为：
```tsx
              <Text style={[styles.statusIdle, { color: colors.textSecondary }]}>未登录</Text>
```

13. 将 inputLabel 改为：
```tsx
              <Text style={[styles.inputLabel, { color: colors.textSecondary }]}>密码</Text>
```

14. 将 input 改为：
```tsx
              <TextInput
                style={[styles.input, { backgroundColor: colors.inputBackground, color: colors.text }]}
                ...
                placeholderTextColor={colors.textMuted}
                ...
              />
```

15. 将 error 改为：
```tsx
            {error ? <Text style={[styles.error, { color: colors.error }]}>{error}</Text> : null}
```

16. 将 primaryButton 改为：
```tsx
            <TouchableOpacity style={[styles.primaryButton, { backgroundColor: colors.accent }]} onPress={handleLogin}>
```

17. 将 destructiveButton 改为：
```tsx
            <TouchableOpacity style={[styles.destructiveButton, { backgroundColor: colors.destructiveBg }]} onPress={handleLogout}>
              <Text style={[styles.destructiveButtonText, { color: colors.error }]}>退出登录</Text>
```

18. 在 styles 中移除所有硬编码颜色（保留尺寸、布局、字体大小等不变的样式属性）。具体移除：
    - `screen`: `backgroundColor: '#F2F2F7'`
    - `backText`: `color: '#007AFF'`
    - `heroTitle`: `color: '#000000'`
    - `heroSubtitle`: `color: '#6D6D72'`
    - `groupLabel`: `color: '#6D6D72'`
    - `card`: `backgroundColor: '#FFFFFF'`
    - `row`: `borderBottomColor: '#D1D1D6'`
    - `rowTitle`: `color: '#111111'`
    - `statusOk`: `color: '#34C759'`
    - `statusIdle`: `color: '#8E8E93'`
    - `inputLabel`: `color: '#6D6D72'`
    - `input`: `backgroundColor: '#F2F2F7'`, `color: '#111111'`
    - `error`: `color: '#FF3B30'`
    - `primaryButton`: `backgroundColor: '#007AFF'`
    - `destructiveButton`: `backgroundColor: '#FFF2F1'`
    - `destructiveButtonText`: `color: '#FF3B30'`

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/app/settings/index.tsx
git commit -m "feat(theme): 设置页颜色全量主题化"
```

---

### Task 8: MarkdownContent 颜色 Bug 修复（`src/components/conversation/MarkdownContent.tsx`）

**Files:**
- Modify: `ui/mobile/src/components/conversation/MarkdownContent.tsx`

**Context:** 这是截图中颜色 bug 的核心文件。当前所有文字用暗色系（`#d0d0d0`），在白色背景上几乎看不清。修复方案：普通文字（body/heading/list/table）跟随主题，代码块（`code_inline`/`fence`/`code_block`）保留暗色不变。

`react-native-markdown-display` 的 `style` prop 接受 `StyleSheet`，但我们需要动态颜色，所以改为直接传对象（该库同时支持 StyleSheet 和普通对象）。

- [ ] **Step 1: 修改 MarkdownContent.tsx**

将 `ui/mobile/src/components/conversation/MarkdownContent.tsx` 完整替换为：

```typescript
import Markdown from 'react-native-markdown-display';
import { useTheme } from '../../theme/ThemeContext';

interface Props {
  content: string;
  /** 流式未完成时传 true */
  streaming?: boolean;
}

export function MarkdownContent({ content }: Props) {
  const colors = useTheme();

  const mdStyles = {
    body: { color: colors.text, fontSize: 15, lineHeight: 22 },
    heading1: { color: colors.text, fontSize: 20, fontWeight: '700' as const, marginBottom: 8 },
    heading2: { color: colors.text, fontSize: 17, fontWeight: '600' as const, marginBottom: 6 },
    heading3: { color: colors.text, fontSize: 15, fontWeight: '600' as const, marginBottom: 4 },
    strong: { color: colors.text, fontWeight: '700' as const },
    em: { fontStyle: 'italic' as const },
    // 代码块保留暗色风格，日间夜间不变
    code_inline: {
      backgroundColor: '#1e1e2e',
      color: '#a8d8a8',
      fontFamily: 'monospace',
      fontSize: 13,
      paddingHorizontal: 4,
      borderRadius: 3,
    },
    fence: {
      backgroundColor: '#111120',
      padding: 12,
      borderRadius: 8,
      marginVertical: 8,
    },
    code_block: {
      color: '#a8d8a8',
      fontFamily: 'monospace',
      fontSize: 13,
      lineHeight: 20,
    },
    bullet_list: { marginVertical: 4 },
    ordered_list: { marginVertical: 4 },
    list_item: { color: colors.text, marginBottom: 2 },
    blockquote: {
      borderLeftWidth: 3,
      borderLeftColor: colors.border,
      paddingLeft: 12,
      marginVertical: 6,
      opacity: 0.8,
    },
    hr: { borderTopColor: colors.border, borderTopWidth: 1, marginVertical: 12 },
    link: { color: colors.accent, textDecorationLine: 'underline' as const },
    table: { borderWidth: 1, borderColor: colors.border, marginVertical: 8 },
    th: { backgroundColor: colors.secondaryBackground, padding: 8, color: colors.text, fontWeight: '600' as const },
    td: { padding: 8, color: colors.text, borderTopWidth: 1, borderTopColor: colors.border },
  };

  return (
    <Markdown style={mdStyles}>{content}</Markdown>
  );
}
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/conversation/MarkdownContent.tsx
git commit -m "fix(theme): MarkdownContent 普通文字跟随主题，代码块保留暗色"
```

---

### Task 9: UserBubble ChatGPT 风格（`src/components/conversation/UserBubble.tsx`）

**Files:**
- Modify: `ui/mobile/src/components/conversation/UserBubble.tsx`

**Context:** 当前紫色气泡改为 ChatGPT 风格：日间黑底白字，夜间浅灰底黑字。颜色来自 `colors.userBubbleBg` 和 `colors.userBubbleText`。

- [ ] **Step 1: 修改 UserBubble.tsx**

将 `ui/mobile/src/components/conversation/UserBubble.tsx` 完整替换为：

```typescript
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';

interface Props {
  content: string;
}

export function UserBubble({ content }: Props) {
  const colors = useTheme();

  return (
    <View style={styles.row}>
      <View style={[styles.bubble, { backgroundColor: colors.userBubbleBg }]}>
        <Text style={[styles.text, { color: colors.userBubbleText }]}>{content}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    paddingHorizontal: 16,
    paddingVertical: 6,
    alignItems: 'flex-end',
  },
  bubble: {
    maxWidth: '75%',
    borderRadius: 18,
    borderBottomRightRadius: 4,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  text: {
    fontSize: 15,
    lineHeight: 21,
  },
});
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/conversation/UserBubble.tsx
git commit -m "feat(theme): UserBubble 改为 ChatGPT 风格主题化气泡"
```

---

### Task 10: ToolCallGroup 和 ToolCallRow 主题化

**Files:**
- Modify: `ui/mobile/src/components/conversation/ToolCallGroup.tsx`
- Modify: `ui/mobile/src/components/conversation/ToolCallRow.tsx`

**Context:** `ToolCallGroup` 的 connector 颜色（`#2a2a2a`）需要跟随主题。`ToolCallRow` 的 name 和 input 文字颜色也需要跟随主题。dot 颜色是状态色（running/done/failed），保持不变。

- [ ] **Step 1: 修改 ToolCallGroup.tsx**

在 `ui/mobile/src/components/conversation/ToolCallGroup.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. 在 `ToolCallGroup` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 将 connector 的 `<View style={styles.connector} />` 改为：
```tsx
          {index < tools.length - 1 && <View style={[styles.connector, { backgroundColor: colors.border }]} />}
```

4. styles 中 `connector` 移除 `backgroundColor: '#2a2a2a'`。

- [ ] **Step 2: 修改 ToolCallRow.tsx**

在 `ui/mobile/src/components/conversation/ToolCallRow.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. 在 `ToolCallRow` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 将 name `<Text>` 改为：
```tsx
      <Text style={[styles.name, { color: colors.textSecondary }]}>{name}</Text>
```

4. 将 input `<Text>` 改为：
```tsx
      {inputPreview ? <Text style={[styles.input, { color: colors.textMuted }]}>{inputPreview}</Text> : null}
```

5. styles 中 `name` 移除 `color: '#8888aa'`，`input` 移除 `color: '#555566'`。

- [ ] **Step 3: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/components/conversation/ToolCallGroup.tsx ui/mobile/src/components/conversation/ToolCallRow.tsx
git commit -m "feat(theme): ToolCallGroup 和 ToolCallRow 颜色主题化"
```

---

### Task 11: MessageBubble 和 StreamingBubble 主题化

**Files:**
- Modify: `ui/mobile/src/components/chat/MessageBubble.tsx`
- Modify: `ui/mobile/src/components/chat/StreamingBubble.tsx`

**Context:** Assistant 消息移除气泡背景（设计文档要求 AI 回复无气泡），文字直接渲染在页面上。User 消息气泡也需要主题化。StreamingBubble 同样移除气泡背景。

- [ ] **Step 1: 修改 MessageBubble.tsx**

将 `ui/mobile/src/components/chat/MessageBubble.tsx` 完整替换为：

```typescript
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
import type { Message } from '../../types';

interface Props { message: Message; }

export function MessageBubble({ message }: Props) {
  const colors = useTheme();
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <View style={[styles.row, styles.rowUser]}>
        <View style={[styles.bubble, { backgroundColor: colors.userBubbleBg }]}>
          <Text style={{ color: colors.userBubbleText }}>{message.content}</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={[styles.row, styles.rowAssistant]}>
      <Text style={{ color: colors.text }}>{message.content}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 12, paddingVertical: 4 },
  rowUser: { alignItems: 'flex-end' },
  rowAssistant: { alignItems: 'flex-start' },
  bubble: { maxWidth: '80%', borderRadius: 16, padding: 10 },
});
```

- [ ] **Step 2: 修改 StreamingBubble.tsx**

将 `ui/mobile/src/components/chat/StreamingBubble.tsx` 完整替换为：

```typescript
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';

interface Props { content: string; }

export function StreamingBubble({ content }: Props) {
  const colors = useTheme();

  if (!content) return null;
  return (
    <View style={styles.row}>
      <Text style={{ color: colors.text }}>{content}</Text>
      <Text style={{ color: colors.accent }}>▋</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 12, paddingVertical: 4, alignItems: 'flex-start', flexDirection: 'row', flexWrap: 'wrap' },
});
```

- [ ] **Step 3: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/components/chat/MessageBubble.tsx ui/mobile/src/components/chat/StreamingBubble.tsx
git commit -m "feat(theme): MessageBubble/StreamingBubble 主题化，assistant 移除气泡"
```

---

### Task 12: MessageInput 主题化（`src/components/chat/MessageInput.tsx`）

**Files:**
- Modify: `ui/mobile/src/components/chat/MessageInput.tsx`

- [ ] **Step 1: 修改 MessageInput.tsx**

在 `ui/mobile/src/components/chat/MessageInput.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. 在 `MessageInput` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 将 container `<View>` 改为：
```tsx
    <View style={[styles.container, { paddingBottom: insets.bottom + 8, backgroundColor: colors.background, borderTopColor: colors.borderLight }]}>
```

4. 将 input `<TextInput>` 改为：
```tsx
      <TextInput
        style={[styles.input, { borderColor: colors.inputBorder, color: colors.text, backgroundColor: colors.inputBackground }]}
        value={text}
        onChangeText={setText}
        placeholder="发消息…"
        placeholderTextColor={colors.textMuted}
        multiline
        onSubmitEditing={isWorking ? undefined : handleSubmit}
        blurOnSubmit={false}
      />
```

5. 将 btn 改为：
```tsx
      <TouchableOpacity
        style={[styles.btn, { backgroundColor: colors.accent }, isWorking && { backgroundColor: colors.error }]}
        onPress={handleSubmit}
      >
```

6. styles 中移除硬编码颜色：
   - `container`: 移除 `backgroundColor: '#fff'`、`borderTopColor: '#eee'`
   - `input`: 移除 `borderColor: '#ccc'`
   - `btn`: 移除 `backgroundColor: '#007AFF'`
   - `btnStop`: 移除整个样式（改为内联）

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/chat/MessageInput.tsx
git commit -m "feat(theme): MessageInput 颜色主题化"
```

---

### Task 13: AppSidebar 主题化（`src/components/chat/AppSidebar.tsx`）

**Files:**
- Modify: `ui/mobile/src/components/chat/AppSidebar.tsx`

**Context:** 当前 AppSidebar 已在上一次会话读取过（见 conversation summary），有以下颜色需要替换：`#f9f9f9`（容器背景）、`#eee`（边框）、`#E8F0FE`（选中高亮）、`#111`（标题+按钮）、`#aaa`（section label）、`#bbb`（删除图标/禁用文字）、`#ccc`（chevron）、`#999`（日期/placeholder）、`#888`（禁用按钮）、`#e0e0e0`（disabled border）、`#efefef`（feature item border）、`#fff`（按钮文字）。

- [ ] **Step 1: 修改 AppSidebar.tsx**

在 `ui/mobile/src/components/chat/AppSidebar.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. 在 `AppSidebar` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 修改 container：
```tsx
    <View style={[styles.container, { paddingTop: insets.top, backgroundColor: colors.secondaryBackground }]}>
```

4. header：
```tsx
      <View style={[styles.header, { borderBottomColor: colors.borderLight }]}>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Sebastian</Text>
      </View>
```

5. featureSection：
```tsx
      <View style={[styles.featureSection, { borderBottomColor: colors.borderLight }]}>
        <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>功能</Text>
```

6. 每个 featureItem：
```tsx
          <TouchableOpacity
            key={item.key}
            style={[
              styles.featureItem,
              { backgroundColor: colors.cardBackground, borderColor: colors.borderLight },
              item.disabled && { borderStyle: 'dashed' as const },
            ]}
            onPress={item.disabled ? undefined : () => handleNav(item.path!)}
            disabled={item.disabled}
            activeOpacity={0.7}
          >
            <Text style={[styles.featureLabel, { color: item.disabled ? colors.textMuted : colors.text }]}>
              {item.label}
            </Text>
            {item.disabled ? (
              <View style={[styles.comingBadge, { backgroundColor: colors.inputBackground }]}>
                <Text style={[styles.comingBadgeText, { color: colors.textMuted }]}>即将推出</Text>
              </View>
            ) : (
              <Text style={[styles.chevron, { color: colors.textMuted }]}>›</Text>
            )}
          </TouchableOpacity>
```

7. historySection：
```tsx
      <View style={styles.historySection}>
        <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>历史对话</Text>
```

8. sessionItem：
```tsx
            <View style={[
              styles.sessionItem,
              { borderBottomColor: colors.borderLight },
              item.id === currentSessionId && { backgroundColor: colors.activeSessionBg, borderRadius: 6 },
            ]}>
```

9. sessionTitle 和 sessionDate：
```tsx
                <Text style={[styles.sessionTitle, { color: colors.text }]} numberOfLines={1}>
                  {item.title || '新对话'}
                </Text>
                <Text style={[styles.sessionDate, { color: colors.textMuted }]}>
```

10. deleteBtn icon color：
```tsx
                <DeleteIcon size={18} color={colors.textMuted} />
```

11. footer：
```tsx
      <View style={[styles.footer, { paddingBottom: insets.bottom + 8, borderTopColor: colors.borderLight }]}>
```

12. newChatBtn：
```tsx
        <TouchableOpacity
          style={[
            styles.newChatBtn,
            { backgroundColor: colors.text },
            (draftSession || !currentSessionId) && { backgroundColor: colors.disabledButton },
          ]}
          onPress={(draftSession || !currentSessionId) ? undefined : onNewChat}
          disabled={draftSession || !currentSessionId}
          activeOpacity={0.85}
        >
          <Text style={[styles.newChatBtnText, { color: colors.background }]}>新对话</Text>
        </TouchableOpacity>
```

13. styles 中移除所有硬编码颜色值，只保留尺寸/布局/字体大小属性。

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/chat/AppSidebar.tsx
git commit -m "feat(theme): AppSidebar 全量颜色主题化"
```

---

### Task 14: Sidebar 容器主题化（`src/components/common/Sidebar.tsx`）

**Files:**
- Modify: `ui/mobile/src/components/common/Sidebar.tsx`

**Context:** 侧边栏容器有白色背景（`#fff`）和遮罩色（`rgba(0,0,0,0.4)`），需要跟随主题。

- [ ] **Step 1: 修改 Sidebar.tsx**

在 `ui/mobile/src/components/common/Sidebar.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. 在 `Sidebar` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. overlay 改为：
```tsx
      <TouchableOpacity
        style={[styles.overlay, { display: visible ? 'flex' : 'none', backgroundColor: colors.overlay }]}
        activeOpacity={1}
        onPress={onClose}
      />
```

4. sidebar Animated.View 改为：
```tsx
          style={[styles.sidebar, { backgroundColor: colors.secondaryBackground, transform: [{ translateX }] }]}
```

5. styles 中：
   - `overlay`: 移除 `backgroundColor: 'rgba(0,0,0,0.4)'`
   - `sidebar`: 移除 `backgroundColor: '#fff'`

- [ ] **Step 2: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/common/Sidebar.tsx
git commit -m "feat(theme): Sidebar 容器背景和遮罩颜色主题化"
```

---

### Task 15: EmptyState 主题化（`src/components/common/EmptyState.tsx`）

**Files:**
- Modify: `ui/mobile/src/components/common/EmptyState.tsx`

- [ ] **Step 1: 修改 EmptyState.tsx**

将 `ui/mobile/src/components/common/EmptyState.tsx` 完整替换为：

```typescript
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';

interface Props {
  message: string;
  ctaLabel?: string;
  onCta?: () => void;
}

export function EmptyState({ message, ctaLabel, onCta }: Props) {
  const colors = useTheme();

  return (
    <View style={styles.container}>
      <Text style={[styles.message, { color: colors.textMuted }]}>{message}</Text>
      {ctaLabel && onCta && (
        <Text style={[styles.cta, { color: colors.accent }]} onPress={onCta}>{ctaLabel}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  message: { textAlign: 'center', marginBottom: 12 },
  cta: { fontWeight: 'bold' },
});
```

- [ ] **Step 2: Commit**

```bash
git add ui/mobile/src/components/common/EmptyState.tsx
git commit -m "feat(theme): EmptyState 颜色主题化"
```

---

### Task 16: Settings 子组件主题化（ServerConfig、LLMProviderConfig、MemorySection、DebugLogging）

**Files:**
- Modify: `ui/mobile/src/components/settings/ServerConfig.tsx`
- Modify: `ui/mobile/src/components/settings/LLMProviderConfig.tsx`
- Modify: `ui/mobile/src/components/settings/MemorySection.tsx`
- Modify: `ui/mobile/src/components/settings/DebugLogging.tsx`

**Context:** 这四个组件都是 iOS Settings.app 风格的卡片，使用相同的颜色模式。全部需要将硬编码色值替换为 theme token。模式一致：`groupLabel` → `colors.textSecondary`，`card` → `colors.cardBackground`，`row borderBottomColor` → `colors.border`，`rowTitle` → `colors.text`，`input bg` → `colors.inputBackground`，`input text` → `colors.text`，`button bg` → `colors.accent`，`error` → `colors.error`，`statusOk` → `colors.success`，`statusFail` → `colors.error`。

- [ ] **Step 1: 修改 ServerConfig.tsx**

在 `ui/mobile/src/components/settings/ServerConfig.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. 在 `ServerConfig` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 逐项替换内联样式（模式与 Task 7 一致）：
   - `<View style={styles.group}>` — 不变（无颜色）
   - `<Text style={styles.groupLabel}>` → `<Text style={[styles.groupLabel, { color: colors.textSecondary }]}>`
   - `<View style={styles.card}>` → `<View style={[styles.card, { backgroundColor: colors.cardBackground }]}>`
   - `<View style={styles.row}>` → `<View style={[styles.row, { borderBottomColor: colors.border }]}>`
   - `<Text style={styles.rowTitle}>` → `<Text style={[styles.rowTitle, { color: colors.text }]}>`
   - statusText → `{ color: colors.textSecondary }`，statusOk → `{ color: colors.success }`，statusFail → `{ color: colors.error }`
   - input → `{ backgroundColor: colors.inputBackground, color: colors.text }`，`placeholderTextColor={colors.textMuted}`
   - button → `{ backgroundColor: colors.accent }`

4. styles 中移除对应的硬编码颜色。

- [ ] **Step 2: 修改 LLMProviderConfig.tsx**

在 `ui/mobile/src/components/settings/LLMProviderConfig.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. **注意**：这个文件有两个组件（`ProviderForm` 和 `LLMProviderConfig`），都需要添加 `const colors = useTheme();`。

3. `ProviderForm` 内的替换：
   - `<View style={styles.form}>` → `<View style={[styles.form, { backgroundColor: colors.cardBackground }]}>`
   - `<Text style={styles.label}>` → `<Text style={[styles.label, { color: colors.textSecondary }]}>`（所有 label）
   - `<TextInput style={styles.input}>` → `<TextInput style={[styles.input, { backgroundColor: colors.inputBackground, color: colors.text }]}>`（所有 input）
   - segmented → `<View style={[styles.segmented, { backgroundColor: colors.segmentedBg }]}>`
   - segmentActive → `{ backgroundColor: colors.cardBackground }`
   - segmentText → `{ color: colors.textSecondary }`，segmentTextActive → `{ color: colors.text }`
   - toggleLabel → `{ color: colors.text }`
   - toggleValue → `{ color: colors.accent }`
   - btnCancel → `{ backgroundColor: colors.segmentedBg }`，btnCancelText → `{ color: colors.text }`
   - btnSave → `{ backgroundColor: colors.accent }`

4. `LLMProviderConfig` 内的替换：
   - `<Text style={styles.groupLabel}>` → `<Text style={[styles.groupLabel, { color: colors.textSecondary }]}>`
   - `<View style={styles.card}>` → `<View style={[styles.card, { backgroundColor: colors.cardBackground }]}>`
   - cardTitle → `{ color: colors.text }`
   - cardSub → `{ color: colors.textSecondary }`
   - actionBtnText → `{ color: colors.accent }`
   - 删除按钮的 `{ color: '#FF3B30' }` → `{ color: colors.error }`
   - addBtn → `{ backgroundColor: colors.cardBackground }`
   - addBtnText → `{ color: colors.accent }`
   - errorText → `{ color: colors.error }`

5. styles 中移除对应的硬编码颜色。

- [ ] **Step 3: 修改 MemorySection.tsx**

在 `ui/mobile/src/components/settings/MemorySection.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. 在 `MemorySection` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 替换：
   - groupLabel → `{ color: colors.textSecondary }`
   - card → `{ backgroundColor: colors.cardBackground }`
   - rowTitle → `{ color: colors.text }`
   - rowSubtitle → `{ color: colors.textSecondary }`
   - placeholder → `{ color: colors.textSecondary }`

4. styles 中移除对应的硬编码颜色。

- [ ] **Step 4: 修改 DebugLogging.tsx**

在 `ui/mobile/src/components/settings/DebugLogging.tsx` 中：

1. 添加 import：
```typescript
import { useTheme } from '../../theme/ThemeContext';
```

2. 在 `DebugLogging` 函数体顶部添加：
```typescript
  const colors = useTheme();
```

3. 替换：
   - groupLabel → `{ color: colors.textSecondary }`
   - card → `{ backgroundColor: colors.cardBackground }`
   - row → `{ borderBottomColor: colors.border }`
   - rowTitle → `{ color: colors.text }`

4. styles 中移除对应的硬编码颜色。

- [ ] **Step 5: 验证类型检查通过**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add ui/mobile/src/components/settings/ServerConfig.tsx ui/mobile/src/components/settings/LLMProviderConfig.tsx ui/mobile/src/components/settings/MemorySection.tsx ui/mobile/src/components/settings/DebugLogging.tsx
git commit -m "feat(theme): 设置页四个子组件全量颜色主题化"
```

---

### Task 17: README 更新

**Files:**
- Create: `ui/mobile/src/theme/README.md`
- Modify: `ui/mobile/src/README.md`
- Modify: `ui/mobile/src/components/README.md`
- Modify: `ui/mobile/src/components/settings/README.md`
- Modify: `ui/mobile/src/components/chat/README.md`
- Modify: `ui/mobile/src/components/conversation/README.md`
- Modify: `ui/mobile/src/components/common/README.md`

- [ ] **Step 1: 创建 `src/theme/README.md`**

```markdown
# theme/

> 上级：[src/](../README.md)

## 目录职责

移动端主题系统，提供日间/夜间配色切换能力。通过 React Context 向全 App 提供当前主题的颜色 token 对象。

## 目录结构

```
theme/
├── colors.ts          # Light / Dark 颜色 token 定义（ThemeColors 类型 + lightColors / darkColors 对象）
└── ThemeContext.tsx    # ThemeProvider（根部包裹）+ useTheme() hook + useIsDark() hook
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 调整某种颜色的日间或夜间值 | [colors.ts](colors.ts) |
| 新增颜色 token | [colors.ts](colors.ts)（加字段）→ ThemeContext 自动生效 |
| 修改主题切换逻辑（system/light/dark） | [ThemeContext.tsx](ThemeContext.tsx) |

## 使用方式

```typescript
import { useTheme } from '../../theme/ThemeContext';

function MyComponent() {
  const colors = useTheme();
  return <View style={{ backgroundColor: colors.background }} />;
}
```

---

> 修改本目录后，请同步更新此 README。
```

- [ ] **Step 2: 修改 `src/README.md`**

在 `ui/mobile/src/README.md` 的目录结构中，在 `store/` 之后添加 `theme/` 条目：

```
├── store/        # Zustand 本地 UI 状态（含 SecureStore 持久化配置）
├── theme/        # 日间/夜间主题系统（颜色 token + ThemeProvider）
├── screens/      # 屏幕级组件占位（当前空目录，预留未来拆分）
```

在「修改导航」表格中添加一行：
```
| 主题颜色 / 日间夜间切换 | [theme/](theme/README.md) |
```

在「子模块」列表中添加：
```
- [theme/](theme/README.md) — 日间/夜间主题系统
```

- [ ] **Step 3: 修改 `src/components/settings/README.md`**

添加 `ThemeSettings.tsx` 条目到目录结构和修改导航表。

- [ ] **Step 4: 修改 `src/components/chat/README.md`**

确认 MessageBubble、StreamingBubble 描述中提到主题化（无气泡 assistant）。

- [ ] **Step 5: 修改 `src/components/conversation/README.md`**

确认 MarkdownContent 描述中提到「普通文字跟随主题，代码块保留暗色」。UserBubble 提到「ChatGPT 风格」。

- [ ] **Step 6: 修改 `src/components/common/README.md`**

确认 Sidebar 描述中提到主题化。

- [ ] **Step 7: Commit**

```bash
git add ui/mobile/src/theme/README.md ui/mobile/src/README.md ui/mobile/src/components/README.md ui/mobile/src/components/settings/README.md ui/mobile/src/components/chat/README.md ui/mobile/src/components/conversation/README.md ui/mobile/src/components/common/README.md
git commit -m "docs(mobile): 新增 theme 目录 README，更新所有受影响的 README"
```

---

### Task 18: 全量类型检查与验收

**Files:** 无新改动

- [ ] **Step 1: 全量类型检查**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 2: 启动 Metro 验证编译**

Run: `cd ui/mobile && npx expo start`
Expected: Metro bundler 启动成功，无编译错误

- [ ] **Step 3: 在模拟器上验证**

手动验证清单：
1. App 启动后显示日间模式（白色背景）
2. AI 回复文字在白色背景上清晰可读（黑色文字）
3. 代码块保持暗色风格
4. 用户气泡为黑底白字
5. 进入设置页 → 外观 → 关闭跟随系统 → 开启深色模式
6. 整个 App 切换为暗色（深灰背景、浅色文字）
7. 侧边栏也为暗色
8. 用户气泡在暗色模式下为浅灰底黑字
9. 重启 App 后主题设置保持不变
10. 再次开启跟随系统，深色模式开关消失
