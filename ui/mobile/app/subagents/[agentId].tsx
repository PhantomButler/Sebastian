import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { deleteSession, getAgentSessions } from '../../src/api/sessions';
import { SessionList } from '../../src/components/subagents/SessionList';
import { NewChatFAB } from '../../src/components/common/NewChatFAB';
import { useTheme } from '../../src/theme/ThemeContext';
import type { SessionMeta } from '../../src/types';

export default function AgentSessionsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const colors = useTheme();
  const { agentId, name } = useLocalSearchParams<{ agentId: string; name?: string }>();
  const agentName = (Array.isArray(name) ? name[0] : name) ?? 'Sub-Agent';
  const normalizedAgentId = (Array.isArray(agentId) ? agentId[0] : agentId) ?? '';

  const { data: sessions = [] } = useQuery({
    queryKey: ['agent-sessions', normalizedAgentId],
    queryFn: () => getAgentSessions(normalizedAgentId),
    enabled: !!normalizedAgentId,
  });

  const { mutate: handleDeleteSession } = useMutation({
    mutationFn: (session: SessionMeta) => deleteSession(session.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-sessions', normalizedAgentId] });
    },
  });

  function handleSelectSession(session: SessionMeta) {
    router.push(`/subagents/session/${session.id}?agent=${session.agent}`);
  }

  function handleNewChat() {
    router.push(`/subagents/session/new?agent=${normalizedAgentId}`);
  }

  return (
    <View style={[styles.container, { backgroundColor: colors.secondaryBackground }]}>
      <View
        style={[
          styles.header,
          { paddingTop: insets.top, backgroundColor: colors.background, borderBottomColor: colors.borderLight },
        ]}
      >
        <TouchableOpacity style={styles.back} onPress={() => router.back()}>
          <Text style={[styles.backText, { color: colors.accent }]}>‹ 返回</Text>
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: colors.text }]} numberOfLines={1}>
          {agentName}
        </Text>
      </View>
      <View style={styles.sectionHeader}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>会话列表</Text>
        <Text style={[styles.sectionSubtitle, { color: colors.textSecondary }]}>
          选择一个会话，继续查看消息流和任务执行状态。
        </Text>
      </View>
      <SessionList sessions={sessions} onSelect={handleSelectSession} onDelete={handleDeleteSession} />
      <NewChatFAB
        label="新对话"
        onPress={handleNewChat}
        style={styles.fab}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    minHeight: 48,
    borderBottomWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
  },
  back: { padding: 8, marginRight: 4 },
  backText: { fontSize: 16 },
  headerTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
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
  },
  sectionSubtitle: {
    marginTop: 4,
    fontSize: 13,
    lineHeight: 18,
  },
  fab: {
    position: 'absolute',
    bottom: 24,
    right: 16,
  },
});
