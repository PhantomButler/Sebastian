# Sebastian Android App (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 Sebastian Android App — a React Native (Expo) client that connects to the Sebastian Gateway for real-time conversation, Sub-Agent monitoring, and task control.

**Architecture:** Expo managed workflow with Expo Router for file-system routing. Zustand manages UI state and SSE-pushed incremental updates; React Query handles REST data fetching and caching. All business data lives on the server — the app is a pure display + control layer.

**Tech Stack:** Expo SDK 51+, Expo Router v3, Zustand 4, @tanstack/react-query 5, axios, react-native-gesture-handler, expo-secure-store, expo-notifications (FCM)

---

## File Map

```
ui/mobile/
├── app.json                                  # Expo config (bundle id, FCM, permissions)
├── package.json
├── tsconfig.json
├── app/
│   ├── _layout.tsx                           # Root layout: QueryClient + gesture handler + tab nav
│   └── (tabs)/
│       ├── _layout.tsx                       # Bottom tab bar (SubAgents | Chat | Settings)
│       ├── subagents/
│       │   ├── _layout.tsx
│       │   └── index.tsx                     # SubAgents page
│       ├── chat/
│       │   ├── _layout.tsx
│       │   └── index.tsx                     # Chat page
│       └── settings/
│           ├── _layout.tsx
│           └── index.tsx                     # Settings page
└── src/
    ├── types.ts                              # Shared TS types (Session, Message, Agent, Task, etc.)
    ├── api/
    │   ├── client.ts                         # axios instance, reads serverUrl from settings store
    │   ├── auth.ts                           # login(), logout()
    │   ├── turns.ts                          # sendTurn(), getSessions(), getMessages()
    │   ├── agents.ts                         # getAgents(), sendAgentCommand()
    │   ├── approvals.ts                      # getApprovals(), grantApproval(), denyApproval()
    │   └── sse.ts                            # createSSEConnection() — fetch-based streaming
    ├── store/
    │   ├── settings.ts                       # serverUrl, jwtToken, llmProvider (SecureStore backed)
    │   ├── session.ts                        # sessionIndex (max 20), currentSessionId, draftSession, streamingMessage
    │   └── agents.ts                         # activeAgents, currentAgentId, streamingOutput, isWorking
    ├── hooks/
    │   ├── useSessions.ts                    # React Query: fetch session list
    │   ├── useMessages.ts                    # React Query: fetch messages for a session
    │   ├── useAgents.ts                      # React Query: fetch active agents
    │   └── useSSE.ts                         # SSE lifecycle: connect/disconnect on foreground/background
    └── components/
        ├── common/
        │   ├── Sidebar.tsx                   # Gesture-driven slide-in sidebar container (reused by both pages)
        │   ├── EmptyState.tsx                # Empty state with icon + message + optional CTA
        │   └── StatusBadge.tsx               # Colored badge for task/agent status
        ├── chat/
        │   ├── ChatSidebar.tsx               # Session list + conditional "New Chat" button
        │   ├── MessageList.tsx               # FlatList of messages, auto-scroll to bottom
        │   ├── MessageBubble.tsx             # Single message bubble (user / assistant)
        │   ├── StreamingBubble.tsx           # Live-updating bubble during SSE stream
        │   └── MessageInput.tsx              # Floating input bar, idle/working states
        ├── subagents/
        │   ├── AgentSidebar.tsx              # Active agent list sidebar
        │   └── AgentStatusBadge.tsx          # Agent-specific status badge
        └── settings/
            ├── ServerConfig.tsx              # Server URL input + connection test
            ├── LLMProviderConfig.tsx         # Provider picker + API key input
            └── MemorySection.tsx             # Placeholder "Coming soon" section
```

---

## Tasks

### Task 1: 项目初始化

**Files:**
- Create: `ui/mobile/` (整个 Expo 项目目录)
- Create: `ui/mobile/app.json`
- Create: `ui/mobile/tsconfig.json`
- Create: `ui/mobile/app/_layout.tsx`
- Create: `ui/mobile/app/(tabs)/_layout.tsx`

- [ ] **Step 1: 创建 Expo 项目**

```bash
cd ui
npx create-expo-app mobile --template blank-typescript
cd mobile
```

- [ ] **Step 2: 安装依赖**

```bash
npx expo install expo-router react-native-safe-area-context react-native-screens expo-linking expo-constants expo-status-bar expo-secure-store expo-notifications react-native-gesture-handler react-native-reanimated
npm install zustand @tanstack/react-query axios
```

- [ ] **Step 3: 更新 tsconfig.json**

```json
{
  "extends": "expo/tsconfig.base",
  "compilerOptions": {
    "strict": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["**/*.ts", "**/*.tsx", ".expo/types/**/*.d.ts", "expo-env.d.ts"]
}
```

- [ ] **Step 4: 更新 app.json**

```json
{
  "expo": {
    "name": "Sebastian",
    "slug": "sebastian",
    "version": "1.0.0",
    "scheme": "sebastian",
    "platforms": ["android", "ios"],
    "android": {
      "package": "com.sebastian.app",
      "googleServicesFile": "./google-services.json"
    },
    "plugins": [
      "expo-router",
      "expo-secure-store",
      ["expo-notifications", { "icon": "./assets/notification-icon.png", "color": "#ffffff" }]
    ],
    "experiments": { "typedRoutes": true }
  }
}
```

- [ ] **Step 5: 创建 Root Layout `app/_layout.tsx`**

```tsx
import { Stack } from 'expo-router';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StyleSheet } from 'react-native';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 2, staleTime: 30_000 } },
});

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={styles.root}>
      <QueryClientProvider client={queryClient}>
        <Stack screenOptions={{ headerShown: false }} />
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
```

- [ ] **Step 6: 创建 Tab Layout `app/(tabs)/_layout.tsx`**

```tsx
import { Tabs } from 'expo-router';

export default function TabLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="subagents" options={{ title: 'SubAgents' }} />
      <Tabs.Screen name="chat" options={{ title: '对话' }} />
      <Tabs.Screen name="settings" options={{ title: '设置' }} />
    </Tabs>
  );
}
```

- [ ] **Step 7: 创建各 Tab 占位页面**

`app/(tabs)/chat/index.tsx`（subagents、settings 同理，函数名分别改为 `SubAgentsScreen`、`SettingsScreen`）：

