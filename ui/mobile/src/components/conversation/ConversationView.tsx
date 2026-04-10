import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, View, StyleSheet, TouchableOpacity, Text, type LayoutChangeEvent, type NativeScrollEvent, type NativeSyntheticEvent, type ScrollViewProps } from 'react-native';
import { useConversation } from '../../hooks/useConversation';
import { useConversationStore } from '../../store/conversation';
import { useTheme } from '../../theme/ThemeContext';
import { UserBubble } from './UserBubble';
import { AssistantMessage } from './AssistantMessage';
import { ErrorBanner } from './ErrorBanner';
import { COMPOSER_DEFAULT_HEIGHT } from '../composer/constants';
import { DownArrowIcon } from '../common/Icons';
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
  const [isFollowing, setIsFollowing] = useState(true);

  const setNearBottom = useCallback((value: boolean) => {
    isNearBottom.current = value;
    setIsFollowing(value);
  }, []);

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
      setNearBottom(true);
    }
    prevMessageCount.current = messageCount;
  }, [messageCount, setNearBottom]);

  // True while the user's finger is on the screen dragging the list.
  // While dragging, onScroll must NOT re-enable isNearBottom — otherwise every
  // 64 ms tick before the user has moved 200 px would flip it back to true and
  // the next streaming delta would immediately snap the list back to bottom.
  const userIsDraggingRef = useRef(false);

  const handleScrollBeginDrag = useCallback(() => {
    userIsDraggingRef.current = true;
    setNearBottom(false);
  }, [setNearBottom]);

  // Drag lifted: re-evaluate position. Momentum may still be running, so we
  // also check in onMomentumScrollEnd for the final resting place.
  const handleScrollEndDrag = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    userIsDraggingRef.current = false;
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const dist = contentSize.height - contentOffset.y - layoutMeasurement.height;
    setNearBottom(dist < 200);
  }, [setNearBottom]);

  const handleMomentumScrollEnd = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const dist = contentSize.height - contentOffset.y - layoutMeasurement.height;
    setNearBottom(dist < 200);
  }, [setNearBottom]);

  // onScroll: only update isNearBottom during programmatic scrolls (not drag).
  const handleScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    if (userIsDraggingRef.current) return;
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const dist = contentSize.height - contentOffset.y - layoutMeasurement.height;
    setNearBottom(dist < 200);
  }, [setNearBottom]);

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
    if (!nowStreaming || !isNearBottom.current || userIsDraggingRef.current) return;
    const frame = requestAnimationFrame(() => {
      if (!isNearBottom.current || userIsDraggingRef.current) return;
      flatListRef.current?.scrollToOffset({ offset: 99999, animated: false });
    });
    return () => cancelAnimationFrame(frame);
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

  const handleScrollToBottom = useCallback(() => {
    flatListRef.current?.scrollToOffset({ offset: 99999, animated: true });
    setNearBottom(true);
  }, [setNearBottom]);

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
        onScrollEndDrag={handleScrollEndDrag}
        onMomentumScrollEnd={handleMomentumScrollEnd}
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
      {!isFollowing && (
        <TouchableOpacity
          style={[styles.scrollToBottomBtn, { backgroundColor: colors.cardBackground, borderColor: colors.border }]}
          onPress={handleScrollToBottom}
          activeOpacity={0.8}
        >
          <DownArrowIcon size={24} color={colors.textSecondary} />
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollToBottomBtn: {
    position: 'absolute',
    bottom: LIST_BOTTOM_PADDING - 8,
    alignSelf: 'center',
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.15,
    shadowRadius: 4,
    elevation: 4,
  },
});
