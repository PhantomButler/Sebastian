import { apiClient } from './client';
import type { Agent } from '../types';

interface BackendAgentWorker {
  agent_id: string;
  status: 'idle' | 'busy';
  session_id: string | null;
}

interface BackendAgentSummary {
  agent_type: string;
  workers: BackendAgentWorker[];
  queue_depth: number;
}

interface BackendAgentsResponse {
  agents: BackendAgentSummary[];
}

function mapAgentSummary(agent: BackendAgentSummary): Agent {
  const busyWorkers = agent.workers.filter((worker) => worker.status === 'busy').length;
  const hasQueuedWork = agent.queue_depth > 0;
  const status = busyWorkers > 0 || hasQueuedWork ? 'working' : 'idle';
  const workerCount = agent.workers.length;
  const queueSuffix = hasQueuedWork ? `，队列 ${agent.queue_depth}` : '';

  return {
    id: agent.agent_type,
    name: agent.agent_type,
    status,
    goal: `${workerCount} 个 worker，${busyWorkers} 个忙碌${queueSuffix}`,
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
