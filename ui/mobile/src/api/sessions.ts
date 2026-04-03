import { apiClient } from './client';
import type { MessageRole, SessionMeta, TaskDetail } from '../types';

export interface SessionMessage {
  role: MessageRole;
  content: string;
  ts?: string;
}

interface BackendSessionMeta {
  id: string;
  agent_type: string;
  agent_id: string;
  title: string;
  status: SessionMeta['status'];
  updated_at: string;
  task_count: number;
  active_task_count: number;
}

export interface SessionDetail {
  session: SessionMeta;
  messages: SessionMessage[];
}

interface SessionsResponse {
  sessions: BackendSessionMeta[];
}

interface SessionDetailResponse {
  session: BackendSessionMeta;
  messages: SessionMessage[];
}

interface TurnResponse {
  session_id: string;
  ts: string;
}

function mapSessionMeta(session: BackendSessionMeta): SessionMeta {
  return {
    id: session.id,
    agent: session.agent_type,
    title: session.title,
    status: session.status,
    updated_at: session.updated_at,
    task_count: session.task_count,
    active_task_count: session.active_task_count,
  };
}

export async function getSessions(): Promise<SessionMeta[]> {
  const { data } = await apiClient.get<SessionsResponse>('/api/v1/sessions');
  return data.sessions.map(mapSessionMeta);
}

export async function getAgentSessions(agent: string): Promise<SessionMeta[]> {
  const { data } = await apiClient.get<SessionsResponse>(
    `/api/v1/agents/${agent}/sessions`,
  );
  return data.sessions.map(mapSessionMeta);
}

export async function getSessionDetail(
  sessionId: string,
  _agent = 'sebastian',
): Promise<SessionDetail> {
  const { data } = await apiClient.get<SessionDetailResponse>(`/api/v1/sessions/${sessionId}`);
  return {
    session: mapSessionMeta(data.session),
    messages: data.messages,
  };
}

export async function sendTurnToSession(
  sessionId: string,
  content: string,
  _agent = 'sebastian',
): Promise<{ sessionId: string; ts: string }> {
  const { data } = await apiClient.post<TurnResponse>(`/api/v1/sessions/${sessionId}/turns`, {
    content,
  });
  return { sessionId: data.session_id, ts: data.ts };
}

export async function getSessionTasks(
  sessionId: string,
  _agent = 'sebastian',
): Promise<TaskDetail[]> {
  const { data } = await apiClient.get<{ tasks: TaskDetail[] }>(`/api/v1/sessions/${sessionId}/tasks`);
  return data.tasks;
}