```tsx
import { View, Text } from 'react-native';
export default function ChatScreen() {
  return <View><Text>Chat</Text></View>;
}
```

- [ ] **Step 8: 验证启动**

```bash
npx expo start --android
```

预期：Metro 启动，底部三 Tab 可见，无红屏。

- [ ] **Step 9: 提交**

```bash
git add ui/mobile/
git commit -m "feat(mobile): 初始化 Expo 项目，配置 Expo Router + Tab 导航

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: 共享类型定义

**Files:**
- Create: `ui/mobile/src/types.ts`

- [ ] **Step 1: 创建 `src/types.ts`**

```typescript
export type MessageRole = 'user' | 'assistant';

export interface Message {
  id: string;
  sessionId: string;
  role: MessageRole;
  content: string;
  createdAt: string;
}

export interface SessionMeta {
  id: string;
  title: string;
  createdAt: string;
}

export type AgentStatus = 'idle' | 'working' | 'waiting_approval' | 'completed' | 'failed';

export interface Agent {
  id: string;
  name: string;
  status: AgentStatus;
  goal: string;
  createdAt: string;
}

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface Task {
  id: string;
  goal: string;
  status: TaskStatus;
  agentId: string | null;
  createdAt: string;
  completedAt: string | null;
}

export interface Approval {
  id: string;
  taskId: string;
  description: string;
  requestedAt: string;
}

export type SSEEventType =
  | 'turn.delta' | 'turn.done'
  | 'agent.delta' | 'agent.done'
  | 'task.created' | 'task.updated' | 'task.completed' | 'task.failed'
  | 'approval.required';

export interface SSEEvent<T = unknown> {
  type: SSEEventType;
  data: T;
}

export interface TurnDeltaData { sessionId: string; delta: string; }
export interface AgentDeltaData { agentId: string; delta: string; }
export interface ApprovalRequiredData { approval: Approval; }

export type LLMProviderName = 'anthropic' | 'openai';
export interface LLMProvider { name: LLMProviderName; apiKey: string; }

export interface AuthResponse { token: string; }
export interface PaginatedMessages { items: Message[]; nextCursor: string | null; }
export interface PaginatedSessions { items: SessionMeta[]; nextCursor: string | null; }
```

- [ ] **Step 2: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 3: 提交**

```bash
git add ui/mobile/src/types.ts
git commit -m "feat(mobile): 添加共享 TypeScript 类型定义

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Settings Store

**Files:**
- Create: `ui/mobile/src/store/settings.ts`
- Modify: `ui/mobile/app/_layout.tsx`

- [ ] **Step 1: 创建 `src/store/settings.ts`**

```typescript
import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';
import type { LLMProvider } from '../types';

const KEYS = {
  serverUrl: 'settings_server_url',
  jwtToken: 'settings_jwt_token',
  llmProvider: 'settings_llm_provider',
} as const;

interface SettingsState {
  serverUrl: string;
  jwtToken: string | null;
  llmProvider: LLMProvider | null;
  isLoaded: boolean;
  load: () => Promise<void>;
  setServerUrl: (url: string) => Promise<void>;
  setJwtToken: (token: string | null) => Promise<void>;
  setLlmProvider: (provider: LLMProvider) => Promise<void>;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  serverUrl: '',
  jwtToken: null,
  llmProvider: null,
  isLoaded: false,

  load: async () => {
    const [serverUrl, jwtToken, raw] = await Promise.all([
      SecureStore.getItemAsync(KEYS.serverUrl),
      SecureStore.getItemAsync(KEYS.jwtToken),
      SecureStore.getItemAsync(KEYS.llmProvider),
    ]);
    set({
      serverUrl: serverUrl ?? '',
      jwtToken: jwtToken ?? null,
      llmProvider: raw ? (JSON.parse(raw) as LLMProvider) : null,
      isLoaded: true,
    });
  },

  setServerUrl: async (url) => {
    await SecureStore.setItemAsync(KEYS.serverUrl, url);
    set({ serverUrl: url });
  },

  setJwtToken: async (token) => {
    if (token === null) await SecureStore.deleteItemAsync(KEYS.jwtToken);
    else await SecureStore.setItemAsync(KEYS.jwtToken, token);
    set({ jwtToken: token });
  },

  setLlmProvider: async (provider) => {
    await SecureStore.setItemAsync(KEYS.llmProvider, JSON.stringify(provider));
    set({ llmProvider: provider });
  },
}));
```

- [ ] **Step 2: 更新 `app/_layout.tsx`，启动时加载 settings**

```tsx
import { Stack } from 'expo-router';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StyleSheet } from 'react-native';
import { useEffect } from 'react';
import { useSettingsStore } from '@/store/settings';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 2, staleTime: 30_000 } },
});

function AppInit({ children }: { children: React.ReactNode }) {
  const load = useSettingsStore((s) => s.load);
  useEffect(() => { load(); }, [load]);
  return <>{children}</>;
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={styles.root}>
      <QueryClientProvider client={queryClient}>
        <AppInit>
          <Stack screenOptions={{ headerShown: false }} />
        </AppInit>
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
```

- [ ] **Step 3: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 4: 提交**

```bash
git add ui/mobile/src/store/settings.ts ui/mobile/app/_layout.tsx
git commit -m "feat(mobile): 添加 Settings Store（Zustand + SecureStore 持久化）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: API 客户端

**Files:**
- Create: `ui/mobile/src/api/client.ts`

- [ ] **Step 1: 创建 `src/api/client.ts`**

```typescript
import axios from 'axios';
import { useSettingsStore } from '../store/settings';

