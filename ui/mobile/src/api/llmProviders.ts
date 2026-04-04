import { apiClient } from './client';
import type { LLMProvider, LLMProviderCreate } from '../types';

interface ProvidersResponse {
  providers: LLMProvider[];
}

export async function getLLMProviders(): Promise<LLMProvider[]> {
  const { data } = await apiClient.get<ProvidersResponse>('/api/v1/llm-providers');
  return data.providers;
}

export async function createLLMProvider(body: LLMProviderCreate): Promise<LLMProvider> {
  const { data } = await apiClient.post<LLMProvider>('/api/v1/llm-providers', body);
  return data;
}

export async function updateLLMProvider(
  id: string,
  updates: Partial<LLMProviderCreate>,
): Promise<LLMProvider> {
  const { data } = await apiClient.put<LLMProvider>(`/api/v1/llm-providers/${id}`, updates);
  return data;
}

export async function deleteLLMProvider(id: string): Promise<void> {
  await apiClient.delete(`/api/v1/llm-providers/${id}`);
}
