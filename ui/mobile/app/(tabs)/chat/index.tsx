import { useState } from 'react';
import { View, StyleSheet, Alert, TouchableOpacity, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSessionStore } from '../../../src/store/session';
import { useSessions } from '../../../src/hooks/useSessions';
import { sendTurn, cancelTurn } from '../../../src/api/turns';
import { deleteSession } from '../../../src/api/sessions';
import { useQueryClient } from '@tanstack/react-query';
import { Sidebar } from '../../../src/components/common/Sidebar';
import { EmptyState } from '../../../src/components/common/EmptyState';
import { ChatSidebar } from '../../../src/components/chat/ChatSidebar';
import { MessageInput } from '../../../src/components/chat/MessageInput';
import { ConversationView } from '../../../src/components/conversation';
import { useConversationStore } from '../../../src/store/conversation';

export default function ChatScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { currentSessionId, draftSession, setCurrentSession, startDraft, persistSession } = useSessionStore();
  const { data: sessions = [] } = useSessions();
  const isWorking = useConversationStore(
    (s) => !!(currentSessionId && s.sessions[currentSessionId]?.activeTurn),
  );

  async function handleSend(text: string) {
    try {
      const { sessionId } = await sendTurn(currentSessionId, text);
      if (!currentSessionId) {
        persistSession({
          id: sessionId,
          agent: 'sebastian',
          title: text.slice(0, 40),
          status: 'active',
          updated_at: new Date().toISOString(),
          task_count: 0,
          active_task_count: 0,
        });
      }
      useConversationStore.getState().appendUserMessage(sessionId, text);
      queryClient.invalidateQueries({ queryKey: ['messages', sessionId] });
    } catch {
      Alert.alert('发送失败，请重试');
    }
  }

  async function handleStop() {
    if (currentSessionId) await cancelTurn(currentSessionId);
  }

  async function handleDeleteSession(id: string) {
    Alert.alert('删除对话', '确认删除这条对话记录？', [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteSession(id);
            if (currentSessionId === id) setCurrentSession(null);
            queryClient.invalidateQueries({ queryKey: ['sessions'] });
            queryClient.invalidateQueries({ queryKey: ['agent-sessions'] });
          } catch {
            Alert.alert('删除失败，请重试');
          }
        },
      },
    ]);
  }

  const isEmpty = !currentSessionId && !draftSession;

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top }]}>
        <TouchableOpacity style={styles.menuButton} onPress={() => setSidebarOpen(true)}>
          <Text style={styles.menuIcon}>☰</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Sebastian</Text>
      </View>
      {isEmpty ? (
        <EmptyState message="向 Sebastian 发送消息开始对话" />
      ) : (
        <ConversationView sessionId={currentSessionId} />
      )}
      <MessageInput isWorking={isWorking} onSend={handleSend} onStop={handleStop} />
      <Sidebar visible={sidebarOpen} onClose={() => setSidebarOpen(false)}>
        <ChatSidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          draftSession={draftSession}
          onSelect={(id) => { setCurrentSession(id); setSidebarOpen(false); }}
          onNewChat={() => { startDraft(); setSidebarOpen(false); }}
          onDelete={handleDeleteSession}
        />
      </Sidebar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0d0d0d' },
  header: {
    minHeight: 48,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#e0e0e0',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
  },
  menuButton: {
    padding: 8,
  },
  menuIcon: {
    fontSize: 20,
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 16,
    fontWeight: '600',
    marginRight: 36,
  },
});
