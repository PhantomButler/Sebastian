# Keyboard Controller Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 React Native 移动端键盘处理从自制的 `useAnimatedKeyboard` + `position:absolute` 补丁方案迁移到 `react-native-keyboard-controller` 官方库，彻底解决 Composer 跟随键盘卡顿和消息列表末尾被遮挡两个问题。

**Architecture:** 使用 `KeyboardStickyView` 替代 `position:absolute` + `useAnimatedKeyboard` 的 Composer 定位（原生层逐帧同步，零 jank）；使用 `KeyboardChatScrollView` 替代 FlatList 内的普通 ScrollView（自动通过 contentInset 调整滚动偏移，不依赖手动 paddingBottom）；`KeyboardGestureArea` 启用手势收起键盘。根组件加 `KeyboardProvider`。

**Tech Stack:** `react-native-keyboard-controller@^1.21.4`（兼容 RN 0.81.5 + Expo 54 + Reanimated 4.1.1 + New Architecture），`react-native-safe-area-context`（屏幕用 `SafeAreaView edges={['bottom']}` 只处理底部安全区）。

---

## 文件结构

| 文件 | 变更类型 | 职责变化 |
|------|---------|---------|
| `ui/mobile/package.json` | 修改 | 新增 `react-native-keyboard-controller` 依赖 |
| `ui/mobile/app/_layout.tsx` | 修改 | 根组件加 `KeyboardProvider` |
| `ui/mobile/src/components/composer/index.tsx` | 修改 | 移除所有键盘/定位逻辑，变为普通 View；移除 `onHeightChange` prop |
| `ui/mobile/src/components/conversation/ConversationView.tsx` | 修改 | 接收可选 `renderScrollComponent` prop 传给 FlatList；移除 `bottomPadding` 动态 prop，改为静态 padding |
| `ui/mobile/app/index.tsx` | 修改 | 用 `SafeAreaView edges={['bottom']}` + `KeyboardGestureArea` + `KeyboardStickyView` 重构；移除 `Keyboard.addListener`/`keyboardHeight`/`composerHeight` 所有补丁 |
| `ui/mobile/app/subagents/session/[id].tsx` | 修改 | 同 index.tsx，相同模式 |

---

## 架构对比

**旧方案（问题所在）：**
```
View (container)
  Header
  ConversationView (FlatList + 手动 contentContainerStyle.paddingBottom)
  Animated.View position:absolute  ← Composer，useAnimatedKeyboard 驱动 bottom layout property
```

**新方案：**
```
SafeAreaView edges={['bottom']}     ← 只处理 bottom safe area
  Header
  KeyboardGestureArea               ← 启用手势收起键盘
    ConversationView
      FlatList (renderScrollComponent=KeyboardChatScrollView)  ← 自动处理滚动偏移
    KeyboardStickyView              ← 原生层跟随键盘，zero jank
      Composer (普通 View，无键盘逻辑)
```

---

## Task 1: 安装依赖并添加 KeyboardProvider

**Files:**
- Modify: `ui/mobile/package.json`
- Modify: `ui/mobile/app/_layout.tsx`

- [ ] **Step 1: 安装 react-native-keyboard-controller**

```bash
cd ui/mobile
npm install react-native-keyboard-controller@^1.21.4
```

Expected output: 包名和版本出现在 `package.json` dependencies 中。

- [ ] **Step 2: 验证 package.json**

打开 `ui/mobile/package.json`，确认 dependencies 中有：
```json
"react-native-keyboard-controller": "^1.21.4"
```

- [ ] **Step 3: 在 `_layout.tsx` 添加 KeyboardProvider**

修改 `ui/mobile/app/_layout.tsx`：

