import axios from 'axios';
import { router } from 'expo-router';
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
      router.push('/(tabs)/settings');
    }
    return Promise.reject(error);
  },
);
