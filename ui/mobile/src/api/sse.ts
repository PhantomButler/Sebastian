import { useSettingsStore } from '../store/settings';
import type { SSEEvent } from '../types';

export type SSEHandler = (event: SSEEvent) => void;

export function createSSEConnection(onEvent: SSEHandler, onError: (err: Error) => void): () => void {
  const { serverUrl, jwtToken } = useSettingsStore.getState();
  let active = true;
  const controller = new AbortController();

  (async () => {
    try {
      const response = await fetch(`${serverUrl}/api/v1/stream`, {
        headers: { Authorization: `Bearer ${jwtToken ?? ''}` },
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`SSE connect failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (active) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6)) as SSEEvent;
              onEvent(event);
            } catch { /* skip malformed */ }
          }
        }
      }
    } catch (err) {
      if (active) onError(err instanceof Error ? err : new Error(String(err)));
    }
  })();

  return () => {
    active = false;
    controller.abort();
  };
}