export const apiClient = axios.create({
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

apiClient.interceptors.request.use((config) => {
  const { serverUrl, jwtToken } = useSettingsStore.getState();
  config.baseURL = serverUrl;
  if (jwtToken) config.headers.Authorization = `Bearer ${jwtToken}`;
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      await useSettingsStore.getState().setJwtToken(null);
    }
    return Promise.reject(error);
  },
);
```

- [ ] **Step 2: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 3: 提交**

```bash
git add ui/mobile/src/api/client.ts
git commit -m "feat(mobile): 添加 axios API 客户端（动态 baseURL + Bearer token + 401 处理）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: 认证 API + 设置页

**Files:**
- Create: `ui/mobile/src/api/auth.ts`
- Create: `ui/mobile/src/components/settings/ServerConfig.tsx`
- Create: `ui/mobile/src/components/settings/LLMProviderConfig.tsx`
- Create: `ui/mobile/src/components/settings/MemorySection.tsx`
- Modify: `ui/mobile/app/(tabs)/settings/index.tsx`

- [ ] **Step 1: 创建 `src/api/auth.ts`**

```typescript
import { apiClient } from './client';
import type { AuthResponse } from '../types';

export async function login(password: string): Promise<string> {
  const { data } = await apiClient.post<AuthResponse>('/api/v1/auth/login', { password });
  return data.token;
}

export async function logout(): Promise<void> {
  await apiClient.post('/api/v1/auth/logout');
}

export async function checkHealth(): Promise<boolean> {
  try {
    await apiClient.get('/api/v1/health');
    return true;
  } catch {
    return false;
  }
}
```

- [ ] **Step 2: 创建 `src/components/settings/ServerConfig.tsx`**

```tsx
import { useState } from 'react';
import { View, Text, TextInput, Button, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import { checkHealth } from '../../api/auth';

export function ServerConfig() {
  const { serverUrl, setServerUrl } = useSettingsStore();
  const [input, setInput] = useState(serverUrl);
  const [status, setStatus] = useState<'idle' | 'ok' | 'fail'>('idle');

  async function handleSave() {
    await setServerUrl(input.trim());
    const ok = await checkHealth();
    setStatus(ok ? 'ok' : 'fail');
  }

  return (
    <View style={styles.section}>
      <Text style={styles.label}>Server URL</Text>
      <TextInput
        style={styles.input}
        value={input}
        onChangeText={setInput}
        placeholder="http://192.168.1.x:8000"
        autoCapitalize="none"
        keyboardType="url"
      />
      <Button title="保存并测试" onPress={handleSave} />
      {status === 'ok' && <Text style={styles.ok}>连接成功</Text>}
      {status === 'fail' && <Text style={styles.fail}>连接失败</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginBottom: 24 },
  label: { fontWeight: 'bold', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, marginBottom: 8 },
  ok: { color: 'green' },
  fail: { color: 'red' },
});
```

- [ ] **Step 3: 创建 `src/components/settings/LLMProviderConfig.tsx`**

```tsx
import { useState } from 'react';
import { View, Text, TextInput, Button, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import type { LLMProviderName } from '../../types';

const PROVIDERS: LLMProviderName[] = ['anthropic', 'openai'];

export function LLMProviderConfig() {
  const { llmProvider, setLlmProvider } = useSettingsStore();
  const [name, setName] = useState<LLMProviderName>(llmProvider?.name ?? 'anthropic');
  const [apiKey, setApiKey] = useState(llmProvider?.apiKey ?? '');

  async function handleSave() {
    await setLlmProvider({ name, apiKey: apiKey.trim() });
  }

  return (
    <View style={styles.section}>
      <Text style={styles.label}>LLM Provider</Text>
      <View style={styles.row}>
        {PROVIDERS.map((p) => (
          <Button key={p} title={p} onPress={() => setName(p)} color={name === p ? '#007AFF' : '#999'} />
        ))}
      </View>
      <TextInput
        style={styles.input}
        value={apiKey}
        onChangeText={setApiKey}
        placeholder="API Key"
        secureTextEntry
        autoCapitalize="none"
      />
      <Button title="保存" onPress={handleSave} />
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginBottom: 24 },
  label: { fontWeight: 'bold', marginBottom: 4 },
  row: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  input: { borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, marginBottom: 8 },
});
```

- [ ] **Step 4: 创建 `src/components/settings/MemorySection.tsx`**

```tsx
import { View, Text, StyleSheet } from 'react-native';

export function MemorySection() {
  return (
    <View style={styles.section}>
      <Text style={styles.label}>Memory 管理</Text>
      <Text style={styles.placeholder}>即将推出</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginBottom: 24 },
  label: { fontWeight: 'bold', marginBottom: 4 },
  placeholder: { color: '#999' },
});
```

- [ ] **Step 5: 实现设置页 `app/(tabs)/settings/index.tsx`**

```tsx
import { useState } from 'react';
import { ScrollView, View, Text, TextInput, Button, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../../src/store/settings';
import { login, logout } from '../../../src/api/auth';
import { ServerConfig } from '../../../src/components/settings/ServerConfig';
import { LLMProviderConfig } from '../../../src/components/settings/LLMProviderConfig';
import { MemorySection } from '../../../src/components/settings/MemorySection';

export default function SettingsScreen() {
  const { jwtToken, setJwtToken } = useSettingsStore();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function handleLogin() {
    try {
      const token = await login(password);
      await setJwtToken(token);
      setPassword('');
      setError('');
    } catch {
      setError('登录失败，请检查密码');
    }
  }

  async function handleLogout() {
    try { await logout(); } catch { /* ignore */ }
    await setJwtToken(null);
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <ServerConfig />
      {jwtToken ? (
        <View style={styles.section}>
          <Text style={styles.label}>已登录</Text>
          <Button title="退出登录" onPress={handleLogout} color="red" />
        </View>
      ) : (
        <View style={styles.section}>
          <Text style={styles.label}>登录</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="密码"
            secureTextEntry
          />
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Button title="登录" onPress={handleLogin} />
        </View>
      )}
      <LLMProviderConfig />
      <MemorySection />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16 },
  section: { marginBottom: 24 },
  label: { fontWeight: 'bold', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, marginBottom: 8 },
  error: { color: 'red', marginBottom: 8 },
});
```

- [ ] **Step 6: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 7: 提交**

```bash
git add ui/mobile/src/api/auth.ts ui/mobile/src/components/settings/ ui/mobile/app/(tabs)/settings/index.tsx
git commit -m "feat(mobile): 添加认证 API 与设置页（ServerConfig、LLMProvider、登录/登出）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Session Store + turns API

**Files:**
- Create: `ui/mobile/src/store/session.ts`
- Create: `ui/mobile/src/api/turns.ts`
- Create: `ui/mobile/src/hooks/useSessions.ts`
- Create: `ui/mobile/src/hooks/useMessages.ts`

- [ ] **Step 1: 创建 `src/store/session.ts`**

```typescript
import { create } from 'zustand';
import type { SessionMeta } from '../types';

const MAX_SESSIONS = 20;

interface SessionState {
  sessionIndex: SessionMeta[];
  currentSessionId: string | null;
  draftSession: boolean;
  streamingMessage: string;
  setCurrentSession: (id: string | null) => void;
  startDraft: () => void;
  persistSession: (meta: SessionMeta) => void;
  appendStreamingDelta: (delta: string) => void;
  clearStreaming: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessionIndex: [],
  currentSessionId: null,
  draftSession: false,
  streamingMessage: '',

  setCurrentSession: (id) => set({ currentSessionId: id, draftSession: false }),

  startDraft: () => set({ currentSessionId: null, draftSession: true, streamingMessage: '' }),

  persistSession: (meta) =>
    set((state) => {
      const filtered = state.sessionIndex.filter((s) => s.id !== meta.id);
      const updated = [meta, ...filtered].slice(0, MAX_SESSIONS);
      return { sessionIndex: updated, currentSessionId: meta.id, draftSession: false };
    }),

  appendStreamingDelta: (delta) =>
    set((state) => ({ streamingMessage: state.streamingMessage + delta })),

  clearStreaming: () => set({ streamingMessage: '' }),
}));
```

- [ ] **Step 2: 创建 `src/api/turns.ts`**

```typescript
import { apiClient } from './client';
import type { Message, PaginatedMessages, PaginatedSessions, SessionMeta } from '../types';

