import { FlatList, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import type { Agent } from '../../types';
import { AgentStatusBadge } from './AgentStatusBadge';

interface Props {
  agents: Agent[];
  onSelect: (agent: Agent) => void;
}

export function AgentList({ agents, onSelect }: Props) {
  if (agents.length === 0) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyText}>暂无可用的 Sub-Agent</Text>
      </View>
    );
  }

  return (
    <FlatList
      data={agents}
      keyExtractor={(agent) => agent.id}
      contentContainerStyle={styles.content}
      renderItem={({ item }) => (
        <TouchableOpacity style={styles.card} onPress={() => onSelect(item)}>
          <View style={styles.topRow}>
            <Text style={styles.name}>{item.name}</Text>
            <AgentStatusBadge status={item.status} />
          </View>
          <Text style={styles.goal} numberOfLines={2}>
            {item.goal}
          </Text>
          <View style={styles.footer}>
            <Text style={styles.footerText}>查看该 Agent 的会话与任务</Text>
            <Text style={styles.chevron}>›</Text>
          </View>
        </TouchableOpacity>
      )}
    />
  );
}

const styles = StyleSheet.create({
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  emptyText: { color: '#999999', fontSize: 14 },
  content: { paddingHorizontal: 16, paddingBottom: 24 },
  card: {
    marginBottom: 12,
    padding: 16,
    borderRadius: 16,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#E8E8E8',
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  name: { flex: 1, marginRight: 12, fontSize: 17, fontWeight: '600', color: '#111111' },
  goal: { marginTop: 10, fontSize: 13, lineHeight: 18, color: '#666666' },
  footer: {
    marginTop: 14,
    paddingTop: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#E6E6E6',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  footerText: { fontSize: 13, color: '#2F5FD0', fontWeight: '500' },
  chevron: { fontSize: 20, color: '#2F5FD0', lineHeight: 20 },
});
