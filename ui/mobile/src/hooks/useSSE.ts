import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';
import { createSSEConnection } from '../api/sse';
import { useSessionStore } from '../store/session';
import { useAgentsStore } from '../store/agents';
import { useSettingsStore } from '../store/settings';
import type { SSEEvent, TurnDeltaData, AgentDeltaData, ApprovalRequiredData } from '../types';
import { useApprovalStore } from '../store/approval';

const MAX_RETRIES = 3;
const BASE_DELAY = 1000;

export function useSSE() {
  const jwtToken = useSettingsStore((s) => s.jwtToken);
  const queryClient = useQueryClient();
  const retryCount = useRef(0);
  const disconnectRef = useRef<(() => void) | null>(null);

  function handleEvent(event: SSEEvent) {
    retryCount.current = 0;
    if (event.type === 'turn.delta') {
      const d = event.data as TurnDeltaData;
      useSessionStore.getState().appendStreamingDelta(d.delta);
    } else if (event.type === 'turn.done') {
      useSessionStore.getState().clearStreaming();
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    } else if (event.type === 'agent.delta') {
      const d = event.data as AgentDeltaData;
      useAgentsStore.getState().appendAgentDelta(d.agentId, d.delta);
    } else if (event.type === 'agent.done') {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
    } else if (event.type.startsWith('task.')) {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    } else if (event.type === 'approval.required') {
      const d = event.data as ApprovalRequiredData;
      useApprovalStore.getState().setPending(d.approval);
    }
  }

  function connect() {
    disconnectRef.current?.();
    disconnectRef.current = createSSEConnection(handleEvent, (err) => {
      console.warn('SSE error:', err);
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

    const sub = AppState.addEventListener('change', (state) => {
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
      sub.remove();
    };
  }, [jwtToken]);
}