```tsx
import { useEffect, type ReactNode } from 'react';
import { AppState } from 'react-native';
import * as Notifications from 'expo-notifications';
import { router, Stack } from 'expo-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { KeyboardProvider } from 'react-native-keyboard-controller';
import { getApprovals, registerDevice } from '@/src/api/approvals';
import { ApprovalModal } from '@/src/components/common/ApprovalModal';
import { useSSE } from '@/src/hooks/useSSE';
import { useApprovalStore } from '@/src/store/approval';
import { useSettingsStore } from '@/src/store/settings';
import { ThemeProvider } from '@/src/theme/ThemeContext';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 2, staleTime: 30_000 } },
});

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

function AppInit({ children }: { children: ReactNode }) {
  const { load, jwtToken } = useSettingsStore();
  const { pending, grant, deny, setPending } = useApprovalStore();

  async function hydratePendingApproval(): Promise<void> {
    if (!jwtToken) {
      setPending(null);
      return;
    }
    const approvals = await getApprovals().catch(() => []);
    setPending(approvals[0] ?? null);
  }

  useSSE({
    onApprovalRequired: (approval) => setPending(approval),
  });

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!jwtToken) return;
    void (async () => {
      const { status } = await Notifications.requestPermissionsAsync();
      if (status !== 'granted') return;
      const token = (await Notifications.getDevicePushTokenAsync()).data;
      await registerDevice(token).catch(() => {});
    })();
  }, [jwtToken]);

  useEffect(() => {
    void hydratePendingApproval();
  }, [jwtToken]);

  useEffect(() => {
    const appStateSubscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        void hydratePendingApproval();
      }
    });
    const subscription = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        const data = response.notification.request.content.data as Record<string, string>;
        if (
          data?.type === 'approval.required' ||
          data?.type === 'user.approval_requested'
        ) {
          router.push('/');
        } else if (data?.type?.startsWith('task.')) {
          router.push('/subagents');
        }
      },
    );
    return () => {
      appStateSubscription.remove();
      subscription.remove();
    };
  }, [jwtToken]);

  return (
    <ThemeProvider>
      {children}
      <ApprovalModal approval={pending} onGrant={grant} onDeny={deny} />
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <GestureHandlerRootView style={styles.root}>
        <QueryClientProvider client={queryClient}>
          <KeyboardProvider>
            <AppInit>
              <Stack screenOptions={{ headerShown: false }} />
            </AppInit>
          </KeyboardProvider>
        </QueryClientProvider>
      </GestureHandlerRootView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
```

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/package.json ui/mobile/app/_layout.tsx
git commit -m "feat(mobile): 安装 react-native-keyboard-controller，根组件添加 KeyboardProvider

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 重构 Composer — 移除键盘定位逻辑

**Files:**
- Modify: `ui/mobile/src/components/composer/index.tsx`

**背景：** Composer 当前是 `position: absolute` 的 `Animated.View`，自己用 `useAnimatedKeyboard` 计算 `bottom` 位置。新方案中，`KeyboardStickyView`（在调用方屏幕中包裹 Composer）负责定位，Composer 只需渲染内容即可，变成普通 `View`。

移除的东西：
- `useAnimatedKeyboard`、`useAnimatedStyle`（Reanimated 键盘 API）
- `useSafeAreaInsets`（位置由 SafeAreaView + StickyView 处理）
- `Animated.View` → 普通 `View`
- `onHeightChange` prop（已无需从外部测量，屏幕不再需要这个值计算 bottomPadding）
- `styles.floating` 中的 `position: absolute`、`left: 12`、`right: 12`

保留的东西：
- 5 状态机（idle_empty / idle_ready / sending / streaming / cancelling）
- 所有 send/stop/cancel 逻辑
- `thinkActive` + 思考按钮
- `marginHorizontal: 12`、`marginBottom: 12`（Composer 内部间距）

- [ ] **Step 1: 完整替换 `composer/index.tsx`**

```tsx
import { useState, useMemo, useEffect, useRef } from 'react';
import { View, StyleSheet, Alert } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
import { useComposerStore } from '../../store/composer';
import { InputTextArea } from './InputTextArea';
import { ActionsRow } from './ActionsRow';
import type { ComposerState } from './types';

export interface ComposerProps {
  /** Current session id. null when composing a new (draft) session. */
  sessionId: string | null;
  /** True while the backend is streaming a response for this session. */
  isWorking: boolean;
  onSend: (text: string, opts: { thinking: boolean }) => Promise<void>;
  onStop: () => Promise<void>;
}

export function Composer({
  sessionId,
  isWorking,
  onSend,
  onStop,
}: ComposerProps) {
  const colors = useTheme();

  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const cancelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const thinkActive = useComposerStore((s) => s.getThinking(sessionId));
  const setThinking = useComposerStore((s) => s.setThinking);

  const state: ComposerState = useMemo(() => {
    if (isCancelling) return 'cancelling';
    if (isWorking) return 'streaming';
    if (isSending) return 'sending';
    return text.trim() ? 'idle_ready' : 'idle_empty';
  }, [isCancelling, isWorking, isSending, text]);

  // Auto-exit cancelling state when backend confirms turn is done
  useEffect(() => {
    if (!isWorking && isCancelling) {
      setIsCancelling(false);
    }
  }, [isWorking, isCancelling]);

  // 5s timeout safeguard: force-recover UI if backend doesn't respond
  useEffect(() => {
    if (state !== 'cancelling') {
      if (cancelTimerRef.current) {
        clearTimeout(cancelTimerRef.current);
        cancelTimerRef.current = null;
      }
      return;
    }
    cancelTimerRef.current = setTimeout(() => {
      setIsCancelling(false);
      Alert.alert('提示', '取消可能未生效，请下拉刷新');
    }, 5000);
    return () => {
      if (cancelTimerRef.current) {
        clearTimeout(cancelTimerRef.current);
        cancelTimerRef.current = null;
      }
    };
  }, [state]);

  async function handleSendOrStop() {
    if (state === 'streaming') {
      setIsCancelling(true);
      try {
        await onStop();
      } catch {
        setIsCancelling(false);
      }
      return;
    }
    if (state !== 'idle_ready') return;
    const content = text.trim();
    setText('');
    setIsSending(true);
    try {
      await onSend(content, { thinking: thinkActive });
    } catch {
      setText(content);
    } finally {
      setIsSending(false);
    }
  }

  const isInputDisabled = state === 'sending' || state === 'cancelling';

  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: colors.cardBackground,
          borderColor: colors.borderLight,
          shadowColor: colors.shadowColor,
        },
      ]}
    >
      <InputTextArea
        value={text}
        onChange={setText}
        editable={!isInputDisabled}
      />
      <ActionsRow
        state={state}
        thinkActive={thinkActive}
        onThinkToggle={() => setThinking(sessionId, !thinkActive)}
        onSendOrStop={handleSendOrStop}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: 12,
    marginBottom: 12,
    borderRadius: 24,
    padding: 12,
    borderWidth: 1,
    // iOS shadow
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 8,
    // Android shadow
    elevation: 3,
  },
});
```

