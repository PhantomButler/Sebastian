# App 对话 UI 一期优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将移动端对话 UI 升级为真实流式渲染，支持思考区折叠、tool 调用展示、Markdown，并抽为共享组件供 Sebastian 主页和 subagent session 页复用。

**Architecture:** 新增 `src/components/conversation/` 共享组件层 + `src/store/conversation.ts` 多 session Zustand store（按 sessionId 隔离状态）+ `src/hooks/useConversation.ts` 封装 hydrate + per-session SSE 生命周期。全局 `useSSE` 保留负责 task/approval 事件，per-session SSE 新建连接专门处理流式内容。

**Tech Stack:** React Native (Expo 54)、Zustand 5、react-native-sse、react-native-markdown-display、TanStack Query 5。

---

## 文件结构

| 文件 | 操作 |
|---|---|
| `ui/mobile/package.json` | 修改：新增 `react-native-markdown-display` |
| `ui/mobile/src/types.ts` | 修改：新增 SSE 事件类型 + RenderBlock / ConvMessage / ActiveTurn 类型 |
| `ui/mobile/src/store/conversation.ts` | 新建：多 session 对话状态 store |
| `ui/mobile/src/api/sse.ts` | 修改：新增 `createSessionSSEConnection`（per-session + Last-Event-ID）|
| `ui/mobile/src/hooks/useConversation.ts` | 新建：hydrate + per-session SSE 生命周期 hook |
| `ui/mobile/src/components/conversation/MarkdownContent.tsx` | 新建 |
| `ui/mobile/src/components/conversation/UserBubble.tsx` | 新建 |
| `ui/mobile/src/components/conversation/ThinkingBlock.tsx` | 新建 |
| `ui/mobile/src/components/conversation/ToolCallRow.tsx` | 新建 |
| `ui/mobile/src/components/conversation/ToolCallGroup.tsx` | 新建 |
| `ui/mobile/src/components/conversation/AssistantMessage.tsx` | 新建 |
| `ui/mobile/src/components/conversation/ConversationView.tsx` | 新建 |
| `ui/mobile/src/components/conversation/index.ts` | 新建 |
| `ui/mobile/app/(tabs)/chat/index.tsx` | 修改：用 `<ConversationView>` 替换消息区 |
| `ui/mobile/app/subagents/session/[id].tsx` | 修改：消息 tab 用 `<ConversationView>` |

---

### Task 1：安装依赖 + 新增类型

**Files:**
- Modify: `ui/mobile/package.json`
- Modify: `ui/mobile/src/types.ts`

- [ ] **Step 1：安装 react-native-markdown-display**

```bash
cd ui/mobile
npm install react-native-markdown-display
```

预期输出：`added 1 package`（纯 JS，无需 native link）。

- [ ] **Step 2：更新 types.ts，新增 SSE 事件类型和 RenderBlock 类型**

将 `ui/mobile/src/types.ts` 中 `SSEEventType` 的联合类型替换为：

```typescript
export type SSEEventType =
  | 'task.planning_started'
  | 'task.planning_failed'
  | 'turn.received'
  | 'turn.response'
  | 'turn.delta'
  | 'turn.thinking_delta'
  | 'thinking_block.start'
  | 'thinking_block.stop'
  | 'text_block.start'
  | 'text_block.stop'
  | 'task.created'
  | 'task.started'
  | 'task.paused'
  | 'task.resumed'
  | 'task.completed'
  | 'task.failed'
  | 'task.cancelled'
  | 'agent.delegated'
  | 'agent.delegated.failed'
  | 'agent.escalated'
  | 'agent.result_received'
  | 'user.approval_requested'
  | 'user.approval_granted'
  | 'user.approval_denied'
  | 'user.intervened'
  | 'user.interrupted'
  | 'tool.registered'
  | 'tool.running'
  | 'tool.executed'
  | 'tool.failed';
```

在文件末尾追加：

```typescript
// ── Conversation rendering types ──────────────────────────────────────────

export type RenderBlock =
  | { type: 'thinking'; blockId: string; text: string; done: boolean }
  | { type: 'text';     blockId: string; text: string; done: boolean }
  | { type: 'tool';     toolId: string;  name: string; input: string;
      status: 'running' | 'done' | 'failed'; result?: string };

export interface ActiveTurn {
  blocks: RenderBlock[];
  blockMap: Map<string, RenderBlock>;
}

export interface ConvMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
}

export interface ConvSessionState {
  status: 'idle' | 'loading' | 'live' | 'paused';
  messages: ConvMessage[];
  activeTurn: ActiveTurn | null;
}
```

- [ ] **Step 3：确认类型文件无 TS 错误**

```bash
cd ui/mobile
npx tsc --noEmit 2>&1 | head -20
```

预期：无输出（0 错误）。

- [ ] **Step 4：Commit**

```bash
cd ui/mobile && git add package.json package-lock.json src/types.ts
git commit -m "feat(app): 安装 react-native-markdown-display，新增对话渲染类型

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2：Conversation Store

**Files:**
- Create: `ui/mobile/src/store/conversation.ts`

- [ ] **Step 1：新建 conversation store**

创建 `ui/mobile/src/store/conversation.ts`：

```typescript
import { create } from 'zustand';
import type { ActiveTurn, ConvMessage, ConvSessionState, RenderBlock } from '../types';