export async function getSessions(): Promise<SessionMeta[]> {
  const { data } = await apiClient.get<PaginatedSessions>('/api/v1/sessions');
  return data.items;
}

export async function getMessages(sessionId: string): Promise<Message[]> {
  const { data } = await apiClient.get<PaginatedMessages>(`/api/v1/turns/${sessionId}`);
  return data.items;
}

export async function sendTurn(
  sessionId: string | null,
  content: string,
): Promise<{ sessionId: string }> {
  const { data } = await apiClient.post<{ sessionId: string }>('/api/v1/turns', {
    sessionId,
    content,
  });
  return data;
}

export async function cancelTurn(sessionId: string): Promise<void> {
  await apiClient.post(`/api/v1/sessions/${sessionId}/cancel`);
}
```

- [ ] **Step 3: 创建 `src/hooks/useSessions.ts`**

```typescript
import { useQuery } from '@tanstack/react-query';
import { getSessions } from '../api/turns';
import { useSettingsStore } from '../store/settings';

export function useSessions() {
  const jwtToken = useSettingsStore((s) => s.jwtToken);
  return useQuery({
    queryKey: ['sessions'],
    queryFn: getSessions,
    enabled: !!jwtToken,
  });
}
```

- [ ] **Step 4: 创建 `src/hooks/useMessages.ts`**

```typescript
import { useQuery } from '@tanstack/react-query';
import { getMessages } from '../api/turns';

export function useMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ['messages', sessionId],
    queryFn: () => getMessages(sessionId!),
    enabled: !!sessionId,
  });
}
```

- [ ] **Step 5: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 6: 提交**

```bash
git add ui/mobile/src/store/session.ts ui/mobile/src/api/turns.ts ui/mobile/src/hooks/useSessions.ts ui/mobile/src/hooks/useMessages.ts
git commit -m "feat(mobile): 添加 Session Store、turns API 与 React Query hooks

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 7: SSE 封装

**Files:**
- Create: `ui/mobile/src/api/sse.ts`
- Create: `ui/mobile/src/hooks/useSSE.ts`

- [ ] **Step 1: 创建 `src/api/sse.ts`**

```typescript
import { useSettingsStore } from '../store/settings';
import type { SSEEvent } from '../types';

export type SSEHandler = (event: SSEEvent) => void;

export function createSSEConnection(onEvent: SSEHandler, onError: (err: Error) => void): () => void {
  const { serverUrl, jwtToken } = useSettingsStore.getState();
  let active = true;
  const controller = new AbortController();

  (async () => {
    try {
      const response = await fetch(`${serverUrl}/api/v1/stream`, {
        headers: { Authorization: `Bearer ${jwtToken ?? ''}` },
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`SSE connect failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (active) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6)) as SSEEvent;
              onEvent(event);
            } catch { /* skip malformed */ }
          }
        }
      }
    } catch (err) {
      if (active) onError(err instanceof Error ? err : new Error(String(err)));
    }
  })();

  return () => {
    active = false;
    controller.abort();
  };
}
```

- [ ] **Step 2: 创建 `src/hooks/useSSE.ts`**

```typescript
import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';
import { createSSEConnection } from '../api/sse';
import { useSessionStore } from '../store/session';
import { useAgentsStore } from '../store/agents';
import { useSettingsStore } from '../store/settings';
import type { SSEEvent, TurnDeltaData, AgentDeltaData } from '../types';

const MAX_RETRIES = 3;
const BASE_DELAY = 1000;

export function useSSE() {
  const jwtToken = useSettingsStore((s) => s.jwtToken);
  const queryClient = useQueryClient();
  const retryCount = useRef(0);
  const disconnectRef = useRef<(() => void) | null>(null);

  function handleEvent(event: SSEEvent) {
    retryCount.current = 0;
    if (event.type === 'turn.delta') {
      const d = event.data as TurnDeltaData;
      useSessionStore.getState().appendStreamingDelta(d.delta);
    } else if (event.type === 'turn.done') {
      useSessionStore.getState().clearStreaming();
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    } else if (event.type === 'agent.delta') {
      const d = event.data as AgentDeltaData;
      useAgentsStore.getState().appendAgentDelta(d.agentId, d.delta);
    } else if (event.type === 'agent.done') {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
    } else if (event.type.startsWith('task.')) {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    }
  }

  function connect() {
    disconnectRef.current?.();
    disconnectRef.current = createSSEConnection(handleEvent, (err) => {
      console.warn('SSE error:', err);
      if (retryCount.current < MAX_RETRIES) {
        const delay = BASE_DELAY * 2 ** retryCount.current;
        retryCount.current += 1;
        setTimeout(connect, delay);
      }
    });
  }

  useEffect(() => {
    if (!jwtToken) return;
    connect();

    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        connect();
        queryClient.invalidateQueries();
      } else if (state === 'background') {
        disconnectRef.current?.();
        disconnectRef.current = null;
      }
    });

    return () => {
      disconnectRef.current?.();
      sub.remove();
    };
  }, [jwtToken]);
}
```

- [ ] **Step 3: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误（`useAgentsStore` 在 Task 10 实现，此处 TS 会报错，可先用 `// @ts-ignore` 占位，Task 10 完成后移除）。