- [ ] **Step 2: 确认编译无误（TypeScript 检查）**

在 `ui/mobile/` 目录，确认 `ComposerProps` 不再有 `onHeightChange`，`Animated.View` 已被移除。用 grep 快速验证：

```bash
cd ui/mobile
grep -n "onHeightChange\|useAnimatedKeyboard\|Animated\.View" src/components/composer/index.tsx
```

Expected: 无输出（这些都已被删除）。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/composer/index.tsx
git commit -m "refactor(composer): 移除键盘定位逻辑，变为普通 View

Composer 不再自行处理键盘偏移，定位职责交给外层 KeyboardStickyView。
移除 useAnimatedKeyboard/useSafeAreaInsets/Animated.View/onHeightChange。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 重构 ConversationView — 支持 renderScrollComponent

**Files:**
- Modify: `ui/mobile/src/components/conversation/ConversationView.tsx`

**背景：** `KeyboardChatScrollView` 需要作为 FlatList 的 scroll 组件注入（`renderScrollComponent` prop）。`ConversationView` 接受可选的 `renderScrollComponent`，有就传给 FlatList，没有就用默认行为（向后兼容）。`bottomPadding` 动态 prop 移除，改用静态值（`COMPOSER_DEFAULT_HEIGHT + 12 = 108`），`KeyboardChatScrollView` 自动处理键盘出现时的额外滚动空间。

- [ ] **Step 1: 完整替换 `ConversationView.tsx`**

```tsx
import { useCallback, useRef } from 'react';
import { FlatList, View, StyleSheet } from 'react-native';
import { useConversation } from '../../hooks/useConversation';
import { useConversationStore } from '../../store/conversation';
import { useTheme } from '../../theme/ThemeContext';
import { UserBubble } from './UserBubble';
import { AssistantMessage } from './AssistantMessage';
import { ErrorBanner } from './ErrorBanner';
import { COMPOSER_DEFAULT_HEIGHT } from '../composer/constants';
import type { ConvMessage, ErrorBanner as ErrorBannerType, RenderBlock } from '../../types';

// Static bottom padding: space for the Composer at rest.
// KeyboardChatScrollView automatically adds keyboard height on top of this.
const LIST_BOTTOM_PADDING = COMPOSER_DEFAULT_HEIGHT + 12;

interface Props {
  sessionId: string | null;
  errorBanner?: ErrorBannerType | null;
  onBannerAction?: () => void;
  // Pass KeyboardChatScrollView as renderScrollComponent for keyboard-aware scrolling.
  // If omitted, FlatList uses its built-in ScrollView (e.g. in non-chat contexts).
  renderScrollComponent?: (props: object) => React.ReactElement;
}

type ListItem =
  | { kind: 'message'; message: ConvMessage }
  | { kind: 'streaming'; blocks: RenderBlock[] };

export function ConversationView({
  sessionId,
  errorBanner,
  onBannerAction,
  renderScrollComponent,
}: Props) {
  useConversation(sessionId);
  const colors = useTheme();

  const flatListRef = useRef<FlatList>(null);

  const session = useConversationStore((s) =>
    sessionId ? s.sessions[sessionId] : undefined,
  );

  const messages = session?.messages ?? [];
  const activeTurn = session?.activeTurn ?? null;

  const items: ListItem[] = [
    ...messages.map((m) => ({ kind: 'message' as const, message: m })),
    ...(activeTurn && activeTurn.blocks.length > 0
      ? [{ kind: 'streaming' as const, blocks: activeTurn.blocks }]
      : []),
  ];

  const renderItem = useCallback(({ item }: { item: ListItem }) => {
    if (item.kind === 'message') {
      const { message } = item;
      if (message.role === 'user') {
        return <UserBubble content={message.content} />;
      }
      return (
        <AssistantMessage
          blocks={
            message.blocks ?? [
              { type: 'text', blockId: message.id, text: message.content, done: true },
            ]
          }
        />
      );
    }
    return <AssistantMessage blocks={item.blocks} />;
  }, []);

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <FlatList
        ref={flatListRef}
        style={{ flex: 1 }}
        data={items}
        keyExtractor={(item, index) =>
          item.kind === 'message' ? item.message.id : `streaming-${index}`
        }
        renderItem={renderItem}
        renderScrollComponent={renderScrollComponent}
        contentContainerStyle={{ paddingTop: 12, paddingBottom: LIST_BOTTOM_PADDING }}
        onContentSizeChange={() =>
          flatListRef.current?.scrollToEnd({ animated: true })
        }
        ListFooterComponent={
          errorBanner ? (
            <ErrorBanner message={errorBanner.message} onAction={onBannerAction ?? (() => {})} />
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
});
```

