import { apiClient } from './client';
import type { Agent } from '../types';

interface BackendAgentWorker {
  agent_id: string;
  status: 'idle' | 'busy';
  session_id: string | null;
  current_goal: string | null;
}

interface BackendAgentSummary {
  agent_type: string;
  name: string;
  description: string;
  workers: BackendAgentWorker[];
  queue_depth: number;
}

interface BackendAgentsResponse {
  agents: BackendAgentSummary[];
}

function mapAgentSummary(agent: BackendAgentSummary): Agent {
  const busyWorker = agent.workers.find((w) => w.status === 'busy' && w.current_goal);
  const busyCount = agent.workers.filter((w) => w.status === 'busy').length;
  const hasQueuedWork = agent.queue_depth > 0;
  const status = busyCount > 0 || hasQueuedWork ? 'working' : 'idle';
  const queueSuffix = hasQueuedWork ? `，队列 ${agent.queue_depth}` : '';
  const goalText = busyWorker?.current_goal ?? '';

  return {
    id: agent.agent_type,
    name: agent.name || agent.agent_type,
    status,
    goal: goalText || `${agent.workers.length} 个 worker，${busyCount} 个忙碌${queueSuffix}`,
    createdAt: '1970-01-01T00:00:00.000Z',
  };
}

export async function getAgents(): Promise<Agent[]> {
  const { data } = await apiClient.get<BackendAgentsResponse>('/api/v1/agents');
  return data.agents.map(mapAgentSummary);
}

export async function sendAgentCommand(agentId: string, content: string): Promise<void> {
  await apiClient.post(`/api/v1/agents/${agentId}/command`, { content });
}

export async function cancelAgent(agentId: string): Promise<void> {
  await apiClient.post(`/api/v1/agents/${agentId}/cancel`);
}
