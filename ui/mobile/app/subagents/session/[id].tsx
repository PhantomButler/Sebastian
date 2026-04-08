import { useCallback, useMemo, useRef, useState } from 'react';
import { Alert, StyleSheet, Text, TouchableOpacity, View, type ScrollViewProps } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import {
  KeyboardGestureArea,
  KeyboardStickyView,
  KeyboardChatScrollView,
} from 'react-native-keyboard-controller';
import {
  createAgentSession,
  getSessionDetail,
  sendTurnToSession,
} from '../../../src/api/sessions';
import { useConversationStore } from '../../../src/store/conversation';
import { Composer } from '../../../src/components/composer';
import { ConversationView } from '../../../src/components/conversation';
import { ErrorBanner } from '../../../src/components/conversation/ErrorBanner';
import { COMPOSER_DEFAULT_HEIGHT } from '../../../src/components/composer/constants';
import { ContentPanGestureArea } from '../../../src/components/common/ContentPanGestureArea';
import { TodoSidebar } from '../../../src/components/chat/TodoSidebar';
import { Sidebar } from '../../../src/components/common/Sidebar';
import { useTheme } from '../../../src/theme/ThemeContext';

const MOCK_MESSAGES = [
  {
    id: 'mock-message-1',
    sessionId: 'mock-session',
    role: 'user' as const,
    content: '帮我复盘一下今天的持仓波动。',
    createdAt: '2026-04-02T10:00:00Z',
  },
  {
    id: 'mock-message-2',
    sessionId: 'mock-session',
    role: 'assistant' as const,
    content: '我已经把盘中异动拆成了两条任务，一条看新闻，一条看技术面。',
    createdAt: '2026-04-02T10:00:12Z',
  },
];

type MockDetail = {
  session: {
    id: string;
    agent: string;
    title: string;
    status: 'active' | 'idle' | 'archived';
    updated_at: string;
    task_count: number;
    active_task_count: number;
  };
  messages: Array<{ role: 'user' | 'assistant'; content: string; ts?: string }>;
};

function buildMockDetail(sessionId: string, agentName: string): MockDetail {
  return {
    session: {
      id: sessionId,
      agent: agentName,
      title: '模拟 Supervision 会话',
      status: 'active',
      updated_at: '2026-04-02T10:03:00Z',
      task_count: 0,
      active_task_count: 0,
    },
    messages: MOCK_MESSAGES.map((message) => ({
      role: message.role,
      content: message.content,
      ts: message.createdAt,
    })),
  };
}

export default function SessionDetailScreen() {
  const { id, agent = 'sebastian' } = useLocalSearchParams<{
    id: string;
    agent: string;
  }>();
  const sessionId = (Array.isArray(id) ? id[0] : id) ?? '';
  const agentName = (Array.isArray(agent) ? agent[0] : agent) ?? 'sebastian';
  const isMockSession = sessionId.startsWith('mock-');
  const isNewSession = sessionId === 'new';
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const colors = useTheme();
  const [sending, setSending] = useState(false);
  const [realSessionId, setRealSessionId] = useState<string | null>(null);
  const [todoSidebarOpen, setTodoSidebarOpen] = useState(false);
  const sendingRef = useRef(false);
  const effectiveSessionId = realSessionId || (isNewSession ? null : sessionId);
  const banner = useConversationStore(
    (s) => s.sessions[effectiveSessionId ?? sessionId]?.errorBanner ?? null,
  );

  const { data: remoteDetail } = useQuery({
    queryKey: ['session-detail', effectiveSessionId, agentName],
    queryFn: () => getSessionDetail(effectiveSessionId!, agentName),
    enabled: !!effectiveSessionId && !isMockSession,
  });

  const detail = useMemo(
    () => (isMockSession ? buildMockDetail(sessionId, agentName) : remoteDetail),
    [agentName, isMockSession, remoteDetail, sessionId],
  );
  const displayTitle = isNewSession && !realSessionId ? '新对话' : (detail?.session.title ?? '会话详情');

  const stickyOffset = useMemo(() => ({ opened: insets.bottom }), [insets.bottom]);

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

  const handleSend = useCallback(
    async (text: string, _opts?: { thinking: boolean }) => {
      if (isMockSession) {
        Alert.alert('模拟会话', '这是用于导航测试的假数据页面。');
        return;
      }
      if (sendingRef.current) return;
      sendingRef.current = true;
      setSending(true);
      try {
        if (isNewSession && !realSessionId) {
          const { sessionId: newId } = await createAgentSession(agentName, text);
          setRealSessionId(newId);
          router.replace(`/subagents/session/${newId}?agent=${agentName}`);
          return;
        }
        if (!effectiveSessionId) return;
        await sendTurnToSession(effectiveSessionId, text, agentName);
        useConversationStore.getState().appendUserMessage(effectiveSessionId, text);
        queryClient.invalidateQueries({
          queryKey: ['session-detail', effectiveSessionId, agentName],
        });
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 400) {
          const detail = err.response.data?.detail;
          if (detail?.code === 'no_llm_provider') {
            useConversationStore.getState().setErrorBanner(effectiveSessionId ?? sessionId, {
              code: detail.code,
              message: detail.message,
            });
            return;
          }
        }
        Alert.alert('发送失败，请重试');
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    },
    [agentName, effectiveSessionId, isMockSession, isNewSession, queryClient, realSessionId, router, sessionId],
  );

  return (
    <SafeAreaView edges={['bottom']} style={[styles.container, { backgroundColor: colors.secondaryBackground }]}>
      <View
        style={[
          styles.header,
          { paddingTop: insets.top, backgroundColor: colors.background, borderBottomColor: colors.borderLight },
        ]}
      >
        <TouchableOpacity style={styles.back} onPress={() => router.back()}>
          <Text style={[styles.backText, { color: colors.accent }]}>‹ 返回</Text>
        </TouchableOpacity>
        <Text style={[styles.title, { color: colors.text }]} numberOfLines={1}>
          {displayTitle}
        </Text>
      </View>

      <ContentPanGestureArea onOpenRight={() => setTodoSidebarOpen(true)}>
        <KeyboardGestureArea
          style={styles.gestureArea}
          interpolator="ios"
          offset={COMPOSER_DEFAULT_HEIGHT}
          textInputNativeID="composer-input"
        >
          <ConversationView
            sessionId={isMockSession ? null : effectiveSessionId}
            errorBanner={banner}
            onBannerAction={() => router.push('/settings')}
            renderScrollComponent={renderScrollComponent}
          />

          <KeyboardStickyView offset={stickyOffset} style={styles.stickyComposer}>
            <Composer
              sessionId={effectiveSessionId}
              isWorking={sending}
              onSend={handleSend}
              onStop={async () => {}}
            />
          </KeyboardStickyView>
        </KeyboardGestureArea>
      </ContentPanGestureArea>

      <Sidebar
        visible={todoSidebarOpen}
        side="right"
        onOpen={() => setTodoSidebarOpen(true)}
        onClose={() => setTodoSidebarOpen(false)}
      >
        <TodoSidebar
          sessionId={effectiveSessionId}
          agentType={agentName}
          onClose={() => setTodoSidebarOpen(false)}
        />
      </Sidebar>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    borderBottomWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 48,
    paddingHorizontal: 12,
  },
  back: { padding: 8, marginRight: 4 },
  backText: { fontSize: 16 },
  title: { flex: 1, fontSize: 15, fontWeight: '600' },
  gestureArea: { flex: 1 },
  stickyComposer: {
    position: 'absolute',
    bottom: 0,
    width: '100%',
  },
});