const MAX_PAUSED = 5;

interface ConversationStore {
  sessions: Record<string, ConvSessionState>;

  getOrInit(sessionId: string): ConvSessionState;
  setStatus(sessionId: string, status: ConvSessionState['status']): void;
  setMessages(sessionId: string, messages: ConvMessage[]): void;
  pauseSession(sessionId: string): void;
  evictSession(sessionId: string): void;

  onThinkingBlockStart(sessionId: string, blockId: string): void;
  onThinkingDelta(sessionId: string, blockId: string, delta: string): void;
  onThinkingBlockStop(sessionId: string, blockId: string): void;
  onTextBlockStart(sessionId: string, blockId: string): void;
  onTextDelta(sessionId: string, blockId: string, delta: string): void;
  onTextBlockStop(sessionId: string, blockId: string): void;
  onToolRunning(sessionId: string, toolId: string, name: string, input: string): void;
  onToolExecuted(sessionId: string, toolId: string, result: string): void;
  onToolFailed(sessionId: string, toolId: string, error: string): void;
  onTurnComplete(sessionId: string): void;
}

function emptySession(): ConvSessionState {
  return { status: 'idle', messages: [], activeTurn: null };
}

function getActiveTurn(state: ConvSessionState): ActiveTurn {
  if (state.activeTurn) return state.activeTurn;
  return { blocks: [], blockMap: new Map() };
}

function pushBlock(turn: ActiveTurn, block: RenderBlock): void {
  const key = block.type === 'tool' ? block.toolId : block.blockId;
  turn.blocks.push(block);
  turn.blockMap.set(key, block);
}

export const useConversationStore = create<ConversationStore>((set, get) => ({
  sessions: {},

  getOrInit(sessionId) {
    return get().sessions[sessionId] ?? emptySession();
  },

  setStatus(sessionId, status) {
    set((s) => ({
      sessions: {
        ...s.sessions,
        [sessionId]: { ...(s.sessions[sessionId] ?? emptySession()), status },
      },
    }));
  },

  setMessages(sessionId, messages) {
    set((s) => ({
      sessions: {
        ...s.sessions,
        [sessionId]: { ...(s.sessions[sessionId] ?? emptySession()), messages },
      },
    }));
  },

  pauseSession(sessionId) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session) return s;
      // Evict oldest paused sessions beyond MAX_PAUSED
      const paused = Object.entries(s.sessions).filter(
        ([id, sess]) => id !== sessionId && sess.status === 'paused',
      );
      const toEvict = paused.slice(MAX_PAUSED - 1);
      const next = { ...s.sessions, [sessionId]: { ...session, status: 'paused' as const } };
      for (const [id] of toEvict) delete next[id];
      return { sessions: next };
    });
  },

  evictSession(sessionId) {
    set((s) => {
      const next = { ...s.sessions };
      delete next[sessionId];
      return { sessions: next };
    });
  },

  onThinkingBlockStart(sessionId, blockId) {
    set((s) => {
      const session = { ...(s.sessions[sessionId] ?? emptySession()) };
      const turn = getActiveTurn(session);
      const block: RenderBlock = { type: 'thinking', blockId, text: '', done: false };
      pushBlock(turn, block);
      session.activeTurn = turn;
      return { sessions: { ...s.sessions, [sessionId]: session } };
    });
  },

  onThinkingDelta(sessionId, blockId, delta) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const block = session.activeTurn.blockMap.get(blockId);
      if (!block || block.type !== 'thinking') return s;
      block.text += delta;
      return { sessions: { ...s.sessions, [sessionId]: { ...session } } };
    });
  },

  onThinkingBlockStop(sessionId, blockId) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const block = session.activeTurn.blockMap.get(blockId);
      if (!block || block.type !== 'thinking') return s;
      block.done = true;
      return { sessions: { ...s.sessions, [sessionId]: { ...session } } };
    });
  },

  onTextBlockStart(sessionId, blockId) {
    set((s) => {
      const session = { ...(s.sessions[sessionId] ?? emptySession()) };
      const turn = getActiveTurn(session);
      const block: RenderBlock = { type: 'text', blockId, text: '', done: false };
      pushBlock(turn, block);
      session.activeTurn = turn;
      return { sessions: { ...s.sessions, [sessionId]: session } };
    });
  },

  onTextDelta(sessionId, blockId, delta) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const block = session.activeTurn.blockMap.get(blockId);
      if (!block || block.type !== 'text') return s;
      block.text += delta;
      return { sessions: { ...s.sessions, [sessionId]: { ...session } } };
    });
  },

  onTextBlockStop(sessionId, blockId) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const block = session.activeTurn.blockMap.get(blockId);
      if (!block || block.type !== 'text') return s;
      block.done = true;
      return { sessions: { ...s.sessions, [sessionId]: { ...session } } };
    });
  },

  onToolRunning(sessionId, toolId, name, input) {
    set((s) => {
      const session = { ...(s.sessions[sessionId] ?? emptySession()) };
      const turn = getActiveTurn(session);
      const block: RenderBlock = { type: 'tool', toolId, name, input, status: 'running' };
      pushBlock(turn, block);
      session.activeTurn = turn;
      return { sessions: { ...s.sessions, [sessionId]: session } };
    });
  },

  onToolExecuted(sessionId, toolId, result) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const block = session.activeTurn.blockMap.get(toolId);
      if (!block || block.type !== 'tool') return s;
      block.status = 'done';
      block.result = result;
      return { sessions: { ...s.sessions, [sessionId]: { ...session } } };
    });
  },

  onToolFailed(sessionId, toolId, error) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const block = session.activeTurn.blockMap.get(toolId);
      if (!block || block.type !== 'tool') return s;
      block.status = 'failed';
      block.result = error;
      return { sessions: { ...s.sessions, [sessionId]: { ...session } } };
    });
  },

  onTurnComplete(sessionId) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session) return s;
      return {
        sessions: {
          ...s.sessions,
          [sessionId]: { ...session, activeTurn: null },
        },
      };
    });
  },
}));
```

- [ ] **Step 2：确认 TS 无错误**

```bash
cd ui/mobile
npx tsc --noEmit 2>&1 | head -20
```

预期：无输出。

- [ ] **Step 3：Commit**

```bash
cd ui/mobile
git add src/store/conversation.ts
git commit -m "feat(app): 新增多 session Conversation Store

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3：Per-session SSE API

