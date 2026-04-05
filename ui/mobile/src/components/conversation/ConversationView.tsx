import { useRef } from 'react';
import { FlatList, View, StyleSheet } from 'react-native';
import { useConversation } from '../../hooks/useConversation';
import { useConversationStore } from '../../store/conversation';
import { UserBubble } from './UserBubble';
import { AssistantMessage } from './AssistantMessage';
import type { ConvMessage, RenderBlock } from '../../types';

interface Props {
  sessionId: string | null;
}

type ListItem =
  | { kind: 'message'; message: ConvMessage }
  | { kind: 'streaming'; blocks: RenderBlock[] };

export function ConversationView({ sessionId }: Props) {
  useConversation(sessionId);

  const flatListRef = useRef<FlatList>(null);

  const session = useConversationStore((s) =>
    sessionId ? s.sessions[sessionId] : undefined,
  );

  const messages = session?.messages ?? [];
  const activeTurn = session?.activeTurn ?? null;

  const items: ListItem[] = [
    ...messages.map((m) => ({ kind: 'message' as const, message: m })),
    ...(activeTurn && activeTurn.blocks.length > 0
      ? [{ kind: 'streaming' as const, blocks: activeTurn.blocks }]
      : []),
  ];

  function renderItem({ item }: { item: ListItem }) {
    if (item.kind === 'message') {
      const { message } = item;
      if (message.role === 'user') {
        return <UserBubble content={message.content} />;
      }
      // Assistant messages: use persisted blocks if available, else fall back to plain text
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
    // Streaming turn
    return <AssistantMessage blocks={item.blocks} />;
  }

  return (
    <View style={styles.container}>
      <FlatList
        ref={flatListRef}
        data={items}
        keyExtractor={(item, index) =>
          item.kind === 'message' ? item.message.id : `streaming-${index}`
        }
        renderItem={renderItem}
        contentContainerStyle={styles.content}
        onContentSizeChange={() =>
          flatListRef.current?.scrollToEnd({ animated: true })
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0d0d0d' },
  content: { paddingTop: 12, paddingBottom: 100 },
});
