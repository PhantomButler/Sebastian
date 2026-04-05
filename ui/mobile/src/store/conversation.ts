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