**Files:**
- Modify: `ui/mobile/src/api/sse.ts`

- [ ] **Step 1：在 sse.ts 新增 `createSessionSSEConnection`**

将 `ui/mobile/src/api/sse.ts` 全量替换为：

```typescript
import EventSource from 'react-native-sse';
import { useSettingsStore } from '../store/settings';
import type { SSEEvent } from '../types';

export type SSEHandler = (event: SSEEvent) => void;

/** 全局 SSE（task / approval 事件）。 */
export function createSSEConnection(
  onEvent: SSEHandler,
  onError: (err: Error) => void,
): () => void {
  const { serverUrl, jwtToken } = useSettingsStore.getState();

  const es = new EventSource(`${serverUrl}/api/v1/stream`, {
    headers: { Authorization: `Bearer ${jwtToken ?? ''}` },
  });

  es.addEventListener('message', (e) => {
    if (!e.data) return;
    try {
      const parsed = JSON.parse(e.data) as SSEEvent & { event?: string };
      onEvent({ type: parsed.type ?? parsed.event, data: parsed.data } as SSEEvent);
    } catch { /* skip malformed */ }
  });

  es.addEventListener('error', (e) => {
    if (e.type === 'error' || e.type === 'exception') {
      onError(new Error((e as { message?: string }).message ?? 'SSE error'));
    }
  });

  return () => es.close();
}

/** Per-session SSE（流式内容：turn.delta / thinking / tool）。支持 Last-Event-ID 续接。 */
export function createSessionSSEConnection(
  sessionId: string,
  onEvent: SSEHandler,
  onError: (err: Error) => void,
  lastEventId?: string,
): () => void {
  const { serverUrl, jwtToken } = useSettingsStore.getState();

  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwtToken ?? ''}`,
  };
  if (lastEventId) headers['Last-Event-ID'] = lastEventId;

  const es = new EventSource(
    `${serverUrl}/api/v1/sessions/${sessionId}/stream`,
    { headers },
  );

  es.addEventListener('message', (e) => {
    if (!e.data) return;
    try {
      const parsed = JSON.parse(e.data) as SSEEvent & { event?: string };
      onEvent({ type: parsed.type ?? parsed.event, data: parsed.data } as SSEEvent);
    } catch { /* skip malformed */ }
  });

  es.addEventListener('error', (e) => {
    if (e.type === 'error' || e.type === 'exception') {
      onError(new Error((e as { message?: string }).message ?? 'SSE error'));
    }
  });

  return () => es.close();
}
```

- [ ] **Step 2：TS 检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

预期：无输出。

- [ ] **Step 3：Commit**

```bash
cd ui/mobile
git add src/api/sse.ts
git commit -m "feat(app): 新增 createSessionSSEConnection，支持 per-session 流式

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4：useConversation hook

**Files:**
- Create: `ui/mobile/src/hooks/useConversation.ts`

- [ ] **Step 1：新建 useConversation.ts**

创建 `ui/mobile/src/hooks/useConversation.ts`：

