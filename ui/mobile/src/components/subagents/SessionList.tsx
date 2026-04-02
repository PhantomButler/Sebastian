import { FlatList, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import type { SessionMeta } from '../../types';

interface Props {
  sessions: SessionMeta[];
  onSelect: (session: SessionMeta) => void;
}

function StatusDot({ status }: { status: SessionMeta['status'] }) {
  const color =
    status === 'active' ? '#34C759' : status === 'idle' ? '#999999' : '#CCCCCC';
  return <View style={[styles.dot, { backgroundColor: color }]} />;
}

function formatUpdatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '刚刚更新';
  return `${date.getMonth() + 1}月${date.getDate()}日 ${date
    .getHours()
    .toString()
    .padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
}

export function SessionList({ sessions, onSelect }: Props) {
  if (sessions.length === 0) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyText}>暂无进行中的会话</Text>
      </View>
    );
  }

  return (
    <FlatList
      data={sessions}
      keyExtractor={(session) => session.id}
      contentContainerStyle={styles.content}
      renderItem={({ item }) => (
        <TouchableOpacity style={styles.card} onPress={() => onSelect(item)}>
          <View style={styles.topRow}>
            <View style={styles.badge}>
              <StatusDot status={item.status} />
              <Text style={styles.badgeText}>{item.agent}</Text>
            </View>
            <Text style={styles.updatedAt}>{formatUpdatedAt(item.updated_at)}</Text>
          </View>
          <View style={styles.info}>
            <Text style={styles.title} numberOfLines={1}>
              {item.title}
            </Text>
            <Text style={styles.meta} numberOfLines={2}>
              {item.active_task_count > 0
                ? `${item.active_task_count} 个任务进行中`
                : '当前空闲，可继续追加指令'}
              {` · 共 ${item.task_count} 个任务`}
            </Text>
          </View>
          <View style={styles.footer}>
            <Text style={styles.footerText}>
              {item.status === 'active' ? '继续查看执行细节' : '查看会话与任务记录'}
            </Text>
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
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    backgroundColor: '#F2F6FF',
  },
  dot: { width: 10, height: 10, borderRadius: 5, marginRight: 8 },
  badgeText: { fontSize: 12, fontWeight: '600', color: '#2F5FD0' },
  updatedAt: { fontSize: 12, color: '#8A8A8A' },
  info: { marginTop: 14 },
  title: { fontSize: 16, fontWeight: '600', color: '#111111' },
  meta: { fontSize: 13, color: '#666666', marginTop: 6, lineHeight: 18 },
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
