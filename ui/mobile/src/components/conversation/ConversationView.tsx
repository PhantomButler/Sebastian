import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, View, StyleSheet, type LayoutChangeEvent, type NativeScrollEvent, type NativeSyntheticEvent, type ScrollViewProps } from 'react-native';
import { useConversation } from '../../hooks/useConversation';
import { useConversationStore } from '../../store/conversation';
import { useTheme } from '../../theme/ThemeContext';
import { UserBubble } from './UserBubble';
import { AssistantMessage } from './AssistantMessage';
import { ErrorBanner } from './ErrorBanner';
import { COMPOSER_DEFAULT_HEIGHT } from '../composer/constants';
import type { ConvMessage, ErrorBanner as ErrorBannerType, RenderBlock } from '../../types';

const LIST_BOTTOM_PADDING = COMPOSER_DEFAULT_HEIGHT + 72;

interface Props {
  sessionId: string | null;
  errorBanner?: ErrorBannerType | null;
  onBannerAction?: () => void;
  bannerActionLabel?: string;
  renderScrollComponent?: (props: ScrollViewProps) => React.ReactElement<ScrollViewProps>;
}

type ListItem =
  | { kind: 'message'; message: ConvMessage }
  | { kind: 'streaming'; blocks: RenderBlock[] };

export function ConversationView({
  sessionId,
  errorBanner,
  onBannerAction,
  bannerActionLabel,
  renderScrollComponent,
}: Props) {
  useConversation(sessionId);
  const colors = useTheme();

  const flatListRef = useRef<FlatList>(null);
  const isNearBottom = useRef(true);
  const isStreaming = useRef(false);

  const [containerH, setContainerH] = useState(0);
  const handleContainerLayout = useCallback((e: LayoutChangeEvent) => {
    const h = e.nativeEvent.layout.height;
    if (h > 0) setContainerH(h);
  }, []);

  const session = useConversationStore((s) =>
    sessionId ? s.sessions[sessionId] : undefined,
  );

  const messages = session?.messages ?? [];
  const activeTurn = session?.activeTurn ?? null;

  isStreaming.current = activeTurn !== null && activeTurn.blocks.length > 0;

  // Reset auto-follow when a new user message is sent.
  const messageCount = messages.length;
  const prevMessageCount = useRef(messageCount);
  useEffect(() => {
    if (messageCount > prevMessageCount.current) {
      isNearBottom.current = true;
    }
    prevMessageCount.current = messageCount;
  }, [messageCount]);

  // Fire as soon as the user's finger starts dragging — before onScroll fires.
  // This immediately disables auto-follow so the next streaming delta doesn't
  // snap the list back to bottom while the user is actively scrolling up.
  const handleScrollBeginDrag = useCallback(() => {
    isNearBottom.current = false;
  }, []);

  const handleScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const distFromBottom = contentSize.height - contentOffset.y - layoutMeasurement.height;
    // Re-engage auto-follow only when user scrolls back close to the bottom.
    isNearBottom.current = distFromBottom < 200;
  }, []);

  // Non-streaming: scroll to end when a completed message is appended.
  const handleContentSizeChange = useCallback((_w: number, h: number) => {
    if (isNearBottom.current && !isStreaming.current) {
      flatListRef.current?.scrollToOffset({ offset: h, animated: true });
    }
  }, []);

  const nowStreaming = !!activeTurn && activeTurn.blocks.length > 0;

  // Real-time auto-scroll during streaming: fires on every SSE delta.
  // Uses offset 99999 so native clamps to the actual scroll max — same pattern
  // as ChatGPT/Claude/DeepSeek web (scrollTop = scrollHeight on every token).
  // animated: false avoids overlapping animation conflicts.
  const streamingLen = useMemo(
    () =>
      activeTurn?.blocks.reduce(
        (acc, b) => acc + ('text' in b ? b.text.length : b.input.length),
        0,
      ) ?? 0,
    [activeTurn],
  );
  useEffect(() => {
    if (!nowStreaming || !isNearBottom.current) return;
    flatListRef.current?.scrollToOffset({ offset: 99999, animated: false });
  }, [streamingLen, nowStreaming]);

  const items: ListItem[] = [
    ...messages.map((m) => ({ kind: 'message' as const, message: m })),
    ...(activeTurn && activeTurn.blocks.length > 0
      ? [{ kind: 'streaming' as const, blocks: activeTurn.blocks }]
      : []),
  ];

  const renderItem = useCallback(({ item }: { item: ListItem }) => {
    if (item.kind === 'message') {
      const { message } = item;
      if (message.role === 'user') {
        return <UserBubble content={message.content} />;
      }
      return (
        <AssistantMessage
          blocks={
            message.blocks ?? [
              { type: 'text', blockId: message.id, text: message.content, done: true },
            ]
          }
        />
      );
    }
    return <AssistantMessage blocks={item.blocks} />;
  }, []);

  return (
    <View
      style={[styles.container, { backgroundColor: colors.background }]}
      onLayout={handleContainerLayout}
    >
      <FlatList
        ref={flatListRef}
        style={containerH > 0 ? { height: containerH } : { flex: 1 }}
        data={items}
        keyExtractor={(item, index) =>
          item.kind === 'message' ? item.message.id : `streaming-${index}`
        }
        renderItem={renderItem}
        renderScrollComponent={renderScrollComponent}
        contentContainerStyle={{ paddingTop: 12, paddingBottom: LIST_BOTTOM_PADDING }}
        onScrollBeginDrag={handleScrollBeginDrag}
        onScroll={handleScroll}
        scrollEventThrottle={64}
        onContentSizeChange={handleContentSizeChange}
        ListFooterComponent={
          errorBanner ? (
            <ErrorBanner
              message={errorBanner.message}
              actionLabel={bannerActionLabel}
              onAction={onBannerAction ?? (() => {})}
            />
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
});