- [ ] **Step 2: 验证导入路径正确**

```bash
cd ui/mobile
grep -n "COMPOSER_DEFAULT_HEIGHT" src/components/composer/constants.ts
```

Expected: 找到 `export const COMPOSER_DEFAULT_HEIGHT = 96;`

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/conversation/ConversationView.tsx
git commit -m "refactor(conversation): 支持 renderScrollComponent，移除动态 bottomPadding prop

接受可选 renderScrollComponent 传给 FlatList，用于注入 KeyboardChatScrollView。
底部 padding 改为静态常量，由 KeyboardChatScrollView 自动处理键盘空间。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 重构主对话屏 `app/index.tsx`

**Files:**
- Modify: `ui/mobile/app/index.tsx`

**背景：** 当前用 `Keyboard.addListener` + `keyboardHeight` 状态 + `composerHeight` 动态计算 `bottomPadding`，这套方案有 JS 线程延迟和计算不准确问题。新方案：
- 外层改为 `SafeAreaView edges={['bottom']}` 处理底部安全区
- `KeyboardGestureArea` 包裹消息列表 + Composer，启用手势收起键盘
- `KeyboardStickyView` 包裹 Composer，原生层跟随键盘
- `KeyboardChatScrollView` 作为 `renderScrollComponent` 传给 ConversationView
- 删除 `Keyboard.addListener`、`keyboardHeight`、`composerHeight`、`bottomPadding` 所有相关代码

**关键数学（供理解，不需要手动计算）：**
- `SafeAreaView edges={['bottom']}` 给容器加 `paddingBottom = insets.bottom`
- `KeyboardStickyView offset={{ opened: insets.bottom }}` 的效果：键盘收起时 Composer 在安全区底部；键盘打开时 Composer 底部贴在键盘顶部
- Composer 内的 `marginBottom: 12` 给键盘顶部/屏幕底部留 12px 间隙

- [ ] **Step 1: 完整替换 `app/index.tsx`**

