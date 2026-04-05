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
  appendUserMessage(sessionId: string, content: string): void;
  onToolRunning(sessionId: string, toolId: string, name: string, input: string): void;
  onToolExecuted(sessionId: string, toolId: string, result: string): void;
  onToolFailed(sessionId: string, toolId: string, error: string): void;
  onTurnComplete(sessionId: string): void;
  completeTurn(sessionId: string): void;
}

function emptySession(): ConvSessionState {
  return { status: 'idle', messages: [], activeTurn: null };
}

/** Produces a new ActiveTurn with the block appended. Does not mutate input. */
function appendBlock(turn: ActiveTurn | null, block: RenderBlock): ActiveTurn {
  const key = block.type === 'tool' ? block.toolId : block.blockId;
  const newMap = new Map(turn?.blockMap ?? []);
  newMap.set(key, block);
  return {
    blocks: [...(turn?.blocks ?? []), block],
    blockMap: newMap,
  };
}

/** Produces a new ActiveTurn with the block at blockId replaced by updater(block). */
function updateBlock(
  turn: ActiveTurn,
  key: string,
  updater: (b: RenderBlock) => RenderBlock,
): ActiveTurn {
  const existing = turn.blockMap.get(key);
  if (!existing) return turn;
  const updated = updater(existing);
  const newMap = new Map(turn.blockMap);
  newMap.set(key, updated);
  const newBlocks = turn.blocks.map((b) => {
    const k = b.type === 'tool' ? b.toolId : b.blockId;
    return k === key ? updated : b;
  });
  return { blocks: newBlocks, blockMap: newMap };
}

function updateSession(
  sessions: Record<string, ConvSessionState>,
  sessionId: string,
  patch: Partial<ConvSessionState>,
): Record<string, ConvSessionState> {
  return {
    ...sessions,
    [sessionId]: { ...(sessions[sessionId] ?? emptySession()), ...patch },
  };
}

export const useConversationStore = create<ConversationStore>((set, get) => ({
  sessions: {},

  getOrInit(sessionId) {
    return get().sessions[sessionId] ?? emptySession();
  },

  setStatus(sessionId, status) {
    set((s) => ({ sessions: updateSession(s.sessions, sessionId, { status }) }));
  },

  setMessages(sessionId, messages) {
    set((s) => ({ sessions: updateSession(s.sessions, sessionId, { messages }) }));
  },

  pauseSession(sessionId) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session) return s;
      const paused = Object.entries(s.sessions).filter(
        ([id, sess]) => id !== sessionId && sess.status === 'paused',
      );
      const toEvictIds = new Set(paused.slice(MAX_PAUSED - 1).map(([id]) => id));
      const next = updateSession(s.sessions, sessionId, { status: 'paused' });
      const final = Object.fromEntries(
        Object.entries(next).filter(([id]) => !toEvictIds.has(id)),
      );
      return { sessions: final };
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
      const session = s.sessions[sessionId] ?? emptySession();
      const block: RenderBlock = { type: 'thinking', blockId, text: '', done: false };
      const activeTurn = appendBlock(session.activeTurn, block);
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  onThinkingDelta(sessionId, blockId, delta) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const activeTurn = updateBlock(session.activeTurn, blockId, (b) => {
        if (b.type !== 'thinking') return b;
        return { ...b, text: b.text + delta };
      });
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  onThinkingBlockStop(sessionId, blockId) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const activeTurn = updateBlock(session.activeTurn, blockId, (b) => {
        if (b.type !== 'thinking') return b;
        return { ...b, done: true };
      });
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  onTextBlockStart(sessionId, blockId) {
    set((s) => {
      const session = s.sessions[sessionId] ?? emptySession();
      const block: RenderBlock = { type: 'text', blockId, text: '', done: false };
      const activeTurn = appendBlock(session.activeTurn, block);
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  onTextDelta(sessionId, blockId, delta) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const activeTurn = updateBlock(session.activeTurn, blockId, (b) => {
        if (b.type !== 'text') return b;
        return { ...b, text: b.text + delta };
      });
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  onTextBlockStop(sessionId, blockId) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const activeTurn = updateBlock(session.activeTurn, blockId, (b) => {
        if (b.type !== 'text') return b;
        return { ...b, done: true };
      });
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  appendUserMessage(sessionId, content) {
    set((s) => {
      const session = s.sessions[sessionId] ?? emptySession();
      const msg: ConvMessage = {
        id: `${sessionId}-user-${Date.now()}`,
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
      };
      return {
        sessions: updateSession(s.sessions, sessionId, {
          messages: [...session.messages, msg],
        }),
      };
    });
  },

  onToolRunning(sessionId, toolId, name, input) {
    set((s) => {
      const session = s.sessions[sessionId] ?? emptySession();
      const block: RenderBlock = { type: 'tool', toolId, name, input, status: 'running' };
      const activeTurn = appendBlock(session.activeTurn, block);
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  onToolExecuted(sessionId, toolId, result) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const activeTurn = updateBlock(session.activeTurn, toolId, (b) => {
        if (b.type !== 'tool') return b;
        return { ...b, status: 'done' as const, result };
      });
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  onToolFailed(sessionId, toolId, error) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const activeTurn = updateBlock(session.activeTurn, toolId, (b) => {
        if (b.type !== 'tool') return b;
        return { ...b, status: 'failed' as const, result: error };
      });
      return { sessions: updateSession(s.sessions, sessionId, { activeTurn }) };
    });
  },

  onTurnComplete(sessionId) {
    set((s) => ({ sessions: updateSession(s.sessions, sessionId, { activeTurn: null }) }));
  },

  completeTurn(sessionId) {
    set((s) => {
      const session = s.sessions[sessionId];
      if (!session?.activeTurn) return s;
      const blocks = session.activeTurn.blocks;
      const content = blocks
        .filter((b) => b.type === 'text')
        .map((b) => (b as { text: string }).text)
        .join('');
      const msg: ConvMessage = {
        id: `${sessionId}-assistant-${Date.now()}`,
        role: 'assistant',
        content,
        createdAt: new Date().toISOString(),
        blocks,
      };
      return {
        sessions: updateSession(s.sessions, sessionId, {
          messages: [...session.messages, msg],
          activeTurn: null,
        }),
      };
    });
  },
}));
