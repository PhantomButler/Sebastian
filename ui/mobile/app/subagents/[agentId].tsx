import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { getAgentSessions } from '../../src/api/sessions';
import { SessionList } from '../../src/components/subagents/SessionList';
import type { SessionMeta } from '../../src/types';

export default function AgentSessionsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { agentId, name } = useLocalSearchParams<{ agentId: string; name?: string }>();
  const agentName = (Array.isArray(name) ? name[0] : name) ?? 'Sub-Agent';
  const normalizedAgentId = (Array.isArray(agentId) ? agentId[0] : agentId) ?? '';

  const { data: sessions = [] } = useQuery({
    queryKey: ['agent-sessions', normalizedAgentId],
    queryFn: () => getAgentSessions(normalizedAgentId),
    enabled: !!normalizedAgentId,
  });

  function handleSelectSession(session: SessionMeta) {
    router.push(`/subagents/session/${session.id}?agent=${session.agent}`);
  }

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top }]}>
        <TouchableOpacity style={styles.back} onPress={() => router.back()}>
          <Text style={styles.backText}>‹ 返回</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle} numberOfLines={1}>
          {agentName}
        </Text>
      </View>
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>会话列表</Text>
        <Text style={styles.sectionSubtitle}>
          选择一个会话，继续查看消息流和任务执行状态。
        </Text>
      </View>
      <SessionList sessions={sessions} onSelect={handleSelectSession} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F5F5' },
  header: {
    minHeight: 48,
    backgroundColor: '#FFFFFF',
    borderBottomWidth: 1,
    borderBottomColor: '#E0E0E0',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
  },
  back: { padding: 8, marginRight: 4 },
  backText: { fontSize: 16, color: '#007AFF' },
  headerTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
    color: '#111111',
    marginRight: 36,
    textAlign: 'center',
  },
  sectionHeader: {
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 8,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111111',
  },
  sectionSubtitle: {
    marginTop: 4,
    fontSize: 13,
    lineHeight: 18,
    color: '#6B6B6B',
  },
});
