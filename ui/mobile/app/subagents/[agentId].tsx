import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { getAgentSessions } from '../../src/api/sessions';
import { SessionList } from '../../src/components/subagents/SessionList';
import type { SessionMeta } from '../../src/types';

const MOCK_SESSIONS: SessionMeta[] = [
  {
    id: 'mock-subagent-session',
    agent: 'Research Assistant',
    title: '模拟研究任务会话',
    status: 'active',
    updated_at: '2026-04-02T10:03:00Z',
    task_count: 3,
    active_task_count: 1,
  },
  {
    id: 'mock-followup-session',
    agent: 'Task Runner',
    title: '模拟后续跟进会话',
    status: 'idle',
    updated_at: '2026-04-02T09:28:00Z',
    task_count: 2,
    active_task_count: 0,
  },
];

export default function AgentSessionsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { agentId, name } = useLocalSearchParams<{ agentId: string; name?: string }>();
  const agentName = (Array.isArray(name) ? name[0] : name) ?? 'Sub-Agent';
  const normalizedAgentId = (Array.isArray(agentId) ? agentId[0] : agentId) ?? '';
  const isMockAgent = normalizedAgentId.startsWith('mock-');

  const { data: sessions = [] } = useQuery({
    queryKey: ['agent-sessions', agentName],
    queryFn: () => getAgentSessions(agentName),
    enabled: !!agentName && !isMockAgent,
  });

  const displaySessions = sessions.length > 0
    ? sessions
    : MOCK_SESSIONS.map((session, index) => ({
        ...session,
        agent: agentName,
        id: `${session.id}-${normalizedAgentId || 'preview'}-${index}`,
      }));
  const showingMockSessions = isMockAgent || sessions.length === 0;

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
      {showingMockSessions ? (
        <View style={styles.notice}>
          <Text style={styles.noticeTitle}>当前展示的是调试假数据</Text>
          <Text style={styles.noticeText}>
            这个 Agent 还没有真实会话时，先用模拟数据验证二级详情页跳转。
          </Text>
        </View>
      ) : null}
      <SessionList sessions={displaySessions} onSelect={handleSelectSession} />
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
  notice: {
    marginHorizontal: 16,
    marginTop: 8,
    marginBottom: 12,
    padding: 14,
    borderRadius: 12,
    backgroundColor: '#FFF7E8',
    borderWidth: 1,
    borderColor: '#F2D39B',
  },
  noticeTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#8A5A00',
  },
  noticeText: {
    marginTop: 4,
    fontSize: 13,
    lineHeight: 18,
    color: '#8A5A00',
  },
});
