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
  status: 'active' | 'idle' | 'completed' | 'failed' | 'stalled' | 'cancelled';
  updated_at: string;
  task_count: number;
  active_task_count: number;
  depth: number;
  parent_session_id: string | null;
  last_activity_at: string;
}

export type AgentStatus = 'idle' | 'working';

export interface Agent {
  id: string;
  name: string;
  description: string;
  status: AgentStatus;
  active_session_count: number;
  max_children: number;
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
  assigned_agent: string;
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
  | 'turn.cancelled'
  | 'turn.delta'
  | 'turn.thinking_delta'
  | 'thinking_block.start'
  | 'thinking_block.stop'
  | 'text_block.start'
  | 'text_block.stop'
  | 'tool_block.start'
  | 'tool_block.stop'
  | 'turn.interrupted'
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
  | 'tool.failed'
  | 'session.completed'
  | 'session.failed'
  | 'session.stalled';

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

export interface AuthResponse { access_token: string; token_type: string; }
export interface PaginatedMessages { items: Message[]; nextCursor: string | null; }
export interface PaginatedSessions { items: SessionMeta[]; nextCursor: string | null; }

// ── Conversation rendering types ──────────────────────────────────────────

export type RenderBlock =
  | { type: 'thinking'; blockId: string; text: string; done: boolean }
  | { type: 'text';     blockId: string; text: string; done: boolean }
  | { type: 'tool';     toolId: string;  name: string; input: string;
      status: 'running' | 'done' | 'failed'; result?: string };

export interface ActiveTurn {
  blocks: RenderBlock[];
  blockMap: Map<string, RenderBlock>;
}

export interface ConvMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
  /** Present on assistant messages rendered from a live turn; absent for hydrated messages. */
  blocks?: RenderBlock[];
}

export interface ErrorBanner {
  code: string;
  message: string;
}

export interface ConvSessionState {
  status: 'idle' | 'loading' | 'live' | 'paused';
  messages: ConvMessage[];
  activeTurn: ActiveTurn | null;
  errorBanner: ErrorBanner | null;
}
