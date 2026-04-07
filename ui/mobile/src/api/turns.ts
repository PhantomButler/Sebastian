import axios from 'axios';
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
  try {
    await apiClient.post(`/api/v1/sessions/${sessionId}/cancel`);
  } catch (err) {
    // 404 = 后端已无活跃 stream（正常竞态），静默处理
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      return;
    }
    throw err;
  }
}
