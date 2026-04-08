import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { StateStorage } from 'zustand/middleware';
import type { ThinkingEffort } from '../types';

const DRAFT_KEY = '__draft__';
const STORAGE_KEY = 'sebastian-composer-v2';

// Simple in-memory storage fallback for React Native
// In production, this could be upgraded to use AsyncStorage if available
const memoryStorage: Record<string, string> = {};

const createMemoryStorage = (): StateStorage => ({
  getItem: async (name: string) => {
    return memoryStorage[name] ?? null;
  },
  setItem: async (name: string, value: string) => {
    memoryStorage[name] = value;
  },
  removeItem: async (name: string) => {
    delete memoryStorage[name];
  },
});

interface ComposerStore {
  effortBySession: Record<string, ThinkingEffort>;
  lastUserChoice: ThinkingEffort;

  getEffort: (sessionId: string | null) => ThinkingEffort;
  setEffort: (sessionId: string | null, effort: ThinkingEffort) => void;
  migrateDraftToSession: (newSessionId: string) => void;
  clearSession: (sessionId: string) => void;
  clampAllToCapability: (allowedEfforts: readonly ThinkingEffort[]) => ThinkingEffort | null;
}

function clampOne(
  current: ThinkingEffort,
  allowed: readonly ThinkingEffort[],
): ThinkingEffort {
  if (allowed.includes(current)) return current;
  if (allowed.includes('on')) {
    return current === 'off' ? 'off' : 'on';
  }
  if (current === 'max' && allowed.includes('high')) return 'high';
  if (current === 'on' && allowed.includes('medium')) return 'medium';
  if (allowed.includes('off')) return 'off';
  return allowed[0] ?? 'off';
}

export const useComposerStore = create<ComposerStore>()(
  persist(
    (set, get) => ({
      effortBySession: {},
      lastUserChoice: 'off',

      getEffort(sessionId) {
        const key = sessionId ?? DRAFT_KEY;
        return get().effortBySession[key] ?? get().lastUserChoice;
      },

      setEffort(sessionId, effort) {
        const key = sessionId ?? DRAFT_KEY;
        set((s) => ({
          effortBySession: { ...s.effortBySession, [key]: effort },
          lastUserChoice: effort,
        }));
      },

      migrateDraftToSession(newSessionId) {
        set((s) => {
          const draftVal = s.effortBySession[DRAFT_KEY];
          if (draftVal === undefined) return s;
          const next = { ...s.effortBySession };
          next[newSessionId] = draftVal;
          delete next[DRAFT_KEY];
          return { effortBySession: next };
        });
      },

      clearSession(sessionId) {
        set((s) => {
          const next = { ...s.effortBySession };
          delete next[sessionId];
          return { effortBySession: next };
        });
      },

      clampAllToCapability(allowedEfforts) {
        const s = get();
        let changedFromValue: ThinkingEffort | null = null;
        const nextMap: Record<string, ThinkingEffort> = {};
        for (const [k, v] of Object.entries(s.effortBySession)) {
          const clamped = clampOne(v, allowedEfforts);
          if (clamped !== v) {
            nextMap[k] = clamped;
            if (k === DRAFT_KEY) changedFromValue = v;
          } else {
            nextMap[k] = v;
          }
        }
        const clampedLast = clampOne(s.lastUserChoice, allowedEfforts);
        const lastChanged = clampedLast !== s.lastUserChoice;
        set({
          effortBySession: nextMap,
          lastUserChoice: clampedLast,
        });
        return lastChanged ? s.lastUserChoice : changedFromValue;
      },
    }),
    {
      name: STORAGE_KEY,
      storage: createJSONStorage(createMemoryStorage),
      partialize: (s) => ({ lastUserChoice: s.lastUserChoice }),
    },
  ),
);