- [ ] **Step 4: 提交**

```bash
git add ui/mobile/src/api/sse.ts ui/mobile/src/hooks/useSSE.ts
git commit -m "feat(mobile): 添加 SSE 封装（fetch streaming + 指数退避重连 + 前后台管理）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 8: 共用组件

**Files:**
- Create: `ui/mobile/src/components/common/Sidebar.tsx`
- Create: `ui/mobile/src/components/common/EmptyState.tsx`
- Create: `ui/mobile/src/components/common/StatusBadge.tsx`
- Create: `ui/mobile/src/components/chat/MessageBubble.tsx`
- Create: `ui/mobile/src/components/chat/StreamingBubble.tsx`
- Create: `ui/mobile/src/components/chat/MessageList.tsx`
- Create: `ui/mobile/src/components/chat/MessageInput.tsx`

- [ ] **Step 1: 创建 `src/components/common/Sidebar.tsx`**

手势驱动的侧边栏容器，左滑展开，点击遮罩关闭：

```tsx
import { useRef } from 'react';
import { Animated, Dimensions, StyleSheet, TouchableOpacity, View } from 'react-native';
import { PanGestureHandler, State } from 'react-native-gesture-handler';

const SIDEBAR_WIDTH = Dimensions.get('window').width * 0.75;

interface Props {
  visible: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

export function Sidebar({ visible, onClose, children }: Props) {
  const translateX = useRef(new Animated.Value(-SIDEBAR_WIDTH)).current;

  Animated.timing(translateX, {
    toValue: visible ? 0 : -SIDEBAR_WIDTH,
    duration: 250,
    useNativeDriver: true,
  }).start();

  if (!visible) return null;

  return (
    <View style={StyleSheet.absoluteFill}>
      <TouchableOpacity style={styles.overlay} activeOpacity={1} onPress={onClose} />
      <Animated.View style={[styles.sidebar, { transform: [{ translateX }] }]}>
        {children}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.4)' },
  sidebar: { position: 'absolute', left: 0, top: 0, bottom: 0, width: SIDEBAR_WIDTH, backgroundColor: '#fff' },
});
```

- [ ] **Step 2: 创建 `src/components/common/EmptyState.tsx`**

```tsx
import { View, Text, StyleSheet } from 'react-native';

interface Props {
  message: string;
  ctaLabel?: string;
  onCta?: () => void;
}

export function EmptyState({ message, ctaLabel, onCta }: Props) {
  return (
    <View style={styles.container}>
      <Text style={styles.message}>{message}</Text>
      {ctaLabel && onCta && (
        <Text style={styles.cta} onPress={onCta}>{ctaLabel}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  message: { color: '#999', textAlign: 'center', marginBottom: 12 },
  cta: { color: '#007AFF', fontWeight: 'bold' },
});
```

- [ ] **Step 3: 创建 `src/components/common/StatusBadge.tsx`**

```tsx
import { Text, StyleSheet } from 'react-native';
import type { AgentStatus, TaskStatus } from '../../types';

const COLOR: Record<string, string> = {
  idle: '#999',
  working: '#007AFF',
  waiting_approval: '#FF9500',
  completed: '#34C759',
  failed: '#FF3B30',
  pending: '#999',
  running: '#007AFF',
  cancelled: '#999',
};

interface Props { status: AgentStatus | TaskStatus; }

export function StatusBadge({ status }: Props) {
  return (
    <Text style={[styles.badge, { backgroundColor: COLOR[status] ?? '#999' }]}>
      {status}
    </Text>
  );
}

const styles = StyleSheet.create({
  badge: { color: '#fff', fontSize: 11, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, overflow: 'hidden' },
});
```

- [ ] **Step 4: 创建 `src/components/chat/MessageBubble.tsx`**

```tsx
import { View, Text, StyleSheet } from 'react-native';
import type { Message } from '../../types';

interface Props { message: Message; }

export function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';
  return (
    <View style={[styles.row, isUser ? styles.rowUser : styles.rowAssistant]}>
      <View style={[styles.bubble, isUser ? styles.bubbleUser : styles.bubbleAssistant]}>
        <Text style={isUser ? styles.textUser : styles.textAssistant}>{message.content}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 12, paddingVertical: 4 },
  rowUser: { alignItems: 'flex-end' },
  rowAssistant: { alignItems: 'flex-start' },
  bubble: { maxWidth: '80%', borderRadius: 16, padding: 10 },
  bubbleUser: { backgroundColor: '#007AFF' },
  bubbleAssistant: { backgroundColor: '#F0F0F0' },
  textUser: { color: '#fff' },
  textAssistant: { color: '#000' },
});
```

- [ ] **Step 5: 创建 `src/components/chat/StreamingBubble.tsx`**

```tsx
import { View, Text, StyleSheet } from 'react-native';

interface Props { content: string; }

export function StreamingBubble({ content }: Props) {
  if (!content) return null;
  return (
    <View style={styles.row}>
      <View style={styles.bubble}>
        <Text style={styles.text}>{content}</Text>
        <Text style={styles.cursor}>▋</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 12, paddingVertical: 4, alignItems: 'flex-start' },
  bubble: { maxWidth: '80%', borderRadius: 16, padding: 10, backgroundColor: '#F0F0F0', flexDirection: 'row', flexWrap: 'wrap' },
  text: { color: '#000' },
  cursor: { color: '#007AFF' },
});
```

- [ ] **Step 6: 创建 `src/components/chat/MessageList.tsx`**

```tsx
import { FlatList, StyleSheet, View } from 'react-native';
import type { Message } from '../../types';
import { MessageBubble } from './MessageBubble';
import { StreamingBubble } from './StreamingBubble';

interface Props {
  messages: Message[];
  streamingContent?: string;
}