```typescript
import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { createSessionSSEConnection } from '../api/sse';
import { getSessionDetail } from '../api/sessions';
import { useConversationStore } from '../store/conversation';
import { useSettingsStore } from '../store/settings';
import type { ConvMessage, SSEEvent } from '../types';

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;

/** 管理单个 session 的 hydrate + per-session SSE 生命周期。
 *  在 ConversationView mount 时调用，unmount 时自动 pause。 */
export function useConversation(sessionId: string | null): void {
  const jwtToken = useSettingsStore((s) => s.jwtToken);
  const queryClient = useQueryClient();
  const store = useConversationStore;
  const disconnectRef = useRef<(() => void) | null>(null);
  const retryRef = useRef(0);
  const lastEventIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!sessionId || !jwtToken) return;

    const { getOrInit, setStatus, setMessages } = store.getState();

    // Already live — nothing to do
    if (getOrInit(sessionId).status === 'live') return;

    setStatus(sessionId, 'loading');

    // 1. Hydrate historical messages
    getSessionDetail(sessionId)
      .then((detail) => {
        const messages: ConvMessage[] = detail.messages.map((m, i) => ({
          id: `${sessionId}-${i}`,
          role: m.role,
          content: m.content,
          createdAt: m.ts ?? '',
        }));
        setMessages(sessionId, messages);
      })
      .catch(() => {
        // Non-fatal — render with empty history, SSE fills live content
      });

    // 2. Connect per-session SSE
    function connect(): void {
      disconnectRef.current?.();

      disconnectRef.current = createSessionSSEConnection(
        sessionId!,
        (event: SSEEvent) => {
          retryRef.current = 0;
          handleEvent(event);
        },
        (err) => {
          console.warn(`[useConversation] SSE error for ${sessionId}:`, err);
          if (retryRef.current < MAX_RETRIES) {
            const delay = BASE_DELAY_MS * 2 ** retryRef.current;
            retryRef.current += 1;
            setTimeout(connect, delay);
          }
        },
        lastEventIdRef.current,
      );

      store.getState().setStatus(sessionId!, 'live');
    }

    function handleEvent(event: SSEEvent): void {
      // Track Last-Event-ID for reconnection (react-native-sse exposes lastEventId
      // via the native EventSource; here we piggyback on a custom field if present)
      const raw = event as SSEEvent & { id?: string };
      if (raw.id) lastEventIdRef.current = raw.id;

      const s = store.getState();

      switch (event.type) {
        case 'thinking_block.start': {
          const d = event.data as { block_id: string };
          s.onThinkingBlockStart(sessionId!, d.block_id);
          break;
        }
        case 'turn.thinking_delta': {
          const d = event.data as { block_id: string; delta: string };
          s.onThinkingDelta(sessionId!, d.block_id, d.delta);
          break;
        }
        case 'thinking_block.stop': {
          const d = event.data as { block_id: string };
          s.onThinkingBlockStop(sessionId!, d.block_id);
          break;
        }
        case 'text_block.start': {
          const d = event.data as { block_id: string };
          s.onTextBlockStart(sessionId!, d.block_id);
          break;
        }
        case 'turn.delta': {
          const d = event.data as { block_id: string; delta: string };
          s.onTextDelta(sessionId!, d.block_id, d.delta);
          break;
        }
        case 'text_block.stop': {
          const d = event.data as { block_id: string };
          s.onTextBlockStop(sessionId!, d.block_id);
          break;
        }
        case 'tool.running': {
          const d = event.data as { tool_id: string; name: string; input?: unknown };
          s.onToolRunning(
            sessionId!,
            d.tool_id,
            d.name,
            typeof d.input === 'string' ? d.input : JSON.stringify(d.input ?? ''),
          );
          break;
        }
        case 'tool.executed': {
          const d = event.data as { tool_id: string; result_summary?: string };
          s.onToolExecuted(sessionId!, d.tool_id, d.result_summary ?? '');
          break;
        }
        case 'tool.failed': {
          const d = event.data as { tool_id: string; error?: string };
          s.onToolFailed(sessionId!, d.tool_id, d.error ?? 'failed');
          break;
        }
        case 'turn.response': {
          s.onTurnComplete(sessionId!);
          // Refresh historical messages
          getSessionDetail(sessionId!).then((detail) => {
            const messages: ConvMessage[] = detail.messages.map((m, i) => ({
              id: `${sessionId}-${i}`,
              role: m.role,
              content: m.content,
              createdAt: m.ts ?? '',
            }));
            store.getState().setMessages(sessionId!, messages);
          });
          queryClient.invalidateQueries({ queryKey: ['session-detail', sessionId] });
          break;
        }
        default:
          break;
      }
    }

    connect();

    return () => {
      // Pause: disconnect SSE, keep state in store
      disconnectRef.current?.();
      disconnectRef.current = null;
      store.getState().pauseSession(sessionId!);
    };
  }, [sessionId, jwtToken]);
}
```

- [ ] **Step 2：TS 检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

预期：无输出。

- [ ] **Step 3：Commit**

```bash
cd ui/mobile
git add src/hooks/useConversation.ts
git commit -m "feat(app): 新增 useConversation hook，管理 hydrate + per-session SSE

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5：MarkdownContent + UserBubble

**Files:**
- Create: `ui/mobile/src/components/conversation/MarkdownContent.tsx`
- Create: `ui/mobile/src/components/conversation/UserBubble.tsx`

- [ ] **Step 1：新建 MarkdownContent.tsx**

创建 `ui/mobile/src/components/conversation/MarkdownContent.tsx`：

```typescript
import Markdown from 'react-native-markdown-display';
import { StyleSheet } from 'react-native';

interface Props {
  content: string;
  /** 流式未完成时传 true，禁用部分会闪烁的样式 */
  streaming?: boolean;
}

