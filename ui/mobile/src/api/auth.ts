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
