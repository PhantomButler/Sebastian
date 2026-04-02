import { Text, StyleSheet } from 'react-native';
import type { AgentStatus, TaskStatus } from '../../types';

const COLOR: Record<string, string> = {
  idle: '#999',
  working: '#007AFF',
  waiting_approval: '#FF9500',
  completed: '#34C759',
  failed: '#FF3B30',
  created: '#999',
  planning: '#5AC8FA',
  running: '#007AFF',
  paused: '#FF9500',
  cancelled: '#999',
};

interface Props { status: AgentStatus | TaskStatus; }

export function StatusBadge({ status }: Props) {
  return (
    <Text style={[styles.badge, { backgroundColor: COLOR[status] ?? '#999' }]}>
      {status}
    </Text>
  );
}

const styles = StyleSheet.create({
  badge: { color: '#fff', fontSize: 11, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, overflow: 'hidden' },
});
