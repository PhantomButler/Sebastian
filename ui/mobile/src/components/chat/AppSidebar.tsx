import { FlatList, View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { DeleteIcon } from '../common/Icons';
import { NewChatFAB } from '../common/NewChatFAB';
import { useTheme } from '../../theme/ThemeContext';
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
  { key: 'subagents', label: 'Sub-Agents', path: '/subagents', disabled: false },
  { key: 'settings',  label: '设置',       path: '/settings',  disabled: false },
  { key: 'overview',  label: '系统总览',   path: null,          disabled: true  },
] as const;

export function AppSidebar({
  sessions, currentSessionId, draftSession,
  onSelect, onNewChat, onDelete, onClose,
}: Props) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const colors = useTheme();

  function handleNav(path: string) {
    onClose();
    router.push(path as any);
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top, backgroundColor: colors.secondaryBackground }]}>
      {/* Header */}
      <View style={[styles.header, { borderBottomColor: colors.borderLight }]}>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Sebastian</Text>
      </View>

      {/* Feature entries */}
      <View style={[styles.featureSection, { borderBottomColor: colors.borderLight }]}>
        <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>功能</Text>
        {FEATURE_ITEMS.map((item) => (
          <TouchableOpacity
            key={item.key}
            style={[
              styles.featureItem,
              { backgroundColor: colors.cardBackground, borderColor: colors.borderLight },
              item.disabled && styles.featureItemDisabled,
              item.disabled && { borderColor: colors.borderLight },
            ]}
            onPress={item.disabled ? undefined : () => handleNav(item.path!)}
            disabled={item.disabled}
            activeOpacity={0.7}
          >
            <Text
              style={[
                styles.featureLabel,
                { color: colors.text },
                item.disabled && { color: colors.textMuted },
              ]}
            >
              {item.label}
            </Text>
            {item.disabled ? (
              <View style={[styles.comingBadge, { backgroundColor: colors.borderLight }]}>
                <Text style={[styles.comingBadgeText, { color: colors.textMuted }]}>即将推出</Text>
              </View>
            ) : (
              <Text style={[styles.chevron, { color: colors.textMuted }]}>›</Text>
            )}
          </TouchableOpacity>
        ))}
      </View>

      {/* Session history */}
      <View style={styles.historySection}>
        <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>历史对话</Text>
        <FlatList
          data={sessions}
          keyExtractor={(s) => s.id}
          renderItem={({ item }) => (
            <View style={[
              styles.sessionItem,
              { borderBottomColor: colors.borderLight },
              item.id === currentSessionId && [styles.sessionItemActive, { backgroundColor: colors.activeSessionBg }],
            ]}>
              <TouchableOpacity
                style={styles.sessionContent}
                onPress={() => onSelect(item.id)}
              >
                <Text style={[styles.sessionTitle, { color: colors.text }]} numberOfLines={1}>
                  {item.title || '新对话'}
                </Text>
                <Text style={[styles.sessionDate, { color: colors.textMuted }]}>
                  {new Date(item.updated_at).toLocaleDateString()}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.deleteBtn}
                onPress={() => onDelete(item.id)}
              >
                <DeleteIcon size={18} color={colors.textMuted} />
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
  container:              { flex: 1 },
  header:                 { paddingHorizontal: 16, paddingVertical: 14, borderBottomWidth: 1 },
  headerTitle:            { fontSize: 18, fontWeight: '700' },
  sectionLabel:           { fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  featureSection:         { padding: 12, borderBottomWidth: 1 },
  featureItem:            { flexDirection: 'row', alignItems: 'center', borderRadius: 8, padding: 10, marginBottom: 6, borderWidth: 1 },
  featureItemDisabled:    { borderStyle: 'dashed' },
  featureLabel:           { flex: 1, fontSize: 14, fontWeight: '500' },
  chevron:                { fontSize: 18 },
  comingBadge:            { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  comingBadgeText:        { fontSize: 10 },
  historySection:         { flex: 1, padding: 12 },
  sessionItem:            { flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1 },
  sessionItemActive:      { borderRadius: 6 },
  sessionContent:         { flex: 1, paddingVertical: 10, paddingHorizontal: 4 },
  sessionTitle:           { fontWeight: '500', fontSize: 13 },
  sessionDate:            { fontSize: 11, marginTop: 2 },
  deleteBtn:              { paddingHorizontal: 12, paddingVertical: 10 },
  fab:                    { position: 'absolute', bottom: 24, right: 16 },
});
