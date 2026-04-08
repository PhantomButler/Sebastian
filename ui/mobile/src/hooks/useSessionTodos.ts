import { useQuery } from '@tanstack/react-query';
import { getSessionTodos } from '../api/todos';
import type { TodoItem } from '../types';

export function useSessionTodos(sessionId: string | null) {
  return useQuery({
    queryKey: ['session-todos', sessionId],
    queryFn: async (): Promise<TodoItem[]> => {
      if (!sessionId) return [];
      const { todos } = await getSessionTodos(sessionId);
      return todos;
    },
    enabled: !!sessionId,
  });
}