export function MessageList({ messages, streamingContent }: Props) {
  return (
    <FlatList
      data={messages}
      keyExtractor={(m) => m.id}
      renderItem={({ item }) => <MessageBubble message={item} />}
      ListFooterComponent={
        streamingContent ? <StreamingBubble content={streamingContent} /> : null
      }
      contentContainerStyle={styles.content}
      onContentSizeChange={() => {}}
      maintainVisibleContentPosition={{ minIndexForVisible: 0 }}
    />
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 80 },
});
```

- [ ] **Step 7: 创建 `src/components/chat/MessageInput.tsx`**

```tsx
import { useState } from 'react';
import { View, TextInput, TouchableOpacity, Text, StyleSheet } from 'react-native';

interface Props {
  isWorking: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

export function MessageInput({ isWorking, onSend, onStop }: Props) {
  const [text, setText] = useState('');

  function handleSubmit() {
    if (isWorking) { onStop(); return; }
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText('');
  }

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.input}
        value={text}
        onChangeText={setText}
        placeholder="发消息…"
        multiline
        onSubmitEditing={isWorking ? undefined : handleSubmit}
        blurOnSubmit={false}
      />
      <TouchableOpacity style={[styles.btn, isWorking && styles.btnStop]} onPress={handleSubmit}>
        <Text style={styles.btnText}>{isWorking ? '■' : '↑'}</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { position: 'absolute', bottom: 0, left: 0, right: 0, flexDirection: 'row', padding: 8, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: '#eee' },
  input: { flex: 1, borderWidth: 1, borderColor: '#ccc', borderRadius: 20, paddingHorizontal: 14, paddingVertical: 8, maxHeight: 100 },
  btn: { width: 36, height: 36, borderRadius: 18, backgroundColor: '#007AFF', alignItems: 'center', justifyContent: 'center', marginLeft: 8, alignSelf: 'flex-end' },
  btnStop: { backgroundColor: '#FF3B30' },
  btnText: { color: '#fff', fontWeight: 'bold' },
});
```

- [ ] **Step 8: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 9: 提交**

```bash
git add ui/mobile/src/components/
git commit -m "feat(mobile): 添加共用组件（Sidebar、EmptyState、StatusBadge、MessageBubble、StreamingBubble、MessageList、MessageInput）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 9: 对话页

**Files:**
- Create: `ui/mobile/src/components/chat/ChatSidebar.tsx`
- Modify: `ui/mobile/app/(tabs)/chat/index.tsx`

- [ ] **Step 1: 创建 `src/components/chat/ChatSidebar.tsx`**

```tsx
import { FlatList, View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import type { SessionMeta } from '../../types';

interface Props {
  sessions: SessionMeta[];
  currentSessionId: string | null;
  draftSession: boolean;
  onSelect: (id: string) => void;
  onNewChat: () => void;
}

export function ChatSidebar({ sessions, currentSessionId, draftSession, onSelect, onNewChat }: Props) {
  const showNewChat = !draftSession && (sessions.length > 0 || currentSessionId !== null);

  return (
    <View style={styles.container}>
      {showNewChat && (
        <TouchableOpacity style={styles.newBtn} onPress={onNewChat}>
          <Text style={styles.newBtnText}>+ 新对话</Text>
        </TouchableOpacity>
      )}
      <FlatList
        data={sessions}
        keyExtractor={(s) => s.id}
        renderItem={({ item }) => (
          <TouchableOpacity
            style={[styles.item, item.id === currentSessionId && styles.itemActive]}
            onPress={() => onSelect(item.id)}
          >
            <Text style={styles.itemTitle} numberOfLines={1}>{item.title || '新对话'}</Text>
            <Text style={styles.itemDate}>{new Date(item.createdAt).toLocaleDateString()}</Text>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, paddingTop: 48 },
  newBtn: { margin: 12, padding: 10, backgroundColor: '#007AFF', borderRadius: 8, alignItems: 'center' },
  newBtnText: { color: '#fff', fontWeight: 'bold' },
  item: { padding: 14, borderBottomWidth: 1, borderBottomColor: '#eee' },
  itemActive: { backgroundColor: '#E8F0FE' },
  itemTitle: { fontWeight: '500' },
  itemDate: { color: '#999', fontSize: 12, marginTop: 2 },
});
```

- [ ] **Step 2: 实现对话页 `app/(tabs)/chat/index.tsx`**

```tsx
import { useState } from 'react';
import { View, StyleSheet } from 'react-native';
import { useSessionStore } from '../../../src/store/session';
import { useMessages } from '../../../src/hooks/useMessages';
import { useSessions } from '../../../src/hooks/useSessions';
import { useSSE } from '../../../src/hooks/useSSE';
import { sendTurn, cancelTurn } from '../../../src/api/turns';
import { useQueryClient } from '@tanstack/react-query';
import { Sidebar } from '../../../src/components/common/Sidebar';
import { EmptyState } from '../../../src/components/common/EmptyState';
import { ChatSidebar } from '../../../src/components/chat/ChatSidebar';
import { MessageList } from '../../../src/components/chat/MessageList';
import { MessageInput } from '../../../src/components/chat/MessageInput';

export default function ChatScreen() {
  useSSE();
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { currentSessionId, draftSession, streamingMessage, setCurrentSession, startDraft, persistSession } = useSessionStore();
  const { data: sessions = [] } = useSessions();
  const { data: messages = [] } = useMessages(currentSessionId);
  const isWorking = !!streamingMessage;

  async function handleSend(text: string) {
    const { sessionId } = await sendTurn(currentSessionId, text);
    if (!currentSessionId) {
      persistSession({ id: sessionId, title: text.slice(0, 30), createdAt: new Date().toISOString() });
    }
    queryClient.invalidateQueries({ queryKey: ['messages', sessionId] });
  }

  async function handleStop() {
    if (currentSessionId) await cancelTurn(currentSessionId);
  }

  const isEmpty = !currentSessionId && !draftSession;

  return (
    <View style={styles.container}>
      {isEmpty ? (
        <EmptyState message="发送消息开始对话" />
      ) : (
        <MessageList messages={messages} streamingContent={streamingMessage} />
      )}
      <MessageInput isWorking={isWorking} onSend={handleSend} onStop={handleStop} />
      <Sidebar visible={sidebarOpen} onClose={() => setSidebarOpen(false)}>
        <ChatSidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          draftSession={draftSession}
          onSelect={(id) => { setCurrentSession(id); setSidebarOpen(false); }}
          onNewChat={() => { startDraft(); setSidebarOpen(false); }}
        />
      </Sidebar>
    </View>
  );
}

const styles = StyleSheet.create({ container: { flex: 1 } });
```

