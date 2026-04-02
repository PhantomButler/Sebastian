import { useQuery } from '@tanstack/react-query';
import { getSessionDetail } from '../api/sessions';
import type { Message } from '../types';

export function useMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ['messages', sessionId],
    queryFn: async (): Promise<Message[]> => {
      const detail = await getSessionDetail(sessionId!);
      return detail.messages.map((message, index) => ({
        id: String(index),
        sessionId: sessionId!,
        role: message.role,
        content: message.content,
        createdAt: message.ts ?? '',
      }));
    },
    enabled: !!sessionId,
  });
}
