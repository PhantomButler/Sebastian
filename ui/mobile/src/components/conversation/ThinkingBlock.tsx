import { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { MarkdownContent } from './MarkdownContent';

interface Props {
  text: string;
  done: boolean;
}

export function ThinkingBlock({ text, done }: Props) {
  const [expanded, setExpanded] = useState(false);

  const label = done ? '思考过程' : '思考中…';

  if (!expanded) {
    return (
      <TouchableOpacity
        style={styles.pill}
        onPress={() => setExpanded(true)}
        activeOpacity={0.7}
      >
        <Text style={styles.pillIcon}>💭</Text>
        <Text style={styles.pillLabel}>{label}</Text>
        <Text style={styles.pillChevron}>›</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.container}>
      {/* Header — same pill style, click to collapse */}
      <TouchableOpacity
        style={styles.header}
        onPress={() => setExpanded(false)}
        activeOpacity={0.7}
      >
        <Text style={styles.pillIcon}>💭</Text>
        <Text style={styles.pillLabel}>{label}</Text>
        <Text style={styles.pillChevron}>⌄</Text>
      </TouchableOpacity>
      {/* Content — connected to header, same container */}
      <View style={styles.body}>
        <MarkdownContent content={text} streaming={!done} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  // Collapsed: standalone pill
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    backgroundColor: '#1a1a2e',
    borderWidth: 1,
    borderColor: '#2a2a4e',
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 6,
    gap: 6,
    marginVertical: 4,
  },
  // Expanded: outer container merges header + body
  container: {
    borderWidth: 1,
    borderColor: '#2a2a4e',
    borderRadius: 12,
    overflow: 'hidden',
    marginVertical: 4,
    backgroundColor: '#111120',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1a1a2e',
    paddingHorizontal: 14,
    paddingVertical: 8,
    gap: 6,
  },
  body: {
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  pillIcon: { fontSize: 14 },
  pillLabel: { color: '#6060a0', fontSize: 13, flex: 1 },
  pillChevron: { color: '#3a3a5a', fontSize: 16 },
});