```tsx
import { useCallback, useMemo, useState } from 'react';
import { View, StyleSheet, Alert, TouchableOpacity, Text } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import axios from 'axios';
import {
  KeyboardGestureArea,
  KeyboardStickyView,
  KeyboardChatScrollView,
} from 'react-native-keyboard-controller';
import { useSessionStore } from '@/src/store/session';
import { useSessions } from '@/src/hooks/useSessions';
import { sendTurn, cancelTurn } from '@/src/api/turns';
import { deleteSession } from '@/src/api/sessions';
import { useQueryClient } from '@tanstack/react-query';
import { Sidebar } from '@/src/components/common/Sidebar';
import { EmptyState } from '@/src/components/common/EmptyState';
import { AppSidebar } from '@/src/components/chat/AppSidebar';
import { Composer } from '@/src/components/composer';
import { ConversationView } from '@/src/components/conversation';
import { ErrorBanner } from '@/src/components/conversation/ErrorBanner';
import { useConversationStore } from '@/src/store/conversation';
import { useComposerStore } from '@/src/store/composer';
import { useTheme } from '@/src/theme/ThemeContext';
import { COMPOSER_DEFAULT_HEIGHT } from '@/src/components/composer/constants';

export default function ChatScreen() {
  const colors = useTheme();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const {
    currentSessionId, draftSession,
    setCurrentSession, startDraft, persistSession,
  } = useSessionStore();
  const { data: sessions = [] } = useSessions();
  const isWorking = useConversationStore(
    (s) => !!(currentSessionId && s.sessions[currentSessionId]?.activeTurn),
  );
  const currentBanner = useConversationStore((s) =>
    currentSessionId ? (s.sessions[currentSessionId]?.errorBanner ?? null) : s.draftErrorBanner,
  );

  // KeyboardStickyView offset: when keyboard opens, Composer bottom sits at keyboard top.
  // insets.bottom compensates for SafeAreaView's bottom padding (which would double-stack
  // without this offset when keyboard is visible).
  const stickyOffset = useMemo(() => ({ opened: insets.bottom }), [insets.bottom]);

  // renderScrollComponent passes KeyboardChatScrollView to FlatList.
  // offset = insets.bottom makes KeyboardChatScrollView's scroll adjustment align with
  // how KeyboardStickyView positions the Composer.
  const renderScrollComponent = useCallback(
    (props: object) => (
      <KeyboardChatScrollView
        {...props}
        keyboardDismissMode="interactive"
        keyboardLiftBehavior="always"
        offset={insets.bottom}
        contentInsetAdjustmentBehavior="never"
        automaticallyAdjustContentInsets={false}
      />
    ),
    [insets.bottom],
  );

  async function handleSend(text: string, _opts: { thinking: boolean }) {
    try {
      const { sessionId } = await sendTurn(currentSessionId, text);
      if (!currentSessionId) {
        persistSession({
          id: sessionId,
          agent: 'sebastian',
          title: text.slice(0, 40),
          status: 'active',
          updated_at: new Date().toISOString(),
          task_count: 0,
          active_task_count: 0,
          depth: 0,
          parent_session_id: null,
          last_activity_at: new Date().toISOString(),
        });
        useComposerStore.getState().migrateDraftToSession(sessionId);
        queryClient.invalidateQueries({ queryKey: ['sessions'] });
      }
      useConversationStore.getState().appendUserMessage(sessionId, text);
      queryClient.invalidateQueries({ queryKey: ['messages', sessionId] });
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 400) {
        const detail = err.response.data?.detail;
        if (detail?.code === 'no_llm_provider') {
          const banner = { code: detail.code, message: detail.message };
          const store = useConversationStore.getState();
          if (currentSessionId) {
            store.setErrorBanner(currentSessionId, banner);
          } else {
            store.setDraftErrorBanner(banner);
          }
          return;
        }
      }
      Alert.alert('发送失败，请重试');
      throw err;
    }
  }

  async function handleStop() {
    if (currentSessionId) await cancelTurn(currentSessionId);
  }

  async function handleDeleteSession(id: string) {
    Alert.alert('删除对话', '确认删除这条对话记录？', [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteSession(id);
            if (currentSessionId === id) setCurrentSession(null);
            useComposerStore.getState().clearSession(id);
            queryClient.invalidateQueries({ queryKey: ['sessions'] });
            queryClient.invalidateQueries({ queryKey: ['agent-sessions'] });
          } catch {
            Alert.alert('删除失败，请重试');
          }
        },
      },
    ]);
  }

  const isEmpty = !currentSessionId && !draftSession;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.container, { backgroundColor: colors.background }]}
    >
      <View
        style={[
          styles.header,
          {
            paddingTop: insets.top,
            backgroundColor: colors.background,
            borderBottomColor: colors.borderLight,
          },
        ]}
      >
        <TouchableOpacity
          style={styles.menuButton}
          onPress={() => setSidebarOpen(true)}
        >
          <Text style={[styles.menuIcon, { color: colors.text }]}>☰</Text>
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Sebastian</Text>
      </View>

      <KeyboardGestureArea
        style={styles.gestureArea}
        interpolator="ios"
        offset={COMPOSER_DEFAULT_HEIGHT}
        textInputNativeID="composer-input"
      >
        {isEmpty ? (
          currentBanner ? (
            <View style={styles.emptyContainer}>
              <ErrorBanner
                message={currentBanner.message}
                onAction={() => router.push('/settings')}
              />
            </View>
          ) : (
            <EmptyState message="向 Sebastian 发送消息开始对话" />
          )
        ) : (
          <ConversationView
            sessionId={currentSessionId}
            errorBanner={currentBanner}
            onBannerAction={() => router.push('/settings')}
            renderScrollComponent={renderScrollComponent}
          />
        )}

        <KeyboardStickyView offset={stickyOffset} style={styles.stickyComposer}>
          <Composer
            sessionId={currentSessionId}
            isWorking={isWorking}
            onSend={handleSend}
            onStop={handleStop}
          />
        </KeyboardStickyView>
      </KeyboardGestureArea>

      <Sidebar
        visible={sidebarOpen}
        onOpen={() => setSidebarOpen(true)}
        onClose={() => setSidebarOpen(false)}
      >
        <AppSidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          draftSession={draftSession}
          onSelect={(id) => { setCurrentSession(id); setSidebarOpen(false); }}
          onNewChat={() => { startDraft(); setSidebarOpen(false); }}
          onDelete={handleDeleteSession}
          onClose={() => setSidebarOpen(false)}
        />
      </Sidebar>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  emptyContainer: { flex: 1 },
  header: {
    minHeight: 48,
    borderBottomWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
  },
  menuButton:  { padding: 8 },
  menuIcon:    { fontSize: 20 },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 16,
    fontWeight: '600',
    marginRight: 36,
  },
  gestureArea: { flex: 1 },
  stickyComposer: {
    position: 'absolute',
    width: '100%',
  },
});
```

**注意：** 这里 `useSafeAreaInsets()` 从 `react-native-safe-area-context` 导入，用于 `header.paddingTop` 和 `stickyOffset`。`SafeAreaView edges={['bottom']}` 处理底部安全区，顶部依然由 header 的 `paddingTop: insets.top` 手动处理（与原来一致）。

- [ ] **Step 2: 验证无残留**

