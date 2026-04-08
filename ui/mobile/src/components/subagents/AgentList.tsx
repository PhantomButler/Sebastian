import { FlatList, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import type { Agent } from '../../types';
import { useTheme } from '../../theme/ThemeContext';
import { AgentStatusBadge } from './AgentStatusBadge';

interface Props {
  agents: Agent[];
  onSelect: (agent: Agent) => void;
}

export function AgentList({ agents, onSelect }: Props) {
  const colors = useTheme();

  if (agents.length === 0) {
    return (
      <View style={styles.empty}>
        <Text style={[styles.emptyText, { color: colors.textMuted }]}>暂无可用的 Sub-Agent</Text>
      </View>
    );
  }

  return (
    <FlatList
      data={agents}
      keyExtractor={(agent) => agent.id}
      contentContainerStyle={styles.content}
      renderItem={({ item }) => (
        <TouchableOpacity
          style={[styles.card, { backgroundColor: colors.cardBackground, borderColor: colors.borderLight }]}
          onPress={() => onSelect(item)}
        >
          <View style={styles.topRow}>
            <Text style={[styles.name, { color: colors.text }]}>{item.name}</Text>
            <AgentStatusBadge status={item.status} />
          </View>
          <Text style={[styles.goal, { color: colors.textSecondary }]} numberOfLines={2}>
            {item.description}
          </Text>
          <View style={[styles.footer, { borderTopColor: colors.borderLight }]}>
            <Text style={[styles.footerText, { color: colors.accent }]}>查看该 Agent 的会话与任务</Text>
            <Text style={[styles.chevron, { color: colors.accent }]}>›</Text>
          </View>
        </TouchableOpacity>
      )}
    />
  );
}

const styles = StyleSheet.create({
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  emptyText: { fontSize: 14 },
  content: { paddingHorizontal: 16, paddingBottom: 24 },
  card: {
    marginBottom: 12,
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  name: { flex: 1, marginRight: 12, fontSize: 17, fontWeight: '600' },
  goal: { marginTop: 10, fontSize: 13, lineHeight: 18 },
  footer: {
    marginTop: 14,
    paddingTop: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  footerText: { fontSize: 13, fontWeight: '500' },
  chevron: { fontSize: 20, lineHeight: 20 },
});