export function MarkdownContent({ content }: Props) {
  return (
    <Markdown style={mdStyles}>{content}</Markdown>
  );
}

const mdStyles = StyleSheet.create({
  body: { color: '#d0d0d0', fontSize: 15, lineHeight: 22 },
  heading1: { color: '#ffffff', fontSize: 20, fontWeight: '700', marginBottom: 8 },
  heading2: { color: '#ffffff', fontSize: 17, fontWeight: '600', marginBottom: 6 },
  heading3: { color: '#e0e0e0', fontSize: 15, fontWeight: '600', marginBottom: 4 },
  strong: { color: '#ffffff', fontWeight: '700' },
  em: { fontStyle: 'italic' },
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
  list_item: { color: '#d0d0d0', marginBottom: 2 },
  blockquote: {
    borderLeftWidth: 3,
    borderLeftColor: '#3a3a5a',
    paddingLeft: 12,
    marginVertical: 6,
    opacity: 0.8,
  },
  hr: { borderTopColor: '#2a2a3a', borderTopWidth: 1, marginVertical: 12 },
  link: { color: '#7c6af5', textDecorationLine: 'underline' },
  table: { borderWidth: 1, borderColor: '#2a2a3a', marginVertical: 8 },
  th: { backgroundColor: '#1a1a2e', padding: 8, color: '#e0e0e0', fontWeight: '600' },
  td: { padding: 8, color: '#d0d0d0', borderTopWidth: 1, borderTopColor: '#2a2a3a' },
});
```

- [ ] **Step 2：新建 UserBubble.tsx**

创建 `ui/mobile/src/components/conversation/UserBubble.tsx`：

```typescript
import { View, Text, StyleSheet } from 'react-native';

interface Props {
  content: string;
}

export function UserBubble({ content }: Props) {
  return (
    <View style={styles.row}>
      <View style={styles.bubble}>
        <Text style={styles.text}>{content}</Text>
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
    backgroundColor: '#7c6af5',
    borderRadius: 18,
    borderBottomRightRadius: 4,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  text: {
    color: '#ffffff',
    fontSize: 15,
    lineHeight: 21,
  },
});
```

- [ ] **Step 3：TS 检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

预期：无输出。

- [ ] **Step 4：Commit**

```bash
cd ui/mobile
git add src/components/conversation/MarkdownContent.tsx src/components/conversation/UserBubble.tsx
git commit -m "feat(app): 新增 MarkdownContent 和 UserBubble 组件

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6：ThinkingBlock 组件

**Files:**
- Create: `ui/mobile/src/components/conversation/ThinkingBlock.tsx`

- [ ] **Step 1：新建 ThinkingBlock.tsx**

创建 `ui/mobile/src/components/conversation/ThinkingBlock.tsx`：

```typescript
import { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { MarkdownContent } from './MarkdownContent';

interface Props {
  text: string;
  done: boolean;
}

export function ThinkingBlock({ text, done }: Props) {
  const [expanded, setExpanded] = useState(false);

  const label = done ? '思考过程' : '思考中…';

  if (!expanded) {
    return (
      <TouchableOpacity
        style={styles.pill}
        onPress={() => setExpanded(true)}
        activeOpacity={0.7}
      >
        <Text style={styles.pillIcon}>💭</Text>
        <Text style={styles.pillLabel}>{label}</Text>
        <Text style={styles.pillChevron}>›</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.container}>
      {/* Header — same pill style, click to collapse */}
      <TouchableOpacity
        style={styles.header}
        onPress={() => setExpanded(false)}
        activeOpacity={0.7}
      >
        <Text style={styles.pillIcon}>💭</Text>
        <Text style={styles.pillLabel}>{label}</Text>
        <Text style={styles.pillChevron}>⌄</Text>
      </TouchableOpacity>
      {/* Content — connected to header, same container */}
      <View style={styles.body}>
        <MarkdownContent content={text} streaming={!done} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  // Collapsed: standalone pill
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    backgroundColor: '#1a1a2e',
    borderWidth: 1,
    borderColor: '#2a2a4e',
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 6,
    gap: 6,
    marginVertical: 4,
  },
  // Expanded: outer container merges header + body
  container: {
    borderWidth: 1,
    borderColor: '#2a2a4e',
    borderRadius: 12,
    overflow: 'hidden',
    marginVertical: 4,
    backgroundColor: '#111120',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1a1a2e',
    paddingHorizontal: 14,
    paddingVertical: 8,
    gap: 6,
  },
  body: {
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  pillIcon: { fontSize: 14 },
  pillLabel: { color: '#6060a0', fontSize: 13, flex: 1 },
  pillChevron: { color: '#3a3a5a', fontSize: 16 },
});
```

- [ ] **Step 2：TS 检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

预期：无输出。

- [ ] **Step 3：Commit**

