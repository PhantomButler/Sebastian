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
  | 'task.planning_started'
  | 'task.planning_failed'
  | 'turn.received'
  | 'turn.response'
  | 'task.created'
  | 'task.started'
  | 'task.paused'
  | 'task.resumed'
  | 'task.completed'
  | 'task.failed'
  | 'task.cancelled'
  | 'agent.delegated'
  | 'agent.delegated.failed'
  | 'agent.escalated'
  | 'agent.result_received'
  | 'user.approval_requested'
  | 'user.approval_granted'
  | 'user.approval_denied'
  | 'user.intervened'
  | 'user.interrupted'
  | 'tool.registered'
  | 'tool.running'
  | 'tool.executed'
  | 'tool.failed';

export interface SSEEvent<T = unknown> {
  type: SSEEventType;
  data: T;
}

export interface TurnDeltaData { sessionId: string; delta: string; }
export interface AgentDeltaData { agentId: string; delta: string; }
export interface ApprovalRequiredData { approval: Approval; }

export type LLMProviderType = 'anthropic' | 'openai';
export type ThinkingFormat = 'reasoning_content' | 'think_tags' | null;

export interface LLMProvider {
  id: string;
  name: string;
  provider_type: LLMProviderType;
  base_url: string | null;
  api_key: string;
  model: string;
  thinking_format: ThinkingFormat;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMProviderCreate {
  name: string;
  provider_type: LLMProviderType;
  api_key: string;
  model: string;
  base_url?: string | null;
  thinking_format?: ThinkingFormat;
  is_default?: boolean;
}

export interface AuthResponse { token: string; }
export interface PaginatedMessages { items: Message[]; nextCursor: string | null; }
export interface PaginatedSessions { items: SessionMeta[]; nextCursor: string | null; }
