import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';
import type { LLMProviderType } from '../types';

const KEYS = {
  serverUrl: 'settings_server_url',
  jwtToken: 'settings_jwt_token',
  llmProviderType: 'settings_llm_provider_type',
  llmApiKey: 'settings_llm_api_key',
  themeMode: 'settings_theme_mode',
} as const;

interface LocalLLMConfig {
  providerType: LLMProviderType;
  apiKey: string;
}

interface SettingsState {
  serverUrl: string;
  jwtToken: string | null;
  llmProvider: LocalLLMConfig | null;
  themeMode: 'system' | 'light' | 'dark';
  isLoaded: boolean;
  load: () => Promise<void>;
  setServerUrl: (url: string) => Promise<void>;
  setJwtToken: (token: string | null) => Promise<void>;
  setLlmProvider: (provider: LocalLLMConfig) => Promise<void>;
  setThemeMode: (mode: 'system' | 'light' | 'dark') => Promise<void>;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  serverUrl: '',
  jwtToken: null,
  llmProvider: null,
  themeMode: 'system',
  isLoaded: false,

  load: async () => {
    const [serverUrl, jwtToken, providerType, apiKey, themeMode] = await Promise.all([
      SecureStore.getItemAsync(KEYS.serverUrl),
      SecureStore.getItemAsync(KEYS.jwtToken),
      SecureStore.getItemAsync(KEYS.llmProviderType),
      SecureStore.getItemAsync(KEYS.llmApiKey),
      SecureStore.getItemAsync(KEYS.themeMode),
    ]);
    const llmProvider =
      providerType && apiKey
        ? { providerType: providerType as LLMProviderType, apiKey }
        : null;
    set({
      serverUrl: serverUrl ?? '',
      jwtToken: jwtToken ?? null,
      llmProvider,
      themeMode: (themeMode as 'system' | 'light' | 'dark') ?? 'system',
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
    await Promise.all([
      SecureStore.setItemAsync(KEYS.llmProviderType, provider.providerType),
      SecureStore.setItemAsync(KEYS.llmApiKey, provider.apiKey),
    ]);
    set({ llmProvider: provider });
  },

  setThemeMode: async (mode) => {
    await SecureStore.setItemAsync(KEYS.themeMode, mode);
    set({ themeMode: mode });
  },
}));