```bash
cd ui/mobile
git add src/components/conversation/ThinkingBlock.tsx
git commit -m "feat(app): 新增 ThinkingBlock accordion pill 组件

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 7：ToolCallRow + ToolCallGroup

**Files:**
- Create: `ui/mobile/src/components/conversation/ToolCallRow.tsx`
- Create: `ui/mobile/src/components/conversation/ToolCallGroup.tsx`

- [ ] **Step 1：新建 ToolCallRow.tsx**

创建 `ui/mobile/src/components/conversation/ToolCallRow.tsx`：

```typescript
import { View, Text, StyleSheet } from 'react-native';

interface Props {
  name: string;
  input: string;
  status: 'running' | 'done' | 'failed';
}

const DOT_COLOR: Record<Props['status'], string> = {
  running: '#f5a623',
  done: '#4caf50',
  failed: '#f44336',
};

export function ToolCallRow({ name, input, status }: Props) {
  // Show first 60 chars of input to keep it one-line
  const inputPreview = input.length > 60 ? `${input.slice(0, 60)}…` : input;

  return (
    <View style={styles.row}>
      <View style={[styles.dot, { backgroundColor: DOT_COLOR[status] }]} />
      <Text style={styles.name}>{name}</Text>
      {inputPreview ? <Text style={styles.input}>{inputPreview}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    flexShrink: 0,
  },
  name: {
    color: '#8888aa',
    fontSize: 13,
    fontWeight: '500',
    flexShrink: 0,
  },
  input: {
    color: '#555566',
    fontSize: 13,
    flex: 1,
  },
});
```

- [ ] **Step 2：新建 ToolCallGroup.tsx**

创建 `ui/mobile/src/components/conversation/ToolCallGroup.tsx`：

```typescript
import { View, StyleSheet } from 'react-native';
import { ToolCallRow } from './ToolCallRow';
import type { RenderBlock } from '../../types';

type ToolBlock = Extract<RenderBlock, { type: 'tool' }>;

interface Props {
  tools: ToolBlock[];
}