```bash
cd ui/mobile
grep -n "Keyboard\.addListener\|keyboardHeight\|composerHeight\|bottomPadding\|COMPOSER_DEFAULT_HEIGHT\|onHeightChange" app/index.tsx
```

Expected: 只有 `COMPOSER_DEFAULT_HEIGHT` 一行（作为 `KeyboardGestureArea.offset` 的值），其余无输出。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/app/index.tsx
git commit -m "refactor(chat-screen): 迁移至 KeyboardStickyView + KeyboardChatScrollView

移除 Keyboard.addListener/keyboardHeight/composerHeight/bottomPadding 所有补丁。
用 KeyboardGestureArea + KeyboardStickyView + KeyboardChatScrollView 重构，
键盘处理完全由 react-native-keyboard-controller 负责。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 重构子 Agent 会话详情屏 `app/subagents/session/[id].tsx`

**Files:**
- Modify: `ui/mobile/app/subagents/session/[id].tsx`

**背景：** 这是截图一中末尾消息被遮挡的屏幕。当前 Composer 是 `position:absolute` 的 `Animated.View` 浮在 `ConversationView` 上面，且 `onHeightChange={() => {}}` 是空操作（没有做任何 bottomPadding 补偿），所以末尾必然被遮挡。迁移到 `KeyboardStickyView` 后，Composer 不再遮挡消息列表。

- [ ] **Step 1: 完整替换 `app/subagents/session/[id].tsx`**

