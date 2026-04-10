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

// Static bottom padding: space for the Composer at rest.
const LIST_BOTTOM_PADDING = COMPOSER_DEFAULT_HEIGHT + 72;

// Trigger a chunk-scroll when actual content bottom is this many px above
// viewport bottom. Negative = above viewport bottom. Using COMPOSER_DEFAULT_HEIGHT
// as offset means we trigger just before content reaches the composer top.
const SCROLL_TRIGGER_PX = -(COMPOSER_DEFAULT_HEIGHT + 20);

// Fraction of viewport height used as a footer spacer during streaming.
// After each chunk-scroll to max offset, actual content sits at mid-screen
// and the spacer fills the lower half — no coordinate math needed.
const SPACER_RATIO = 0.5;

// Duration to hold the animation lock after each programmatic scroll (ms).
// Prevents overlapping scroll animations when streaming is fast.
const SCROLL_LOCK_MS = 500;

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

  // Live scroll metrics.
  const scrollOffsetRef = useRef(0);
  const contentHeightRef = useRef(0);
  const viewportHeightRef = useRef(0);

  // Animation lock: prevents overlapping programmatic scroll animations.
  const isScrollingRef = useRef(false);

  // Tracks previous nowStreaming value to detect the streaming-end transition.
  const prevNowStreamingRef = useRef(false);

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

  const messageCount = messages.length;
  const prevMessageCount = useRef(messageCount);
  useEffect(() => {
    if (messageCount > prevMessageCount.current) {
      isNearBottom.current = true;
    }
    prevMessageCount.current = messageCount;
  }, [messageCount]);

  const handleScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    scrollOffsetRef.current = contentOffset.y;
    contentHeightRef.current = contentSize.height;
    viewportHeightRef.current = layoutMeasurement.height;
    const distFromBottom = contentSize.height - contentOffset.y - layoutMeasurement.height;
    isNearBottom.current = distFromBottom < 300;
  }, []);

  // Non-streaming scroll: fires when a completed message is appended.
  const handleContentSizeChange = useCallback((_w: number, h: number) => {
    contentHeightRef.current = h;
    if (isNearBottom.current && !isStreaming.current) {
      flatListRef.current?.scrollToOffset({ offset: h, animated: true });
    }
  }, []);

  const nowStreaming = !!activeTurn && activeTurn.blocks.length > 0;

  // Streaming content length — changes on every SSE delta, driving the
  // scroll check without relying on a timer or onContentSizeChange.
  const streamingLen = useMemo(
    () =>
      activeTurn?.blocks.reduce(
        (acc, b) => acc + ('text' in b ? b.text.length : b.input.length),
        0,
      ) ?? 0,
    [activeTurn],
  );

  // Data-driven chunk-scroll: fires on every streaming update.
  // Uses exact scroll max (not 999999) so native animates smoothly.
  // Updates scrollOffsetRef immediately so the next check uses a fresh baseline
  // even if onScroll hasn't fired yet.
  useEffect(() => {
    if (!nowStreaming || !isNearBottom.current || isScrollingRef.current) return;
    const viewportH = viewportHeightRef.current || containerH;
    const spacerH = Math.round(viewportH * SPACER_RATIO);
    const actualContentH = contentHeightRef.current - spacerH;
    const dist = actualContentH - scrollOffsetRef.current - viewportH;
    if (dist < SCROLL_TRIGGER_PX) return;
    const targetOffset = Math.max(0, contentHeightRef.current - viewportH);
    isScrollingRef.current = true;
    scrollOffsetRef.current = targetOffset;
    flatListRef.current?.scrollToOffset({ offset: targetOffset, animated: true });
    setTimeout(() => { isScrollingRef.current = false; }, SCROLL_LOCK_MS);
  }, [streamingLen, nowStreaming, containerH]);

  // Streaming-end transition: when streaming finishes, instantly reposition
  // the scroll to where content will sit after the spacer is removed.
  // This prevents native from doing a visible clamp-jump when spacer height
  // disappears from the content.
  useEffect(() => {
    if (prevNowStreamingRef.current && !nowStreaming) {
      isScrollingRef.current = false;
      const viewportH = viewportHeightRef.current || containerH;
      const spacerH = Math.round(viewportH * SPACER_RATIO);
      const target = Math.max(0, contentHeightRef.current - spacerH - viewportH);
      scrollOffsetRef.current = target;
      flatListRef.current?.scrollToOffset({ offset: target, animated: false });
    }
    prevNowStreamingRef.current = nowStreaming;
  }, [nowStreaming, containerH]);

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
        onScroll={handleScroll}
        scrollEventThrottle={64}
        onContentSizeChange={handleContentSizeChange}
        ListFooterComponent={
          <>
            {errorBanner && (
              <ErrorBanner
                message={errorBanner.message}
                actionLabel={bannerActionLabel}
                onAction={onBannerAction ?? (() => {})}
              />
            )}
            {nowStreaming && containerH > 0 && (
              <View style={{ height: Math.round((viewportHeightRef.current || containerH) * SPACER_RATIO) }} />
            )}
          </>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
});
