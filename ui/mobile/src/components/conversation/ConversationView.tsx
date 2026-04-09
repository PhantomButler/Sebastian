import { useCallback, useEffect, useRef } from 'react';
import { FlatList, View, StyleSheet, type NativeScrollEvent, type NativeSyntheticEvent, type ScrollViewProps } from 'react-native';
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
    const distFromBottom = contentSize.height - contentOffset.y - layoutMeasurement.height;
    isNearBottom.current = distFromBottom < 150;
  }, []);

  const handleContentSizeChange = useCallback(() => {
    if (isNearBottom.current) {
      // During streaming use no animation to avoid queued animations conflicting
      flatListRef.current?.scrollToEnd({ animated: !isStreaming.current });
    }
  }, []);

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
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <FlatList
        ref={flatListRef}
        style={{ flex: 1 }}
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