```tsx
import { useCallback, useMemo, useRef, useState } from 'react';
import { Alert, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import {
  KeyboardGestureArea,
  KeyboardStickyView,
  KeyboardChatScrollView,
} from 'react-native-keyboard-controller';
import {
  createAgentSession,
  getSessionDetail,
  getSessionTasks,
  sendTurnToSession,
} from '../../../src/api/sessions';
import { useConversationStore } from '../../../src/store/conversation';
import { Composer } from '../../../src/components/composer';
import { ConversationView } from '../../../src/components/conversation';
import { SessionDetailView } from '../../../src/components/subagents/SessionDetailView';
import { ErrorBanner } from '../../../src/components/conversation/ErrorBanner';
import { COMPOSER_DEFAULT_HEIGHT } from '../../../src/components/composer/constants';
import type { TaskDetail } from '../../../src/types';

type Tab = 'messages' | 'tasks';

const MOCK_MESSAGES = [
  {
    id: 'mock-message-1',
    sessionId: 'mock-session',
    role: 'user' as const,
    content: '帮我复盘一下今天的持仓波动。',
    createdAt: '2026-04-02T10:00:00Z',
  },
  {
    id: 'mock-message-2',
    sessionId: 'mock-session',
    role: 'assistant' as const,
    content: '我已经把盘中异动拆成了两条任务，一条看新闻，一条看技术面。',
    createdAt: '2026-04-02T10:00:12Z',
  },
];

const MOCK_TASKS: TaskDetail[] = [
  {
    id: 'mock-task-1',
    session_id: 'mock-session',
    goal: '收集盘前新闻并标记影响仓位的事件',
    status: 'running',
    assigned_agent: 'stock',
    created_at: '2026-04-02T10:00:15Z',
    completed_at: null,
  },
  {
    id: 'mock-task-2',
    session_id: 'mock-session',
    goal: '对比昨日与今日的成交量结构',
    status: 'completed',
    assigned_agent: 'stock',
    created_at: '2026-04-02T10:00:20Z',
    completed_at: '2026-04-02T10:02:00Z',
  },
];

type MockDetail = {
  session: {
    id: string;
    agent: string;
    title: string;
    status: 'active' | 'idle' | 'archived';
    updated_at: string;
    task_count: number;
    active_task_count: number;
  };
  messages: Array<{ role: 'user' | 'assistant'; content: string; ts?: string }>;
};

function buildMockDetail(sessionId: string, agentName: string): MockDetail {
  return {
    session: {
      id: sessionId,
      agent: agentName,
      title: '模拟 Supervision 会话',
      status: 'active',
      updated_at: '2026-04-02T10:03:00Z',
      task_count: MOCK_TASKS.length,
      active_task_count: 1,
    },
    messages: MOCK_MESSAGES.map((message) => ({
      role: message.role,
      content: message.content,
      ts: message.createdAt,
    })),
  };
}

export default function SessionDetailScreen() {
  const { id, agent = 'sebastian' } = useLocalSearchParams<{
    id: string;
    agent: string;
  }>();
  const sessionId = (Array.isArray(id) ? id[0] : id) ?? '';
  const agentName = (Array.isArray(agent) ? agent[0] : agent) ?? 'sebastian';
  const isMockSession = sessionId.startsWith('mock-');
  const isNewSession = sessionId === 'new';
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>('messages');
  const [sending, setSending] = useState(false);
  const [realSessionId, setRealSessionId] = useState<string | null>(null);
  const sendingRef = useRef(false);
  const effectiveSessionId = realSessionId || (isNewSession ? null : sessionId);
  const banner = useConversationStore(
    (s) => s.sessions[effectiveSessionId ?? sessionId]?.errorBanner ?? null,
  );

  const { data: remoteDetail } = useQuery({
    queryKey: ['session-detail', effectiveSessionId, agentName],
    queryFn: () => getSessionDetail(effectiveSessionId!, agentName),
    enabled: !!effectiveSessionId && !isMockSession,
  });

  const { data: remoteTasks = [] } = useQuery({
    queryKey: ['session-tasks', effectiveSessionId, agentName],
    queryFn: () => getSessionTasks(effectiveSessionId!, agentName),
    enabled: !!effectiveSessionId && !isMockSession,
  });

  const detail = useMemo(
    () => (isMockSession ? buildMockDetail(sessionId, agentName) : remoteDetail),
    [agentName, isMockSession, remoteDetail, sessionId],
  );
  const displayTitle = isNewSession && !realSessionId ? '新对话' : (detail?.session.title ?? '会话详情');
  const tasks = isMockSession ? MOCK_TASKS : remoteTasks;

  const stickyOffset = useMemo(() => ({ opened: insets.bottom }), [insets.bottom]);

  const renderScrollComponent = useCallback(
    (props: object) => (
      <KeyboardChatScrollView
        {...props}
        keyboardDismissMode="interactive"
        keyboardLiftBehavior="always"
        offset={insets.bottom}
        contentInsetAdjustmentBehavior="never"
        automaticallyAdjustContentInsets={false}
      />
    ),
    [insets.bottom],
  );

  const handleSend = useCallback(
    async (text: string, _opts?: { thinking: boolean }) => {
      if (isMockSession) {
        Alert.alert('模拟会话', '这是用于导航测试的假数据页面。');
        return;
      }
      if (sendingRef.current) return;
      sendingRef.current = true;
      setSending(true);
      try {
        if (isNewSession && !realSessionId) {
          const { sessionId: newId } = await createAgentSession(agentName, text);
          setRealSessionId(newId);
          router.replace(`/subagents/session/${newId}?agent=${agentName}`);
          return;
        }
        if (!effectiveSessionId) return;
        await sendTurnToSession(effectiveSessionId, text, agentName);
        useConversationStore.getState().appendUserMessage(effectiveSessionId, text);
        queryClient.invalidateQueries({
          queryKey: ['session-detail', effectiveSessionId, agentName],
        });
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 400) {
          const detail = err.response.data?.detail;
          if (detail?.code === 'no_llm_provider') {
            useConversationStore.getState().setErrorBanner(effectiveSessionId ?? sessionId, {
              code: detail.code,
              message: detail.message,
            });
            return;
          }
        }
        Alert.alert('发送失败，请重试');
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    },
    [agentName, effectiveSessionId, isMockSession, isNewSession, queryClient, realSessionId, router, sessionId],
  );

  return (
    <SafeAreaView edges={['bottom']} style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top }]}>
        <TouchableOpacity style={styles.back} onPress={() => router.back()}>
          <Text style={styles.backText}>‹ 返回</Text>
        </TouchableOpacity>
        <Text style={styles.title} numberOfLines={1}>
          {displayTitle}
        </Text>
      </View>
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, tab === 'messages' && styles.tabActive]}
          onPress={() => setTab('messages')}
        >
          <Text
            style={[styles.tabText, tab === 'messages' && styles.tabTextActive]}
          >
            消息
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, tab === 'tasks' && styles.tabActive]}
          onPress={() => setTab('tasks')}
        >
          <Text style={[styles.tabText, tab === 'tasks' && styles.tabTextActive]}>
            任务 {tasks.length > 0 ? `(${tasks.length})` : ''}
          </Text>
        </TouchableOpacity>
      </View>

      <KeyboardGestureArea
        style={styles.gestureArea}
        interpolator="ios"
        offset={COMPOSER_DEFAULT_HEIGHT}
        textInputNativeID="composer-input"
      >
        {tab === 'messages' ? (
          <ConversationView
            sessionId={isMockSession ? null : effectiveSessionId}
            errorBanner={banner}
            onBannerAction={() => router.push('/settings')}
            renderScrollComponent={renderScrollComponent}
          />
        ) : (
          <SessionDetailView tasks={tasks} />
        )}

        <KeyboardStickyView offset={stickyOffset} style={styles.stickyComposer}>
          <Composer
            sessionId={effectiveSessionId}
            isWorking={sending}
            onSend={handleSend}
            onStop={async () => {}}
          />
        </KeyboardStickyView>
      </KeyboardGestureArea>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F5F5' },
  header: {
    backgroundColor: '#FFFFFF',
    borderBottomWidth: 1,
    borderBottomColor: '#E0E0E0',
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 48,
    paddingHorizontal: 12,
  },
  back: { padding: 8, marginRight: 4 },
  backText: { fontSize: 16, color: '#007AFF' },
  title: { flex: 1, fontSize: 15, fontWeight: '600', color: '#111111' },
  tabs: {
    flexDirection: 'row',
    backgroundColor: '#FFFFFF',
    borderBottomWidth: 1,
    borderBottomColor: '#E0E0E0',
  },
  tab: { flex: 1, paddingVertical: 10, alignItems: 'center' },
  tabActive: { borderBottomWidth: 2, borderBottomColor: '#007AFF' },
  tabText: { fontSize: 14, color: '#888888' },
  tabTextActive: { color: '#007AFF', fontWeight: '600' },
  gestureArea: { flex: 1 },
  stickyComposer: {
    position: 'absolute',
    width: '100%',
  },
});
```

