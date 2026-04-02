import { apiClient } from './client';
import type { MessageRole, SessionMeta, TaskDetail } from '../types';

export interface SessionMessage {
  role: MessageRole;
  content: string;
  ts?: string;
}

export interface SessionDetail {
  session: SessionMeta;
  messages: SessionMessage[];
}

export async function getSessions(): Promise<SessionMeta[]> {
  const { data } = await apiClient.get<{ sessions: SessionMeta[] }>('/api/v1/sessions');
  return data.sessions;
}

export async function getAgentSessions(agent: string): Promise<SessionMeta[]> {
  const { data } = await apiClient.get<{ sessions: SessionMeta[] }>(
    `/api/v1/agents/${agent}/sessions`,
  );
  return data.sessions;
}

export async function getSessionDetail(
  sessionId: string,
  agent = 'sebastian',
): Promise<SessionDetail> {
  const { data } = await apiClient.get<SessionDetail>(`/api/v1/sessions/${sessionId}`, {
    params: { agent },
  });
  return data;
}

export async function sendTurnToSession(
  sessionId: string,
  content: string,
  agent = 'sebastian',
): Promise<{ sessionId: string; response: string }> {
  const { data } = await apiClient.post<{ session_id: string; response: string }>(
    `/api/v1/sessions/${sessionId}/turns`,
    { content },
    { params: { agent } },
  );
  return { sessionId: data.session_id, response: data.response };
}

export async function getSessionTasks(
  sessionId: string,
  agent = 'sebastian',
): Promise<TaskDetail[]> {
  const { data } = await apiClient.get<{ tasks: TaskDetail[] }>(
    `/api/v1/sessions/${sessionId}/tasks`,
    { params: { agent } },
  );
  return data.tasks;
}
