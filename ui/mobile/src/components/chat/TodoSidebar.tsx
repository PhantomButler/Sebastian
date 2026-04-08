import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getSessionTasks } from '../../api/sessions';
import { useSessionTodos } from '../../hooks/useSessionTodos';
import { useTheme } from '../../theme/ThemeContext';
import { TodoCircleIcon, SuccessCircleIcon } from '../common/Icons';
import type { TodoItem, TaskDetail } from '../../types';

interface Props {
  sessionId: string | null;
  agentType: string;
  onClose: () => void;
}

export function TodoSidebar({ sessionId, agentType }: Props) {
  const colors = useTheme();

  const { data: tasks = [] } = useQuery({
    queryKey: ['session-tasks', sessionId, agentType],
    queryFn: () => getSessionTasks(sessionId!, agentType),
    enabled: !!sessionId,
  });

  const { data: todos = [] } = useSessionTodos(sessionId);

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: colors.secondaryBackground }]} edges={['top', 'bottom']}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <Text style={[styles.sectionHeader, { color: colors.textSecondary }]}>任务</Text>
        {tasks.length === 0 ? (
          <Text style={[styles.emptyText, { color: colors.textSecondary }]}>暂无任务</Text>
        ) : (
          tasks.map((task) => <TaskRow key={task.id} task={task} />)
        )}

        <View style={[styles.divider, { backgroundColor: colors.borderLight }]} />

        <Text style={[styles.sectionHeader, { color: colors.textSecondary }]}>待办</Text>
        {todos.length === 0 ? (
          <Text style={[styles.emptyText, { color: colors.textSecondary }]}>暂无待办</Text>
        ) : (
          todos.map((todo, idx) => <TodoRow key={idx} todo={todo} />)
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function TaskRow({ task }: { task: TaskDetail }) {
  const colors = useTheme();
  return (
    <View style={styles.row}>
      <Text style={[styles.taskGoal, { color: colors.text }]} numberOfLines={2}>
        {task.goal}
      </Text>
      <Text style={[styles.taskStatus, { color: colors.textSecondary }]}>[{task.status}]</Text>
    </View>
  );
}

function TodoRow({ todo }: { todo: TodoItem }) {
  const colors = useTheme();
  const isCompleted = todo.status === 'completed';
  const isInProgress = todo.status === 'in_progress';

  const displayText = isInProgress ? todo.activeForm : todo.content;
  const textStyle = [
    styles.todoText,
    {
      color: isCompleted ? colors.textSecondary : colors.text,
      textDecorationLine: (isCompleted ? 'line-through' : 'none') as 'line-through' | 'none',
      fontWeight: (isInProgress ? '600' : '400') as '600' | '400',
    },
  ];

  return (
    <View style={styles.row}>
      {isCompleted ? (
        <SuccessCircleIcon size={18} />
      ) : (
        <TodoCircleIcon size={18} color={isInProgress ? '#007AFF' : undefined} />
      )}
      <Text style={textStyle} numberOfLines={3}>
        {displayText}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 16 },
  sectionHeader: {
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
    marginTop: 8,
    marginBottom: 10,
    letterSpacing: 0.5,
  },
  emptyText: { fontSize: 14, fontStyle: 'italic', paddingVertical: 4 },
  divider: { height: 1, marginVertical: 18 },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingVertical: 8,
    gap: 10,
  },
  taskGoal: { flex: 1, fontSize: 14 },
  taskStatus: { fontSize: 12 },
  todoText: { flex: 1, fontSize: 14, lineHeight: 20 },
});