- [ ] **Step 3: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 4: 提交**

```bash
git add ui/mobile/src/components/chat/ChatSidebar.tsx ui/mobile/app/(tabs)/chat/index.tsx
git commit -m "feat(mobile): 实现对话页（Session 生命周期、草稿逻辑、SSE 流式显示）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 10: Agents Store + agents API

**Files:**
- Create: `ui/mobile/src/store/agents.ts`
- Create: `ui/mobile/src/api/agents.ts`
- Create: `ui/mobile/src/hooks/useAgents.ts`

- [ ] **Step 1: 创建 `src/store/agents.ts`**

```typescript
import { create } from 'zustand';
import type { Agent } from '../types';

interface AgentsState {
  activeAgents: Agent[];
  currentAgentId: string | null;
  streamingOutput: string;
  isWorking: boolean;
  setActiveAgents: (agents: Agent[]) => void;
  setCurrentAgent: (id: string | null) => void;
  appendAgentDelta: (agentId: string, delta: string) => void;
  clearAgentOutput: () => void;
  setIsWorking: (working: boolean) => void;
}

export const useAgentsStore = create<AgentsState>((set, get) => ({
  activeAgents: [],
  currentAgentId: null,
  streamingOutput: '',
  isWorking: false,

  setActiveAgents: (agents) => set({ activeAgents: agents }),

  setCurrentAgent: (id) => set({ currentAgentId: id, streamingOutput: '' }),

  appendAgentDelta: (agentId, delta) => {
    if (get().currentAgentId === agentId) {
      set((state) => ({ streamingOutput: state.streamingOutput + delta }));
    }
  },

  clearAgentOutput: () => set({ streamingOutput: '' }),

  setIsWorking: (working) => set({ isWorking: working }),
}));
```

- [ ] **Step 2: 创建 `src/api/agents.ts`**

```typescript
import { apiClient } from './client';
import type { Agent } from '../types';

export async function getAgents(): Promise<Agent[]> {
  const { data } = await apiClient.get<Agent[]>('/api/v1/agents');
  return data;
}

export async function sendAgentCommand(agentId: string, content: string): Promise<void> {
  await apiClient.post(`/api/v1/agents/${agentId}/command`, { content });
}

export async function cancelAgent(agentId: string): Promise<void> {
  await apiClient.post(`/api/v1/agents/${agentId}/cancel`);
}
```

- [ ] **Step 3: 创建 `src/hooks/useAgents.ts`**

```typescript
import { useQuery } from '@tanstack/react-query';
import { getAgents } from '../api/agents';
import { useSettingsStore } from '../store/settings';

export function useAgents() {
  const jwtToken = useSettingsStore((s) => s.jwtToken);
  return useQuery({
    queryKey: ['agents'],
    queryFn: getAgents,
    enabled: !!jwtToken,
  });
}
```

- [ ] **Step 4: 移除 useSSE.ts 中的 `// @ts-ignore` 占位（如有）**

确认 `src/hooks/useSSE.ts` 中 `useAgentsStore` 导入正常，无 ts-ignore 注释。

- [ ] **Step 5: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 6: 提交**

```bash
git add ui/mobile/src/store/agents.ts ui/mobile/src/api/agents.ts ui/mobile/src/hooks/useAgents.ts
git commit -m "feat(mobile): 添加 Agents Store、agents API 与 React Query hook

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 11: SubAgents 页

**Files:**
- Create: `ui/mobile/src/components/subagents/AgentSidebar.tsx`
- Create: `ui/mobile/src/components/subagents/AgentStatusBadge.tsx`
- Modify: `ui/mobile/app/(tabs)/subagents/index.tsx`

- [ ] **Step 1: 创建 `src/components/subagents/AgentStatusBadge.tsx`**

```tsx
import { Text, StyleSheet } from 'react-native';
import type { AgentStatus } from '../../types';

const COLOR: Record<AgentStatus, string> = {
  idle: '#999',
  working: '#007AFF',
  waiting_approval: '#FF9500',
  completed: '#34C759',
  failed: '#FF3B30',
};

interface Props { status: AgentStatus; }

export function AgentStatusBadge({ status }: Props) {
  return (
    <Text style={[styles.badge, { backgroundColor: COLOR[status] }]}>{status}</Text>
  );
}

