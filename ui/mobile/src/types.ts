export type MessageRole = 'user' | 'assistant';

export interface Message {
  id: string;
  sessionId: string;
  role: MessageRole;
  content: string;
  createdAt: string;
}

export interface SessionMeta {
  id: string;
  agent: string;
  title: string;
  status: 'active' | 'idle' | 'archived';
  updated_at: string;
  task_count: number;
  active_task_count: number;
}

export type AgentStatus = 'idle' | 'working' | 'waiting_approval' | 'completed' | 'failed';

export interface Agent {
  id: string;
  name: string;
  status: AgentStatus;
  goal: string;
  createdAt: string;
}

export type TaskStatus =
  | 'created'
  | 'planning'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface Task {
  id: string;
  goal: string;
  status: TaskStatus;
  agentId: string | null;
  createdAt: string;
  completedAt: string | null;
}

export interface TaskDetail {
  id: string;
  session_id: string;
  goal: string;
  status: TaskStatus;
  assigned_agent: string;
  created_at: string;
  completed_at: string | null;
}

export interface Approval {
  id: string;
  taskId: string;
  description: string;
  requestedAt: string;
}

export type SSEEventType =
  | 'turn.delta' | 'turn.done'
  | 'agent.delta' | 'agent.done'
  | 'task.created' | 'task.updated' | 'task.completed' | 'task.failed'
  | 'approval.required';

export interface SSEEvent<T = unknown> {
  type: SSEEventType;
  data: T;
}

export interface TurnDeltaData { sessionId: string; delta: string; }
export interface AgentDeltaData { agentId: string; delta: string; }
export interface ApprovalRequiredData { approval: Approval; }

export type LLMProviderName = 'anthropic' | 'openai';
export interface LLMProvider { name: LLMProviderName; apiKey: string; }

export interface AuthResponse { token: string; }
export interface PaginatedMessages { items: Message[]; nextCursor: string | null; }
export interface PaginatedSessions { items: SessionMeta[]; nextCursor: string | null; }
