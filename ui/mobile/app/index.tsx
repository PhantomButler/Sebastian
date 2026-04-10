import { useCallback, useMemo, useRef, useState } from 'react';
import { View, StyleSheet, Alert, TouchableOpacity, Text, type ScrollViewProps } from 'react-native';
import { ConfirmDialog } from '@/src/components/common/ConfirmDialog';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import axios from 'axios';
import {
  KeyboardGestureArea,
  KeyboardStickyView,
  KeyboardChatScrollView,
} from 'react-native-keyboard-controller';
import { useSessionStore } from '@/src/store/session';
import { useSessions } from '@/src/hooks/useSessions';
import { sendTurn, cancelTurn } from '@/src/api/turns';
import { deleteSession } from '@/src/api/sessions';
import type { ThinkingEffort } from '@/src/types';
import { useQueryClient } from '@tanstack/react-query';
import { SwipePager, type SwipePagerRef } from '@/src/components/common/SwipePager';
import { EmptyState } from '@/src/components/common/EmptyState';
import { AppSidebar } from '@/src/components/chat/AppSidebar';
import { TodoSidebar } from '@/src/components/chat/TodoSidebar';
import { Composer } from '@/src/components/composer';
import { ConversationView } from '@/src/components/conversation';
import { ErrorBanner } from '@/src/components/conversation/ErrorBanner';
import { useConversationStore } from '@/src/store/conversation';
import { useComposerStore } from '@/src/store/composer';
import { useTheme } from '@/src/theme/ThemeContext';
import { COMPOSER_DEFAULT_HEIGHT } from '@/src/components/composer/constants';

export default function ChatScreen() {
  const colors = useTheme();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const pagerRef = useRef<SwipePagerRef>(null);

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

  function handleBannerAction() {
    if (currentBanner?.code === 'no_llm_provider') {
      router.push('/settings/providers');
      return;
    }
    router.push('/settings');
  }

  const bannerActionLabel =
    currentBanner?.code === 'no_llm_provider' ? '前往模型与 Provider' : '前往设置';

  // KeyboardStickyView offset: when keyboard opens, Composer bottom sits at keyboard top.
  // insets.bottom compensates for SafeAreaView's bottom padding (which would double-stack
  // without this offset when keyboard is visible).
  const stickyOffset = useMemo(() => ({ opened: insets.bottom }), [insets.bottom]);

  // renderScrollComponent passes KeyboardChatScrollView to FlatList.
  // offset = insets.bottom makes KeyboardChatScrollView's scroll adjustment align with
  // how KeyboardStickyView positions the Composer.
  const renderScrollComponent = useCallback(
    (props: ScrollViewProps) => (
      <KeyboardChatScrollView
        {...props}
        keyboardDismissMode="interactive"
        keyboardLiftBehavior="always"
        offset={insets.bottom}
        contentInsetAdjustmentBehavior="never"
        automaticallyAdjustContentInsets={false}
      />
    ),
    [insets.bottom],
  );

  async function handleSend(text: string, opts: { effort: ThinkingEffort }) {
    try {
      const { sessionId } = await sendTurn(currentSessionId, text, opts.effort);
      if (!currentSessionId) {
        persistSession({
          id: sessionId,
          agent: 'sebastian',
          title: text.slice(0, 40),
          status: 'active',
          updated_at: new Date().toISOString(),
          task_count: 0,
          active_task_count: 0,
          depth: 0,
          parent_session_id: null,
          last_activity_at: new Date().toISOString(),
        });
        useComposerStore.getState().migrateDraftToSession(sessionId);
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
      throw err;
    }
  }

  async function handleStop() {
    if (currentSessionId) await cancelTurn(currentSessionId);
  }

  async function confirmDeleteSession() {
    const id = deleteTarget;
    if (!id) return;
    setDeleteTarget(null);
    try {
      await deleteSession(id);
      if (currentSessionId === id) setCurrentSession(null);
      useComposerStore.getState().clearSession(id);
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
      queryClient.invalidateQueries({ queryKey: ['agent-sessions'] });
    } catch {
      Alert.alert('删除失败，请重试');
    }
  }

  const isEmpty = !currentSessionId && !draftSession;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.container, { backgroundColor: colors.background }]}
    >
      <SwipePager
        ref={pagerRef}
        left={
          <AppSidebar
            sessions={sessions}
            currentSessionId={currentSessionId}
            draftSession={draftSession}
            onSelect={(id) => { setCurrentSession(id); pagerRef.current?.goToCenter(); }}
            onNewChat={() => { startDraft(); pagerRef.current?.goToCenter(); }}
            onDelete={setDeleteTarget}
            onClose={() => pagerRef.current?.goToCenter()}
          />
        }
        right={
          <TodoSidebar
            sessionId={currentSessionId}
            agentType="sebastian"
            onClose={() => pagerRef.current?.goToCenter()}
          />
        }
      >
        <View
          style={[
            styles.header,
            {
              paddingTop: insets.top,
              backgroundColor: colors.background,
              borderBottomColor: colors.borderLight,
            },
          ]}
        >
          <TouchableOpacity
            style={styles.menuButton}
            onPress={() => pagerRef.current?.goToLeft()}
          >
            <Text style={[styles.menuIcon, { color: colors.text }]}>☰</Text>
          </TouchableOpacity>
          <Text style={[styles.headerTitle, { color: colors.text }]}>Sebastian</Text>
        </View>

        <KeyboardGestureArea
          style={styles.gestureArea}
          interpolator="ios"
          offset={COMPOSER_DEFAULT_HEIGHT}
          textInputNativeID="composer-input"
        >
          {isEmpty ? (
            currentBanner ? (
              <View style={styles.emptyContainer}>
                <ErrorBanner
                  message={currentBanner.message}
                  actionLabel={bannerActionLabel}
                  onAction={handleBannerAction}
                />
              </View>
            ) : (
              <EmptyState message="向 Sebastian 发送消息开始对话" />
            )
          ) : (
            <ConversationView
              sessionId={currentSessionId}
              errorBanner={currentBanner}
              bannerActionLabel={bannerActionLabel}
              onBannerAction={handleBannerAction}
              renderScrollComponent={renderScrollComponent}
            />
          )}

          <KeyboardStickyView offset={stickyOffset} style={styles.stickyComposer}>
            <Composer
              sessionId={currentSessionId}
              isWorking={isWorking}
              onSend={handleSend}
              onStop={handleStop}
            />
          </KeyboardStickyView>
        </KeyboardGestureArea>
      </SwipePager>
      <ConfirmDialog
        visible={deleteTarget !== null}
        title="删除对话"
        message="确认删除这条对话记录？"
        confirmText="删除"
        destructive
        onCancel={() => setDeleteTarget(null)}
        onConfirm={confirmDeleteSession}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  emptyContainer: { flex: 1 },
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
  gestureArea: { flex: 1 },
  stickyComposer: {
    position: 'absolute',
    bottom: 0,
    width: '100%',
  },
});
