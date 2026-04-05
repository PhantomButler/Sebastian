import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { createSessionSSEConnection } from '../api/sse';
import { getSessionDetail } from '../api/sessions';
import { useConversationStore } from '../store/conversation';
import { useSettingsStore } from '../store/settings';
import type { ConvMessage, SSEEvent } from '../types';

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;

/** Map raw API message list to ConvMessage array. */
function mapMessages(
  sessionId: string,
  messages: Array<{ role: string; content: string; ts?: string }>,
): ConvMessage[] {
  return messages.map((m, i) => ({
    id: `${sessionId}-${i}`,
    role: m.role as ConvMessage['role'],
    content: m.content,
    createdAt: m.ts ?? '',
  }));
}

/** 管理单个 session 的 hydrate + per-session SSE 生命周期。
 *  在 ConversationView mount 时调用，unmount 时自动 pause。 */
export function useConversation(sessionId: string | null): void {
  const jwtToken = useSettingsStore((s) => s.jwtToken);
  const queryClient = useQueryClient();
  const store = useConversationStore;
  const disconnectRef = useRef<(() => void) | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryRef = useRef(0);
  const lastEventIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!sessionId || !jwtToken) return;

    // Capture sessionId so all closures use the same stable reference
    const sid = sessionId;

    const { getOrInit, setStatus, setMessages } = store.getState();

    // Already live — nothing to do
    if (getOrInit(sid).status === 'live') return;

    setStatus(sid, 'loading');

    // Cancellation flag shared across all async callbacks in this effect run
    let cancelled = false;

    // 1. Hydrate historical messages
    getSessionDetail(sid)
      .then((detail) => {
        if (cancelled) return;
        setMessages(sid, mapMessages(sid, detail.messages));
      })
      .catch((err) => {
        console.warn(`[useConversation] Hydration failed for ${sid}:`, err);
        // Non-fatal — render with empty history, SSE fills live content
      });

    // 2. Connect per-session SSE
    function connect(): void {
      disconnectRef.current?.();

      disconnectRef.current = createSessionSSEConnection(
        sid,
        (event: SSEEvent) => {
          retryRef.current = 0;
          handleEvent(event);
        },
        (err) => {
          console.warn(`[useConversation] SSE error for ${sid}:`, err);
          if (retryRef.current < MAX_RETRIES) {
            const delay = BASE_DELAY_MS * 2 ** retryRef.current;
            retryRef.current += 1;
            retryTimerRef.current = setTimeout(connect, delay);
          }
        },
        lastEventIdRef.current,
      );

      store.getState().setStatus(sid, 'live');
    }

    function handleEvent(event: SSEEvent): void {
      const raw = event as SSEEvent & { id?: string };
      if (raw.id) lastEventIdRef.current = raw.id;

      const s = store.getState();

      switch (event.type) {
        case 'thinking_block.start': {
          const d = event.data as { block_id: string };
          s.onThinkingBlockStart(sid, d.block_id);
          break;
        }
        case 'turn.thinking_delta': {
          const d = event.data as { block_id: string; delta: string };
          s.onThinkingDelta(sid, d.block_id, d.delta);
          break;
        }
        case 'thinking_block.stop': {
          const d = event.data as { block_id: string };
          s.onThinkingBlockStop(sid, d.block_id);
          break;
        }
        case 'text_block.start': {
          const d = event.data as { block_id: string };
          s.onTextBlockStart(sid, d.block_id);
          break;
        }
        case 'turn.delta': {
          const d = event.data as { block_id: string; delta: string };
          s.onTextDelta(sid, d.block_id, d.delta);
          break;
        }
        case 'text_block.stop': {
          const d = event.data as { block_id: string };
          s.onTextBlockStop(sid, d.block_id);
          break;
        }
        case 'tool.running': {
          const d = event.data as { tool_id: string; name: string; input?: unknown };
          s.onToolRunning(
            sid,
            d.tool_id,
            d.name,
            typeof d.input === 'string' ? d.input : JSON.stringify(d.input ?? ''),
          );
          break;
        }
        case 'tool.executed': {
          const d = event.data as { tool_id: string; result_summary?: string };
          s.onToolExecuted(sid, d.tool_id, d.result_summary ?? '');
          break;
        }
        case 'tool.failed': {
          const d = event.data as { tool_id: string; error?: string };
          s.onToolFailed(sid, d.tool_id, d.error ?? 'failed');
          break;
        }
        case 'turn.response': {
          s.completeTurn(sid);
          queryClient.invalidateQueries({ queryKey: ['session-detail', sid] });
          break;
        }
        default:
          break;
      }
    }

    retryRef.current = 0;
    connect();

    return () => {
      cancelled = true;
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      disconnectRef.current?.();
      disconnectRef.current = null;
      store.getState().pauseSession(sid);
    };
  }, [sessionId, jwtToken, queryClient]);
}
