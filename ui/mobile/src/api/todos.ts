import { apiClient } from './client';
import type { SessionTodosResponse } from '../types';

export async function getSessionTodos(sessionId: string): Promise<SessionTodosResponse> {
  const { data } = await apiClient.get<SessionTodosResponse>(`/api/v1/sessions/${sessionId}/todos`);
  return data;
}
