import { StyleSheet, Text, View, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AgentList } from '@/src/components/subagents/AgentList';
import { useAgents } from '@/src/hooks/useAgents';
import { useTheme } from '@/src/theme/ThemeContext';
import type { Agent } from '@/src/types';

export default function SubAgentsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const colors = useTheme();
  const { data: agents = [] } = useAgents();

  function handleSelectAgent(agent: Agent) {
    router.push(`/subagents/${agent.id}?name=${agent.name}`);
  }

  return (
    <View style={[styles.container, { backgroundColor: colors.secondaryBackground }]}>
      <View
        style={[
          styles.header,
          { paddingTop: insets.top, backgroundColor: colors.background, borderBottomColor: colors.borderLight },
        ]}
      >
        <TouchableOpacity style={styles.backBtn} onPress={() => router.back()}>
          <Text style={[styles.backText, { color: colors.accent }]}>‹ 返回</Text>
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Sub-Agents</Text>
        <View style={styles.backBtn} />
      </View>
      <View style={styles.sectionHeader}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Agent 列表</Text>
        <Text style={[styles.sectionSubtitle, { color: colors.textSecondary }]}>
          先选一个 Sub-Agent，再进入它的会话列表和详情页。
        </Text>
      </View>
      <AgentList agents={agents} onSelect={handleSelectAgent} />
    </View>
  );
}

const styles = StyleSheet.create({
  container:       { flex: 1 },
  header: {
    minHeight: 48,
    borderBottomWidth: 1,
    flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12,
  },
  backBtn:         { width: 64 },
  backText:        { fontSize: 16 },
  headerTitle:     { flex: 1, textAlign: 'center', fontSize: 16, fontWeight: '600' },
  sectionHeader:   { paddingHorizontal: 16, paddingTop: 16, paddingBottom: 8 },
  sectionTitle:    { fontSize: 20, fontWeight: '700' },
  sectionSubtitle: { marginTop: 4, fontSize: 13, lineHeight: 18 },
});
