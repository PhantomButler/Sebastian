import { FlatList, View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import type { SessionMeta } from '../../types';

interface Props {
  sessions: SessionMeta[];
  currentSessionId: string | null;
  draftSession: boolean;
  onSelect: (id: string) => void;
  onNewChat: () => void;
}

export function ChatSidebar({ sessions, currentSessionId, draftSession, onSelect, onNewChat }: Props) {
  const showNewChat = !draftSession && (sessions.length > 0 || currentSessionId !== null);

  return (
    <View style={styles.container}>
      {showNewChat && (
        <TouchableOpacity style={styles.newBtn} onPress={onNewChat}>
          <Text style={styles.newBtnText}>+ 新对话</Text>
        </TouchableOpacity>
      )}
      <FlatList
        data={sessions}
        keyExtractor={(s) => s.id}
        renderItem={({ item }) => (
          <TouchableOpacity
            style={[styles.item, item.id === currentSessionId && styles.itemActive]}
            onPress={() => onSelect(item.id)}
          >
            <Text style={styles.itemTitle} numberOfLines={1}>{item.title || '新对话'}</Text>
            <Text style={styles.itemDate}>
              {new Date(item.updated_at).toLocaleDateString()}
            </Text>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, paddingTop: 48 },
  newBtn: { margin: 12, padding: 10, backgroundColor: '#007AFF', borderRadius: 8, alignItems: 'center' },
  newBtnText: { color: '#fff', fontWeight: 'bold' },
  item: { padding: 14, borderBottomWidth: 1, borderBottomColor: '#eee' },
  itemActive: { backgroundColor: '#E8F0FE' },
  itemTitle: { fontWeight: '500' },
  itemDate: { color: '#999', fontSize: 12, marginTop: 2 },
});
