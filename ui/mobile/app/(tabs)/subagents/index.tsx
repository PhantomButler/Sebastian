import { StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AgentList } from '../../../src/components/subagents/AgentList';
import { useAgents } from '../../../src/hooks/useAgents';
import type { Agent } from '../../../src/types';

const MOCK_AGENTS: Agent[] = [
  {
    id: 'mock-research-agent',
    name: 'Research Assistant',
    status: 'working',
    goal: '跟进用户交办的研究任务，并同步整理出可追踪的执行过程。',
    createdAt: '2026-04-02T10:00:00Z',
  },
  {
    id: 'mock-task-runner',
    name: 'Task Runner',
    status: 'idle',
    goal: '负责执行结构化子任务，在需要时回传结果和待审批动作。',
    createdAt: '2026-04-02T09:28:00Z',
  },
];

export default function SubAgentsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data: agents = [] } = useAgents();
  const displayAgents = agents.length > 0 ? agents : MOCK_AGENTS;
  const showingMockAgents = agents.length === 0;

  function handleSelectAgent(agent: Agent) {
    router.push(`/subagents/${agent.id}?name=${agent.name}`);
  }

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top }]}>
        <Text style={styles.headerTitle}>Sub-Agents</Text>
      </View>
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Agent 列表</Text>
        <Text style={styles.sectionSubtitle}>
          先选一个 Sub-Agent，再进入它的会话列表和详情页。
        </Text>
      </View>
      {showingMockAgents ? (
        <View style={styles.notice}>
          <Text style={styles.noticeTitle}>当前展示的是调试假数据</Text>
          <Text style={styles.noticeText}>
            还没有拿到真实 Agent 列表时，先用这组数据验证二级导航流程。
          </Text>
        </View>
      ) : null}
      <AgentList agents={displayAgents} onSelect={handleSelectAgent} />
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
    justifyContent: 'center',
    paddingHorizontal: 12,
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#111111',
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
