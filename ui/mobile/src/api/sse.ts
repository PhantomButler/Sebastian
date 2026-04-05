import EventSource from 'react-native-sse';
import { useSettingsStore } from '../store/settings';
import type { SSEEvent } from '../types';

export type SSEHandler = (event: SSEEvent) => void;

/** 全局 SSE（task / approval 事件）。 */
export function createSSEConnection(
  onEvent: SSEHandler,
  onError: (err: Error) => void,
): () => void {
  const { serverUrl, jwtToken } = useSettingsStore.getState();

  const es = new EventSource(`${serverUrl}/api/v1/stream`, {
    headers: { Authorization: `Bearer ${jwtToken ?? ''}` },
  });

  es.addEventListener('message', (e) => {
    if (!e.data) return;
    try {
      const parsed = JSON.parse(e.data) as SSEEvent & { event?: string };
      onEvent({ type: parsed.type ?? parsed.event, data: parsed.data } as SSEEvent);
    } catch { /* skip malformed */ }
  });

  es.addEventListener('error', (e) => {
    if (e.type === 'error' || e.type === 'exception') {
      onError(new Error((e as { message?: string }).message ?? 'SSE error'));
    }
  });

  return () => es.close();
}

/** Per-session SSE（流式内容：turn.delta / thinking / tool）。支持 Last-Event-ID 续接。 */
export function createSessionSSEConnection(
  sessionId: string,
  onEvent: SSEHandler,
  onError: (err: Error) => void,
  lastEventId?: string,
): () => void {
  const { serverUrl, jwtToken } = useSettingsStore.getState();

  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwtToken ?? ''}`,
  };
  if (lastEventId) headers['Last-Event-ID'] = lastEventId;

  const es = new EventSource(
    `${serverUrl}/api/v1/sessions/${sessionId}/stream`,
    { headers },
  );

  es.addEventListener('message', (e) => {
    if (!e.data) return;
    try {
      const parsed = JSON.parse(e.data) as SSEEvent & { event?: string };
      onEvent({ type: parsed.type ?? parsed.event, data: parsed.data } as SSEEvent);
    } catch { /* skip malformed */ }
  });

  es.addEventListener('error', (e) => {
    if (e.type === 'error' || e.type === 'exception') {
      onError(new Error((e as { message?: string }).message ?? 'SSE error'));
    }
  });

  return () => es.close();
}
