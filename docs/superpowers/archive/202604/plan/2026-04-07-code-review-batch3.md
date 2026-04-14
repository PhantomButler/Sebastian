# Code Review Batch 3 — 前端修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 5 个前端问题（H7 / M6 / M7 / C3 / H8），消除竞态条件、类型错误和逻辑缺失。

**Architecture:** 所有改动在 `ui/mobile/` 目录的 React Native/TypeScript 前端代码中，仅修改 4 个文件，无新增文件，无后端改动。

**Tech Stack:** React Native, TypeScript, Expo Router, React hooks (`useRef`, `useState`)

---

## 文件改动汇总

| 文件 | 改动 |
|------|------|
| `ui/mobile/src/components/subagents/AgentList.tsx:30` | `item.goal` → `item.description` |
| `ui/mobile/src/components/common/StatusBadge.tsx` | 加 `stalled` 颜色；扩展 Props 类型 |
| `ui/mobile/src/components/chat/AppSidebar.tsx:105` | FAB `disabled` 补 `!currentSessionId` |
| `ui/mobile/app/subagents/session/[id].tsx` | 加 `sendingRef` 防重入；`setRealSessionId(newId)` |

---

### Task 1: H7 — AgentList: item.goal → item.description

**Files:**
- Modify: `ui/mobile/src/components/subagents/AgentList.tsx:30`

`Agent` 类型只有 `description` 字段，没有 `goal`，当前渲染 `{item.goal}` 结果为 `undefined`。

- [ ] **Step 1: 修改渲染字段**

在 `ui/mobile/src/components/subagents/AgentList.tsx` 找到第 30 行：

```tsx
          <Text style={styles.goal} numberOfLines={2}>
            {item.goal}
          </Text>
```

改为：

```tsx
          <Text style={styles.goal} numberOfLines={2}>
            {item.description}
          </Text>
```

- [ ] **Step 2: TypeScript 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无类型错误（之前 `item.goal` 会报 Property 'goal' does not exist on type 'Agent'）。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/subagents/AgentList.tsx
git commit -m "fix(frontend): H7 — AgentList item.goal → item.description

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: M6 — StatusBadge: stalled 颜色 + 类型扩展

**Files:**
- Modify: `ui/mobile/src/components/common/StatusBadge.tsx`

当前 `COLOR` 映射缺少 `stalled`（fallback 灰色而非橙色）；`Props` 类型为 `AgentStatus | TaskStatus`，无法承担 `SessionMeta['status']` 角色。

- [ ] **Step 1: 修改 StatusBadge**

将 `ui/mobile/src/components/common/StatusBadge.tsx` 完整替换为：

```tsx
import { Text, StyleSheet } from 'react-native';
import type { AgentStatus, SessionMeta, TaskStatus } from '../../types';

const COLOR: Record<string, string> = {
  idle: '#999',
  working: '#007AFF',
  waiting_approval: '#FF9500',
  completed: '#34C759',
  failed: '#FF3B30',
  created: '#999',
  planning: '#5AC8FA',
  running: '#007AFF',
  paused: '#FF9500',
  cancelled: '#999',
  stalled: '#F59E0B',
  active: '#34C759',
};

interface Props { status: AgentStatus | TaskStatus | SessionMeta['status']; }

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

说明：
- `stalled: '#F59E0B'` — 橙黄色，符合 Spec §8.5
- `active: '#34C759'` — 绿色（与 completed 相同，表示正常运行）
- Props 加 `SessionMeta['status']` 使组件可用于 session status badge

- [ ] **Step 2: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无类型错误。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/common/StatusBadge.tsx
git commit -m "fix(frontend): M6 — StatusBadge 加 stalled 颜色 + 扩展 SessionMeta status 类型

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: M7 — AppSidebar FAB disabled 补完

**Files:**
- Modify: `ui/mobile/src/components/chat/AppSidebar.tsx:105`

当前 `disabled={draftSession}` 遗漏了 `!currentSessionId` 条件。当 `currentSessionId` 为 null（已处于"新对话"状态）时 FAB 应灰显，避免重复创建。

- [ ] **Step 1: 修改 FAB disabled 逻辑**

在 `ui/mobile/src/components/chat/AppSidebar.tsx` 找到：

```tsx
      <NewChatFAB
        label="新对话"
        onPress={onNewChat}
        disabled={draftSession}
        style={styles.fab}
      />
