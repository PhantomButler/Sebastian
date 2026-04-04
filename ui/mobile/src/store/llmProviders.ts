import { create } from 'zustand';
import {
  getLLMProviders,
  createLLMProvider,
  updateLLMProvider,
  deleteLLMProvider,
} from '../api/llmProviders';
import type { LLMProvider, LLMProviderCreate } from '../types';

interface LLMProvidersState {
  providers: LLMProvider[];
  loading: boolean;
  error: string | null;
  fetch: () => Promise<void>;
  create: (body: LLMProviderCreate) => Promise<LLMProvider>;
  update: (id: string, updates: Partial<LLMProviderCreate>) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

export const useLLMProvidersStore = create<LLMProvidersState>((set) => ({
  providers: [],
  loading: false,
  error: null,

  fetch: async () => {
    set({ loading: true, error: null });
    try {
      const providers = await getLLMProviders();
      set({ providers, loading: false });
    } catch (err: unknown) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load providers',
      });
    }
  },

  create: async (body) => {
    const provider = await createLLMProvider(body);
    set((s) => ({ providers: [...s.providers, provider] }));
    return provider;
  },

  update: async (id, updates) => {
    const updated = await updateLLMProvider(id, updates);
    set((s) => ({
      providers: s.providers.map((p) => (p.id === id ? updated : p)),
    }));
  },

  remove: async (id) => {
    await deleteLLMProvider(id);
    set((s) => ({ providers: s.providers.filter((p) => p.id !== id) }));
  },
}));
