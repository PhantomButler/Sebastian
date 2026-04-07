import { FlatList, View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { DeleteIcon } from '../common/Icons';
import { NewChatFAB } from '../common/NewChatFAB';
import type { SessionMeta } from '../../types';

interface Props {
  sessions: SessionMeta[];
  currentSessionId: string | null;
  draftSession: boolean;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

const FEATURE_ITEMS = [
  { key: 'subagents', icon: '🤖', label: 'Sub-Agents', path: '/subagents', disabled: false },
  { key: 'settings',  icon: '⚙️', label: '设置',       path: '/settings',  disabled: false },
  { key: 'overview',  icon: '📊', label: '系统总览',   path: null,          disabled: true  },
] as const;

export function AppSidebar({
  sessions, currentSessionId, draftSession,
  onSelect, onNewChat, onDelete, onClose,
}: Props) {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  function handleNav(path: string) {
    onClose();
    router.push(path as any);
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Sebastian</Text>
      </View>

      {/* Feature entries */}
      <View style={styles.featureSection}>
        <Text style={styles.sectionLabel}>功能</Text>
        {FEATURE_ITEMS.map((item) => (
          <TouchableOpacity
            key={item.key}
            style={[styles.featureItem, item.disabled && styles.featureItemDisabled]}
            onPress={item.disabled ? undefined : () => handleNav(item.path!)}
            disabled={item.disabled}
            activeOpacity={0.7}
          >
            <Text style={styles.featureIcon}>{item.icon}</Text>
            <Text style={[styles.featureLabel, item.disabled && styles.featureLabelDisabled]}>
              {item.label}
            </Text>
            {item.disabled ? (
              <View style={styles.comingBadge}>
                <Text style={styles.comingBadgeText}>即将推出</Text>
              </View>
            ) : (
              <Text style={styles.chevron}>›</Text>
            )}
          </TouchableOpacity>
        ))}
      </View>

      {/* Session history */}
      <View style={styles.historySection}>
        <Text style={styles.sectionLabel}>历史对话</Text>
        <FlatList
          data={sessions}
          keyExtractor={(s) => s.id}
          renderItem={({ item }) => (
            <View style={[
              styles.sessionItem,
              item.id === currentSessionId && styles.sessionItemActive,
            ]}>
              <TouchableOpacity
                style={styles.sessionContent}
                onPress={() => onSelect(item.id)}
              >
                <Text style={styles.sessionTitle} numberOfLines={1}>
                  {item.title || '新对话'}
                </Text>
                <Text style={styles.sessionDate}>
                  {new Date(item.updated_at).toLocaleDateString()}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.deleteBtn}
                onPress={() => onDelete(item.id)}
              >
                <DeleteIcon size={18} color="#bbb" />
              </TouchableOpacity>
            </View>
          )}
        />
      </View>

      <NewChatFAB
        label="新对话"
        onPress={onNewChat}
        disabled={!!draftSession || !currentSessionId}
        style={styles.fab}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container:              { flex: 1, backgroundColor: '#f9f9f9' },
  header:                 { paddingHorizontal: 16, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: '#eee' },
  headerTitle:            { fontSize: 18, fontWeight: '700', color: '#111' },
  sectionLabel:           { fontSize: 11, color: '#aaa', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  featureSection:         { padding: 12, borderBottomWidth: 1, borderBottomColor: '#eee' },
  featureItem:            { flexDirection: 'row', alignItems: 'center', backgroundColor: '#fff', borderRadius: 8, padding: 10, marginBottom: 6, borderWidth: 1, borderColor: '#efefef' },
  featureItemDisabled:    { borderStyle: 'dashed', borderColor: '#e0e0e0' },
  featureIcon:            { fontSize: 16, marginRight: 10 },
  featureLabel:           { flex: 1, fontSize: 14, fontWeight: '500', color: '#111' },
  featureLabelDisabled:   { color: '#bbb' },
  chevron:                { fontSize: 18, color: '#ccc' },
  comingBadge:            { backgroundColor: '#eee', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  comingBadgeText:        { fontSize: 10, color: '#999' },
  historySection:         { flex: 1, padding: 12 },
  sessionItem:            { flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: '#eee' },
  sessionItemActive:      { backgroundColor: '#E8F0FE', borderRadius: 6 },
  sessionContent:         { flex: 1, paddingVertical: 10, paddingHorizontal: 4 },
  sessionTitle:           { fontWeight: '500', color: '#111', fontSize: 13 },
  sessionDate:            { color: '#999', fontSize: 11, marginTop: 2 },
  deleteBtn:              { paddingHorizontal: 12, paddingVertical: 10 },
  fab:                    { position: 'absolute', bottom: 24, right: 16 },
});