```

改为：

```tsx
      <NewChatFAB
        label="新对话"
        onPress={onNewChat}
        disabled={!!draftSession || !currentSessionId}
        style={styles.fab}
      />
```

- [ ] **Step 2: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无类型错误（`currentSessionId: string | null`，`!currentSessionId` 合法）。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/chat/AppSidebar.tsx
git commit -m "fix(frontend): M7 — AppSidebar FAB disabled 补完 !currentSessionId 条件

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: C3 + H8 — handleSend 竞态修复 + setRealSessionId

**Files:**
- Modify: `ui/mobile/app/subagents/session/[id].tsx`

**C3**：当前使用 `sending` state 防重入，React 批处理使得两次快速点击可同时通过检查，需用 `useRef` 做同步标志。

**H8**：`createAgentSession` 成功后直接 `router.replace` 但未调用 `setRealSessionId(newId)`，若路由是就地更新（未卸载组件），`realSessionId` 永远为 null，后续 query 和 sendTurn 全部失效。

- [ ] **Step 1: 修改 [id].tsx**

打开 `ui/mobile/app/subagents/session/[id].tsx`，进行以下改动：

**1a. 在 import 行加 `useRef`**（当前 line 1）：

```tsx
import { useCallback, useMemo, useRef, useState } from 'react';
```

**1b. 在 `useState` 声明之后（line 104 附近）加 `sendingRef`**：

```tsx
  const [sending, setSending] = useState(false);
  const [realSessionId, setRealSessionId] = useState<string | null>(null);
  const sendingRef = useRef(false);
  const effectiveSessionId = realSessionId || (isNewSession ? null : sessionId);
```

**1c. 修改 `handleSend` 函数**（完整替换 `handleSend`，line 126-159）：

```tsx
  const handleSend = useCallback(
    async (text: string) => {
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
      } catch {
        Alert.alert('发送失败，请重试');
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    },
    [agentName, effectiveSessionId, isMockSession, isNewSession, queryClient, realSessionId, router],
  );
```

说明：
- `sendingRef.current` 在异步函数的整个生命周期内保持 `true`，防止并发调用
- `setSending(true)` 提至最外层，统一处理所有分支的 loading 状态
- `setRealSessionId(newId)` 在 `router.replace` 之前调用（H8）
- `try` 块最后加 `return` 以避免 finally 中的 `setSending(false)` 干扰 mock 分支（mock 分支有 early return）

注意：`isMockSession` 分支保持 early return，`sendingRef` 不会被置 true（mock 分支不走正式发送流程）。

- [ ] **Step 2: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无类型错误。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/app/subagents/session/\[id\].tsx
git commit -m "fix(frontend): C3+H8 — handleSend 加 sendingRef 防重入 + setRealSessionId

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 自检清单

- [ ] H7: `AgentList.tsx` line 30 不再有 `item.goal`
- [ ] M6: `StatusBadge.tsx` COLOR 有 `stalled`；Props 类型含 `SessionMeta['status']`
- [ ] M7: `AppSidebar.tsx` FAB `disabled={!!draftSession || !currentSessionId}`
- [ ] C3: `[id].tsx` 有 `sendingRef = useRef(false)` 且在 `handleSend` 入口处判断
- [ ] H8: `[id].tsx` `createAgentSession` 成功后先调 `setRealSessionId(newId)` 再 `router.replace`
- [ ] `npx tsc --noEmit` 无错误
