import { apiClient } from './client';

export async function sendTurn(
  sessionId: string | null,
  content: string,
): Promise<{ sessionId: string; ts: string }> {
  const { data } = await apiClient.post<{ session_id: string; ts: string }>('/api/v1/turns', {
    session_id: sessionId,
    content,
  });
  return { sessionId: data.session_id, ts: data.ts };
}

export async function cancelTurn(sessionId: string): Promise<void> {
  await apiClient.post(`/api/v1/sessions/${sessionId}/cancel`);
}
