import { useCallback, useEffect, useRef, useState } from 'react';
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
// KeyboardChatScrollView automatically adds keyboard height on top of this.
const LIST_BOTTOM_PADDING = COMPOSER_DEFAULT_HEIGHT + 72;

// Streaming chunk-scroll: check every SCROLL_INTERVAL_MS whether content has
// grown past the viewport bottom. When it has, scroll to max offset so that
// the Footer Spacer (SPACER_RATIO of viewport) sits below actual content,
// leaving a half-screen of breathing room and naturally anchoring the content
// bottom to the viewport center.
const SCROLL_INTERVAL_MS = 400;
// A small negative tolerance: trigger just before content reaches viewport bottom.
const SCROLL_TRIGGER_PX = -20;
// Fraction of viewport height used as the footer spacer during streaming.
const SPACER_RATIO = 0.5;

interface Props {
  sessionId: string | null;
  errorBanner?: ErrorBannerType | null;
  onBannerAction?: () => void;
  bannerActionLabel?: string;
  // Pass KeyboardChatScrollView as renderScrollComponent for keyboard-aware scrolling.
  // If omitted, FlatList uses its built-in ScrollView (e.g. in non-chat contexts).
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

  // Live scroll metrics — updated by both onScroll and onContentSizeChange.
  const scrollOffsetRef = useRef(0);
  const contentHeightRef = useRef(0);
  const viewportHeightRef = useRef(0);

  // Measure the container's actual pixel height so FlatList always has
  // a bounded scroll region, even if the flex chain above is broken.
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

  // Track streaming state for scroll behavior
  isStreaming.current = activeTurn !== null && activeTurn.blocks.length > 0;

  // When a new user message is sent, reset to auto-follow
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
    // onScroll always carries the latest contentSize — more reliable than waiting for
    // onContentSizeChange alone, which can lag on async layout passes.
    contentHeightRef.current = contentSize.height;
    viewportHeightRef.current = layoutMeasurement.height;
    const distFromBottom = contentSize.height - contentOffset.y - layoutMeasurement.height;
    isNearBottom.current = distFromBottom < 300;
  }, []);

  // Non-streaming scroll: when a completed message is appended, scroll to end.
  const handleContentSizeChange = useCallback((_w: number, h: number) => {
    contentHeightRef.current = h;
    if (isNearBottom.current && !isStreaming.current) {
      flatListRef.current?.scrollToOffset({ offset: h, animated: true });
    }
  }, []);

  // Streaming chunk-scroll with Footer Spacer technique:
  // While streaming, a spacer (SPACER_RATIO * viewportH) is appended to the list footer.
  // This means scrolling to offset 999999 (clamped by native to max) always leaves
  // actual content sitting at the top ~50% of the screen — no offset math needed.
  // Each interval tick checks whether actual content has grown past the viewport bottom;
  // if so, we trigger one scroll-to-max.
  const nowStreaming = !!activeTurn && activeTurn.blocks.length > 0;
  useEffect(() => {
    if (!nowStreaming) return;
    const id = setInterval(() => {
      if (!isNearBottom.current) return;
      const viewportH = viewportHeightRef.current || containerH;
      const spacerH = Math.round(viewportH * SPACER_RATIO);
      // Actual content bottom relative to viewport bottom (spacer excluded).
      const actualContentH = contentHeightRef.current - spacerH;
      const dist = actualContentH - scrollOffsetRef.current - viewportH;
      if (dist < SCROLL_TRIGGER_PX) return;
      flatListRef.current?.scrollToOffset({ offset: 999999, animated: true });
    }, SCROLL_INTERVAL_MS);
    return () => clearInterval(id);
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