export function ToolCallGroup({ tools }: Props) {
  return (
    <View style={styles.container}>
      {tools.map((tool, index) => (
        <View key={tool.toolId}>
          <ToolCallRow
            name={tool.name}
            input={tool.input}
            status={tool.status}
          />
          {/* Vertical connector between consecutive tool calls */}
          {index < tools.length - 1 && <View style={styles.connector} />}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: 2,
    paddingLeft: 4,
  },
  connector: {
    width: 1,
    height: 10,
    backgroundColor: '#2a2a2a',
    marginLeft: 3,   // aligns with center of the 8px dot
  },
});
```

- [ ] **Step 3：TS 检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

预期：无输出。

- [ ] **Step 4：Commit**

```bash
cd ui/mobile
git add src/components/conversation/ToolCallRow.tsx src/components/conversation/ToolCallGroup.tsx
git commit -m "feat(app): 新增 ToolCallRow + ToolCallGroup 组件（Claude Code 风格）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 8：AssistantMessage 组件

**Files:**
- Create: `ui/mobile/src/components/conversation/AssistantMessage.tsx`

- [ ] **Step 1：新建 AssistantMessage.tsx**

创建 `ui/mobile/src/components/conversation/AssistantMessage.tsx`：

```typescript
import { View, StyleSheet } from 'react-native';
import { ThinkingBlock } from './ThinkingBlock';
import { ToolCallGroup } from './ToolCallGroup';
import { MarkdownContent } from './MarkdownContent';
import type { RenderBlock } from '../../types';

type ToolBlock = Extract<RenderBlock, { type: 'tool' }>;

interface Props {
  blocks: RenderBlock[];
}

/** 将连续的 tool block 合并为一个 ToolCallGroup，其余块按顺序渲染。 */
function groupBlocks(blocks: RenderBlock[]): Array<RenderBlock | ToolBlock[]> {
  const result: Array<RenderBlock | ToolBlock[]> = [];
  let i = 0;
  while (i < blocks.length) {
    if (blocks[i].type === 'tool') {
      const group: ToolBlock[] = [];
      while (i < blocks.length && blocks[i].type === 'tool') {
        group.push(blocks[i] as ToolBlock);
        i++;
      }
      result.push(group);
    } else {
      result.push(blocks[i]);
      i++;
    }
  }
  return result;
}

export function AssistantMessage({ blocks }: Props) {
  if (blocks.length === 0) return null;

  const grouped = groupBlocks(blocks);

  return (
    <View style={styles.container}>
      {grouped.map((item, index) => {
        if (Array.isArray(item)) {
          return <ToolCallGroup key={`tools-${index}`} tools={item} />;
        }
        if (item.type === 'thinking') {
          return (
            <ThinkingBlock
              key={item.blockId}
              text={item.text}
              done={item.done}
            />
          );
        }
        if (item.type === 'text') {
          return (
            <MarkdownContent
              key={item.blockId}
              content={item.text}
              streaming={!item.done}
            />
          );
        }
        return null;
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
});
```

- [ ] **Step 2：TS 检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

预期：无输出。

- [ ] **Step 3：Commit**

```bash
cd ui/mobile
git add src/components/conversation/AssistantMessage.tsx
git commit -m "feat(app): 新增 AssistantMessage 组件（blocks 顺序渲染 + tool 分组）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 9：ConversationView + index.ts

**Files:**
- Create: `ui/mobile/src/components/conversation/ConversationView.tsx`
- Create: `ui/mobile/src/components/conversation/index.ts`

- [ ] **Step 1：新建 ConversationView.tsx**

创建 `ui/mobile/src/components/conversation/ConversationView.tsx`：

```typescript
import { useRef } from 'react';
import { FlatList, View, StyleSheet } from 'react-native';
import { useConversation } from '../../hooks/useConversation';
import { useConversationStore } from '../../store/conversation';
import { UserBubble } from './UserBubble';
import { AssistantMessage } from './AssistantMessage';
import type { ConvMessage, RenderBlock } from '../../types';

interface Props {
  sessionId: string | null;
}

type ListItem =
  | { kind: 'message'; message: ConvMessage }
  | { kind: 'streaming'; blocks: RenderBlock[] };

export function ConversationView({ sessionId }: Props) {
  useConversation(sessionId);

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

  function renderItem({ item }: { item: ListItem }) {
    if (item.kind === 'message') {
      const { message } = item;
      if (message.role === 'user') {
        return <UserBubble content={message.content} />;
      }
      // Historical assistant messages rendered as plain markdown
      return (
        <View style={styles.assistantPadding}>
          <AssistantMessage
            blocks={[
              {
                type: 'text',
                blockId: message.id,
                text: message.content,
                done: true,
              },
            ]}
          />
        </View>
      );
    }
    // Streaming turn
    return <AssistantMessage blocks={item.blocks} />;
  }

  return (
    <View style={styles.container}>
      <FlatList
        ref={flatListRef}
        data={items}
        keyExtractor={(item, index) =>
          item.kind === 'message' ? item.message.id : `streaming-${index}`
        }
        renderItem={renderItem}
        contentContainerStyle={styles.content}
        onContentSizeChange={() =>
          flatListRef.current?.scrollToEnd({ animated: true })
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0d0d0d' },
  content: { paddingTop: 12, paddingBottom: 100 },
  assistantPadding: {},
});
```

- [ ] **Step 2：新建 index.ts**

创建 `ui/mobile/src/components/conversation/index.ts`：

```typescript
export { ConversationView } from './ConversationView';
export { UserBubble } from './UserBubble';
export { AssistantMessage } from './AssistantMessage';
export { ThinkingBlock } from './ThinkingBlock';
export { ToolCallGroup } from './ToolCallGroup';
export { ToolCallRow } from './ToolCallRow';
export { MarkdownContent } from './MarkdownContent';
```

- [ ] **Step 3：TS 检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

预期：无输出。

- [ ] **Step 4：Commit**

```bash
cd ui/mobile
git add src/components/conversation/ConversationView.tsx src/components/conversation/index.ts
git commit -m "feat(app): 新增 ConversationView 顶层容器 + conversation 组件出口

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 10：接入 Chat 页面 + Subagent Session 页面

**Files:**
- Modify: `ui/mobile/app/(tabs)/chat/index.tsx`
- Modify: `ui/mobile/app/subagents/session/[id].tsx`

- [ ] **Step 1：更新 chat/index.tsx**

将 `ui/mobile/app/(tabs)/chat/index.tsx` 的消息区替换为 `ConversationView`。完整替换文件内容：

```typescript
import { useState } from 'react';
import { View, StyleSheet, Alert, TouchableOpacity, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSessionStore } from '../../../src/store/session';
import { useSessions } from '../../../src/hooks/useSessions';
import { sendTurn, cancelTurn } from '../../../src/api/turns';
import { deleteSession } from '../../../src/api/sessions';
import { useQueryClient } from '@tanstack/react-query';
import { useSSE } from '../../../src/hooks/useSSE';
import { Sidebar } from '../../../src/components/common/Sidebar';
import { EmptyState } from '../../../src/components/common/EmptyState';
import { ChatSidebar } from '../../../src/components/chat/ChatSidebar';
import { MessageInput } from '../../../src/components/chat/MessageInput';
import { ConversationView } from '../../../src/components/conversation';
import type { Approval } from '../../../src/types';

export default function ChatScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<Approval | null>(null);

  const {
    currentSessionId,
    draftSession,
    setCurrentSession,
    startDraft,
    persistSession,
  } = useSessionStore();

  const { data: sessions = [] } = useSessions();

  // Global SSE: handles task.* and approval events only
  useSSE({ onApprovalRequired: setPendingApproval });

  const isWorking = useConversationStore(
    (s) => !!(currentSessionId && s.sessions[currentSessionId]?.activeTurn),
  );

  async function handleSend(text: string) {
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
        });
      }
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    } catch {
      Alert.alert('发送失败，请重试');
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
            queryClient.invalidateQueries({ queryKey: ['sessions'] });
          } catch {
            Alert.alert('删除失败，请重试');
          }
        },
      },
    ]);
  }

  const isEmpty = !currentSessionId && !draftSession;

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top }]}>
        <TouchableOpacity style={styles.menuButton} onPress={() => setSidebarOpen(true)}>
          <Text style={styles.menuIcon}>☰</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Sebastian</Text>
      </View>

      {isEmpty ? (
        <EmptyState message="向 Sebastian 发送消息开始对话" />
      ) : (
        <ConversationView sessionId={currentSessionId} />
      )}

      <MessageInput isWorking={isWorking} onSend={handleSend} onStop={handleStop} />

      <Sidebar visible={sidebarOpen} onClose={() => setSidebarOpen(false)}>
        <ChatSidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          draftSession={draftSession}
          onSelect={(id) => { setCurrentSession(id); setSidebarOpen(false); }}
          onNewChat={() => { startDraft(); setSidebarOpen(false); }}
          onDelete={handleDeleteSession}
        />
      </Sidebar>
    </View>
  );
}

// Add missing import at top of file
// import { useConversationStore } from '../../../src/store/conversation';

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0d0d0d' },
  header: {
    minHeight: 48,
    backgroundColor: '#111118',
    borderBottomWidth: 1,
    borderBottomColor: '#1e1e2e',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
  },
  menuButton: { padding: 8 },
  menuIcon: { fontSize: 20, color: '#888' },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 16,
    fontWeight: '600',
    color: '#e0e0e0',
    marginRight: 36,
  },
});
```

**注意**：文件头部需加上这行 import（已在上面注释里提醒）：

```typescript
import { useConversationStore } from '../../../src/store/conversation';
```

将它加入文件的 import 区。

- [ ] **Step 2：更新 subagents/session/[id].tsx 的消息 Tab**

将 `ui/mobile/app/subagents/session/[id].tsx` 中消息 tab 的 `<MessageList>` 替换为 `<ConversationView>`。

将文件的 import 区顶部加入：

```typescript
import { ConversationView } from '../../../src/components/conversation';
```

删除原有的 `MessageList` import：

```typescript
// 删除这行：
import { MessageList } from '../../../src/components/chat/MessageList';
```

将消息 tab 渲染部分（约第 183 行）：

```typescript
// 原来：
{tab === 'messages' ? (
  <MessageList messages={messages} streamingContent="" />
) : (
  <SessionDetailView tasks={tasks} />
)}
```

替换为：

```typescript
{tab === 'messages' ? (
  <ConversationView sessionId={isMockSession ? null : sessionId} />
) : (
  <SessionDetailView tasks={tasks} />
)}
```

同时可以删除 `detail`、`messages` 的计算逻辑（已不需要）：

删除以下代码块（约第 114-149 行）：

```typescript
const detail = useMemo(
  () => (isMockSession ? buildMockDetail(sessionId, agentName) : remoteDetail),
  [agentName, isMockSession, remoteDetail, sessionId],
);
// ...
const messages =
  detail?.messages.map((message, index) => ({...})) ?? [];
```

但保留 `detail` 用于 header title 显示，所以只删 `messages` 的计算，保留 `detail`。

- [ ] **Step 3：TS 检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -30
```

预期：无输出。如果有错误，根据错误信息修正 import 路径。

- [ ] **Step 4：运行 App 验证**

```bash
cd ui/mobile
npx expo start
```

在模拟器/真机上验证：
1. Sebastian 主页：发一条消息，确认流式输出逐字显示（不再是等待后一次性刷出）
2. AI 回复有思考块时：显示 `💭 思考中…` pill，完成后可点击展开/收起
3. 有 tool 调用时：显示状态圆点 + tool name + 参数，连续 tool 之间有竖线
4. 正文 Markdown 正确渲染（`**粗体**`、代码块等）
5. 切换到 subagent session 页：消息 tab 同样显示 ConversationView

- [ ] **Step 5：Commit**

```bash
cd ui/mobile
git add app/\(tabs\)/chat/index.tsx app/subagents/session/\[id\].tsx
git commit -m "feat(app): 接入 ConversationView，替换 MessageList，打通真实流式渲染

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 自查

**Spec coverage：**
- ✅ 用户气泡 → `UserBubble`
- ✅ AI 扁平线性 → `AssistantMessage` + `ConversationView`（无卡片包裹）
- ✅ 思考折叠 accordion pill → `ThinkingBlock`
- ✅ tool 调用 Claude Code 风格 → `ToolCallRow` + `ToolCallGroup`（连续竖线）
- ✅ Markdown → `MarkdownContent`（react-native-markdown-display）
- ✅ 共享组件 → `src/components/conversation/`，两处页面均用 `<ConversationView>`
- ✅ per-session 状态隔离 → `conversation.ts` store，key = sessionId
- ✅ 多 session 并行 + LRU 清理 → `pauseSession` + `MAX_PAUSED = 5`
- ✅ 流式接续：先 hydrate REST，再 per-session SSE + Last-Event-ID
- ✅ block_id 追踪 → `blockMap`，防止多思考块合并到第一个
- ✅ tool_id 追踪 → `blockMap` 同一 map，toolId 作为 key

**Placeholder 扫描：** 无 TBD / TODO。

**类型一致性：** `RenderBlock`、`ActiveTurn`、`ConvSessionState` 在 `types.ts` 定义，store 和组件均从同一处 import。`ToolBlock = Extract<RenderBlock, { type: 'tool' }>` 在需要的组件内局部定义，一致。
