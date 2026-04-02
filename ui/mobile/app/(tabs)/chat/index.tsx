import { useState } from 'react';
import { View, StyleSheet, Alert, TouchableOpacity, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSessionStore } from '../../../src/store/session';
import { useMessages } from '../../../src/hooks/useMessages';
import { useSessions } from '../../../src/hooks/useSessions';
import { sendTurn, cancelTurn } from '../../../src/api/turns';
import { useQueryClient } from '@tanstack/react-query';
import { Sidebar } from '../../../src/components/common/Sidebar';
import { EmptyState } from '../../../src/components/common/EmptyState';
import { ChatSidebar } from '../../../src/components/chat/ChatSidebar';
import { MessageList } from '../../../src/components/chat/MessageList';
import { MessageInput } from '../../../src/components/chat/MessageInput';

export default function ChatScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { currentSessionId, draftSession, streamingMessage, setCurrentSession, startDraft, persistSession } = useSessionStore();
  const { data: sessions = [] } = useSessions();
  const { data: messages = [] } = useMessages(currentSessionId);
  const isWorking = !!streamingMessage;

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
      queryClient.invalidateQueries({ queryKey: ['messages', sessionId] });
    } catch {
      Alert.alert('发送失败，请重试');
    }
  }

  async function handleStop() {
    if (currentSessionId) await cancelTurn(currentSessionId);
  }

  const isEmpty = !currentSessionId && !draftSession;

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top }]}>
        <TouchableOpacity style={styles.menuButton} onPress={() => setSidebarOpen(true)}>
          <Text style={styles.menuIcon}>☰</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>对话</Text>
      </View>
      {isEmpty ? (
        <EmptyState message="发送消息开始对话" />
      ) : (
        <MessageList messages={messages} streamingContent={streamingMessage} />
      )}
      <MessageInput isWorking={isWorking} onSend={handleSend} onStop={handleStop} />
      <Sidebar visible={sidebarOpen} onClose={() => setSidebarOpen(false)}>
        <ChatSidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          draftSession={draftSession}
          onSelect={(id) => { setCurrentSession(id); setSidebarOpen(false); }}
          onNewChat={() => { startDraft(); setSidebarOpen(false); }}
        />
      </Sidebar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
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