const styles = StyleSheet.create({
  badge: { color: '#fff', fontSize: 11, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, overflow: 'hidden' },
});
```

- [ ] **Step 2: 创建 `src/components/subagents/AgentSidebar.tsx`**

```tsx
import { FlatList, View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import type { Agent } from '../../types';
import { AgentStatusBadge } from './AgentStatusBadge';

interface Props {
  agents: Agent[];
  currentAgentId: string | null;
  onSelect: (id: string) => void;
}

export function AgentSidebar({ agents, currentAgentId, onSelect }: Props) {
  return (
    <View style={styles.container}>
      <Text style={styles.header}>Sub-Agents</Text>
      <FlatList
        data={agents}
        keyExtractor={(a) => a.id}
        renderItem={({ item }) => (
          <TouchableOpacity
            style={[styles.item, item.id === currentAgentId && styles.itemActive]}
            onPress={() => onSelect(item.id)}
          >
            <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
            <AgentStatusBadge status={item.status} />
          </TouchableOpacity>
        )}
        ListEmptyComponent={<Text style={styles.empty}>暂无活跃 Agent</Text>}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, paddingTop: 48 },
  header: { fontWeight: 'bold', fontSize: 16, padding: 14 },
  item: { padding: 14, borderBottomWidth: 1, borderBottomColor: '#eee', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  itemActive: { backgroundColor: '#E8F0FE' },
  name: { flex: 1, marginRight: 8 },
  empty: { color: '#999', padding: 14 },
});
```

- [ ] **Step 3: 实现 SubAgents 页 `app/(tabs)/subagents/index.tsx`**

```tsx
import { useState } from 'react';
import { View, StyleSheet } from 'react-native';
import { useAgentsStore } from '../../../src/store/agents';
import { useAgents } from '../../../src/hooks/useAgents';
import { sendAgentCommand, cancelAgent } from '../../../src/api/agents';
import { Sidebar } from '../../../src/components/common/Sidebar';
import { EmptyState } from '../../../src/components/common/EmptyState';
import { AgentSidebar } from '../../../src/components/subagents/AgentSidebar';
import { MessageList } from '../../../src/components/chat/MessageList';
import { MessageInput } from '../../../src/components/chat/MessageInput';

export default function SubAgentsScreen() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { currentAgentId, streamingOutput, isWorking, setCurrentAgent } = useAgentsStore();
  const { data: agents = [] } = useAgents();

  async function handleSend(text: string) {
    if (!currentAgentId) return;
    await sendAgentCommand(currentAgentId, text);
  }

  async function handleStop() {
    if (!currentAgentId) return;
    await cancelAgent(currentAgentId);
  }

  return (
    <View style={styles.container}>
      {!currentAgentId ? (
        <EmptyState message="从左侧选择一个 Sub-Agent 查看输出" />
      ) : (
        <MessageList messages={[]} streamingContent={streamingOutput} />
      )}
      <MessageInput isWorking={isWorking} onSend={handleSend} onStop={handleStop} />
      <Sidebar visible={sidebarOpen} onClose={() => setSidebarOpen(false)}>
        <AgentSidebar
          agents={agents}
          currentAgentId={currentAgentId}
          onSelect={(id) => { setCurrentAgent(id); setSidebarOpen(false); }}
        />
      </Sidebar>
    </View>
  );
}

const styles = StyleSheet.create({ container: { flex: 1 } });
```

- [ ] **Step 4: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 5: 提交**

```bash
git add ui/mobile/src/components/subagents/ ui/mobile/app/(tabs)/subagents/index.tsx
git commit -m "feat(mobile): 实现 SubAgents 页（AgentSidebar + 复用 MessageList/MessageInput）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 12: FCM 推送

**Files:**
- Create: `ui/mobile/src/api/approvals.ts`
- Modify: `ui/mobile/app/_layout.tsx`

- [ ] **Step 1: 创建 `src/api/approvals.ts`**

```typescript
import { apiClient } from './client';
import type { Approval } from '../types';

export async function registerDevice(fcmToken: string): Promise<void> {
  await apiClient.post('/api/v1/devices', { fcm_token: fcmToken, platform: 'android' });
}

export async function getApprovals(): Promise<Approval[]> {
  const { data } = await apiClient.get<Approval[]>('/api/v1/approvals');
  return data;
}

export async function grantApproval(approvalId: string): Promise<void> {
  await apiClient.post(`/api/v1/approvals/${approvalId}/grant`);
}

export async function denyApproval(approvalId: string): Promise<void> {
  await apiClient.post(`/api/v1/approvals/${approvalId}/deny`);
}
```

- [ ] **Step 2: 在 Root Layout 中注册 FCM token**

修改 `app/_layout.tsx`，在 `AppInit` 中加入 FCM 注册逻辑：

```tsx
import { Stack } from 'expo-router';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StyleSheet } from 'react-native';
import { useEffect } from 'react';
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useSettingsStore } from '@/store/settings';
import { registerDevice } from '@/api/approvals';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 2, staleTime: 30_000 } },
});

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: false }),
});

function AppInit({ children }: { children: React.ReactNode }) {
  const { load, jwtToken } = useSettingsStore();

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!jwtToken) return;
    (async () => {
      const { status } = await Notifications.requestPermissionsAsync();
      if (status !== 'granted') return;
      const token = (await Notifications.getExpoPushTokenAsync()).data;
      await registerDevice(token).catch(() => {});
    })();
  }, [jwtToken]);

  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = response.notification.request.content.data as Record<string, string>;
      if (data?.type === 'approval.required') router.push('/(tabs)/chat');
      else if (data?.type?.startsWith('task.')) router.push('/(tabs)/subagents');
    });
    return () => sub.remove();
  }, []);

  return <>{children}</>;
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={styles.root}>
      <QueryClientProvider client={queryClient}>
        <AppInit>
          <Stack screenOptions={{ headerShown: false }} />
        </AppInit>
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
```

- [ ] **Step 3: 验证**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 4: 提交**

```bash
git add ui/mobile/src/api/approvals.ts ui/mobile/app/_layout.tsx
git commit -m "feat(mobile): 添加 FCM 推送注册与通知点击路由

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 13: 端到端冒烟测试

**Files:** 无新文件，验证整体集成。

- [ ] **Step 1: 启动 Sebastian Gateway（本地）**

```bash
cd E:/App/Coding/AI/Sebastian
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload
```

- [ ] **Step 2: 启动 App**

```bash
cd ui/mobile
npx expo start --android
```

- [ ] **Step 3: 设置页验证**

1. 填写 Server URL `http://127.0.0.1:8000` → 点击"保存并测试" → 显示"连接成功"
2. 填写密码 → 点击"登录" → 显示"已登录"
3. 选择 LLM Provider + 填写 API Key → 点击"保存"

- [ ] **Step 4: 对话页验证**

1. 切换到"对话" Tab → 显示空状态
2. 输入消息 → 点击发送 → 消息出现在列表，服务端返回流式响应，StreamingBubble 实时更新
3. 流式结束后 StreamingBubble 消失，完整消息出现
4. 左滑 → ChatSidebar 出现，显示刚创建的 Session
5. 点击"+ 新对话" → 草稿状态，按钮消失

- [ ] **Step 5: SubAgents 页验证**

1. 切换到"SubAgents" Tab → 显示空状态提示
2. 左滑 → AgentSidebar 出现（若有活跃 Agent 则显示列表）
3. 选中 Agent → 主区域显示该 Agent 输出流

- [ ] **Step 6: 后台/前台 SSE 验证**

1. App 切到后台 → 等待 5 秒 → 切回前台
2. 观察：React Query 自动刷新，消息列表补齐断开期间的内容

- [ ] **Step 7: 最终提交（如有遗漏文件）**

```bash
git add ui/mobile/
git commit -m "feat(mobile): Phase 1 Android App 完整实现

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
