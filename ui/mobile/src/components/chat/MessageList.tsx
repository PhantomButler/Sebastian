import { useRef } from 'react';
import { FlatList, StyleSheet } from 'react-native';
import type { Message } from '../../types';
import { MessageBubble } from './MessageBubble';
import { StreamingBubble } from './StreamingBubble';

interface Props {
  messages: Message[];
  streamingContent?: string;
}

export function MessageList({ messages, streamingContent }: Props) {
  const flatListRef = useRef<FlatList>(null);

  return (
    <FlatList
      ref={flatListRef}
      data={messages}
      keyExtractor={(m) => m.id}
      renderItem={({ item }) => <MessageBubble message={item} />}
      ListFooterComponent={
        streamingContent ? <StreamingBubble content={streamingContent} /> : null
      }
      contentContainerStyle={styles.content}
      onContentSizeChange={() => flatListRef.current?.scrollToEnd({ animated: true })}
    />
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 80 },
});
