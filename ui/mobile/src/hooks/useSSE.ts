import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';
import { createSSEConnection } from '../api/sse';
import { useAgentsStore } from '../store/agents';
import { useSessionStore } from '../store/session';
import { useSettingsStore } from '../store/settings';
import type {
  AgentDeltaData,
  Approval,
  ApprovalRequiredData,
  SSEEvent,
  TurnDeltaData,
} from '../types';

const MAX_RETRIES = 3;
const BASE_DELAY = 1000;

interface UseSSEOptions {
  onApprovalRequired?: (approval: Approval) => void;
}

export function useSSE(options?: UseSSEOptions) {
  const jwtToken = useSettingsStore((state) => state.jwtToken);
  const queryClient = useQueryClient();
  const retryCount = useRef(0);
  const disconnectRef = useRef<(() => void) | null>(null);
  const approvalHandler = options?.onApprovalRequired;

  function handleEvent(event: SSEEvent) {
    retryCount.current = 0;

    if (event.type === 'turn.delta') {
      const data = event.data as TurnDeltaData;
      useSessionStore.getState().appendStreamingDelta(data.delta);
    } else if (event.type === 'turn.done') {
      useSessionStore.getState().clearStreaming();
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    } else if (event.type === 'agent.delta') {
      const data = event.data as AgentDeltaData;
      useAgentsStore.getState().appendAgentDelta(data.agentId, data.delta);
    } else if (event.type === 'agent.done') {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
    } else if (event.type.startsWith('task.')) {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['agent-sessions'] });
      queryClient.invalidateQueries({ queryKey: ['session-tasks'] });
    } else if (event.type === 'approval.required') {
      const data = event.data as ApprovalRequiredData;
      approvalHandler?.(data.approval);
    }
  }

  function connect() {
    disconnectRef.current?.();
    disconnectRef.current = createSSEConnection(handleEvent, (error) => {
      console.warn('SSE error:', error);
      if (retryCount.current < MAX_RETRIES) {
        const delay = BASE_DELAY * 2 ** retryCount.current;
        retryCount.current += 1;
        setTimeout(connect, delay);
      }
    });
  }

  useEffect(() => {
    if (!jwtToken) return;

    connect();

    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        connect();
        queryClient.invalidateQueries();
      } else if (state === 'background') {
        disconnectRef.current?.();
        disconnectRef.current = null;
      }
    });

    return () => {
      disconnectRef.current?.();
      subscription.remove();
    };
  }, [approvalHandler, jwtToken, queryClient]);
}
