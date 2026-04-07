import { useState } from 'react';
import { View, StyleSheet, Alert, TouchableOpacity, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import axios from 'axios';
import { useSessionStore } from '@/src/store/session';
import { useSessions } from '@/src/hooks/useSessions';
import { sendTurn, cancelTurn } from '@/src/api/turns';
import { deleteSession } from '@/src/api/sessions';
import { useQueryClient } from '@tanstack/react-query';
import { Sidebar } from '@/src/components/common/Sidebar';
import { EmptyState } from '@/src/components/common/EmptyState';
import { AppSidebar } from '@/src/components/chat/AppSidebar';
import { MessageInput } from '@/src/components/chat/MessageInput';
import { ConversationView } from '@/src/components/conversation';
import { ErrorBanner } from '@/src/components/conversation/ErrorBanner';
import { useConversationStore } from '@/src/store/conversation';
import { useTheme } from '@/src/theme/ThemeContext';

export default function ChatScreen() {
  const colors = useTheme();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const {
    currentSessionId, draftSession,
    setCurrentSession, startDraft, persistSession,
  } = useSessionStore();
  const { data: sessions = [] } = useSessions();
  const isWorking = useConversationStore(
    (s) => !!(currentSessionId && s.sessions[currentSessionId]?.activeTurn),
  );
  const currentBanner = useConversationStore((s) =>
    currentSessionId ? (s.sessions[currentSessionId]?.errorBanner ?? null) : s.draftErrorBanner,
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
        // 新建 session 后立即刷新侧边栏列表
        queryClient.invalidateQueries({ queryKey: ['sessions'] });
      }
      useConversationStore.getState().appendUserMessage(sessionId, text);
      queryClient.invalidateQueries({ queryKey: ['messages', sessionId] });
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 400) {
        const detail = err.response.data?.detail;
        if (detail?.code === 'no_llm_provider') {
          const banner = { code: detail.code, message: detail.message };
          const store = useConversationStore.getState();
          if (currentSessionId) {
            store.setErrorBanner(currentSessionId, banner);
          } else {
            store.setDraftErrorBanner(banner);
          }
          return;
        }
      }
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
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <View style={[styles.header, { paddingTop: insets.top, backgroundColor: colors.background, borderBottomColor: colors.borderLight }]}>
        <TouchableOpacity
          style={styles.menuButton}
          onPress={() => setSidebarOpen(true)}
        >
          <Text style={[styles.menuIcon, { color: colors.text }]}>☰</Text>
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Sebastian</Text>
      </View>

      {isEmpty ? (
        <EmptyState message="向 Sebastian 发送消息开始对话" />
      ) : (
        <ConversationView sessionId={currentSessionId} />
      )}

      {currentBanner && (
        <ErrorBanner
          message={currentBanner.message}
          onAction={() => router.push('/settings')}
        />
      )}
      <MessageInput isWorking={isWorking} onSend={handleSend} onStop={handleStop} />

      <Sidebar
        visible={sidebarOpen}
        onOpen={() => setSidebarOpen(true)}
        onClose={() => setSidebarOpen(false)}
      >
        <AppSidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          draftSession={draftSession}
          onSelect={(id) => { setCurrentSession(id); setSidebarOpen(false); }}
          onNewChat={() => { startDraft(); setSidebarOpen(false); }}
          onDelete={handleDeleteSession}
          onClose={() => setSidebarOpen(false)}
        />
      </Sidebar>
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
  menuButton:  { padding: 8 },
  menuIcon:    { fontSize: 20 },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 16,
    fontWeight: '600',
    marginRight: 36,
  },
});