**注意：** `ErrorBanner` 现在通过 `ConversationView` 的 `errorBanner` prop 传入，在 `ListFooterComponent` 内渲染，不再单独悬浮在 Composer 上方。

- [ ] **Step 2: 验证无残留旧代码**

```bash
cd ui/mobile
grep -n "onHeightChange\|useAnimatedKeyboard\|bottomPadding\|position.*absolute" \
  app/subagents/session/\[id\].tsx
```

Expected: 无输出。

- [ ] **Step 3: Commit**

```bash
git add "ui/mobile/app/subagents/session/[id].tsx"
git commit -m "refactor(session-detail): 迁移至 KeyboardStickyView + KeyboardChatScrollView

修复消息被 Composer 遮挡问题（原因：onHeightChange 是空操作，bottomPadding 从未补偿）。
KeyboardStickyView 使 Composer 不再浮在消息列表上，而是紧贴键盘/屏幕底部。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 构建 APK 并验证

**背景：** `react-native-keyboard-controller` 是原生模块，必须重新构建 APK 才能生效。

- [ ] **Step 1: 确认 Android 模拟器已启动**

```bash
~/Library/Android/sdk/platform-tools/adb devices
```

Expected: 列表中有一个 `device` 状态的设备（如 `emulator-5554 device`）。

若无，先启动：
```bash
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -no-snapshot-load &
~/Library/Android/sdk/platform-tools/adb wait-for-device shell getprop sys.boot_completed
```

- [ ] **Step 2: 构建并安装 APK**

```bash
cd ui/mobile
npx expo run:android
```

这一步需要几分钟。Expected: 编译成功，App 启动，无 crash。

- [ ] **Step 3: 验证键盘行为**

手动测试以下场景：
1. **主对话页 — 无对话时**: App 启动，底部 Composer 显示在屏幕底部，无多余空白
2. **主对话页 — 点击输入框**: 键盘弹出，Composer 跟随键盘上移，动画顺滑无掉帧
3. **主对话页 — 收起键盘**: Composer 回到屏幕底部，无灰条、无残留空白
4. **主对话页 — 发送消息后**: 消息列表末尾一条完整可见，不被 Composer 遮挡
5. **子 Agent 会话详情页**: 同上 1-4

- [ ] **Step 4: 如果发现 Composer 位置偏差，调整 offset**

如果 Composer 在键盘开/关时有轻微偏移，调整以下两处 `offset`（两个屏幕保持一致）：

在 `app/index.tsx` 和 `app/subagents/session/[id].tsx` 中：
```tsx
// 当前：offset = insets.bottom（0 gap between keyboard and composer）
const stickyOffset = useMemo(() => ({ opened: insets.bottom }), [insets.bottom]);

// 如需要键盘和 Composer 之间有 8px 间隙，改为：
const stickyOffset = useMemo(() => ({ opened: insets.bottom - 8 }), [insets.bottom]);
```

对应 `KeyboardChatScrollView` 的 `offset` 同步修改为相同值。

- [ ] **Step 5: 验证通过后 Commit**

```bash
git add -p  # 如果有 offset 调整需要提交
git commit -m "fix(mobile): 调整 KeyboardStickyView/KeyboardChatScrollView offset 数值

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

若无调整跳过此步。

---

## 自查清单

**Spec 覆盖检查：**
- [x] 键盘跟随动画卡顿 → Task 2+4+5，`KeyboardStickyView` 原生层帧同步
- [x] 消息末尾被遮挡（主对话页）→ Task 3+4，`KeyboardChatScrollView` 自动调整 + 静态 paddingBottom
- [x] 消息末尾被遮挡（子 Agent 详情页）→ Task 5，原先 `onHeightChange={}` 空操作导致从未补偿
- [x] 键盘收起后灰条 → Task 4，移除 KAV，SafeAreaView 不会产生灰条
- [x] 输入框底部多余空间 → Task 4，移除动态 bottomPadding 计算
- [x] 根组件 KeyboardProvider → Task 1
- [x] `onHeightChange` 清理 → Task 2，从 ComposerProps 移除
- [x] 两个屏幕模式一致 → Task 4+5 使用完全相同的 offset 公式

**Placeholder 检查：** 无 TBD/TODO，所有代码块完整。

**类型一致性：** `renderScrollComponent: (props: object) => React.ReactElement` 在 Task 3 定义，Task 4+5 使用 `useCallback` 返回 `KeyboardChatScrollView`，类型匹配。
