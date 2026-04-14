import { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
import { RightArrowIcon } from '../common/Icons';
import { MarkdownContent } from './MarkdownContent';

interface Props {
  text: string;
  done: boolean;
}

export function ThinkingBlock({ text, done }: Props) {
  const colors = useTheme();
  const [expanded, setExpanded] = useState(false);

  const label = done ? '思考过程' : '思考中…';

  if (!expanded) {
    return (
      <TouchableOpacity
        style={[
          styles.pill,
          { backgroundColor: colors.secondaryBackground, borderColor: colors.border },
        ]}
        onPress={() => setExpanded(true)}
        activeOpacity={0.7}
      >
        <Text style={styles.pillIcon}>💭</Text>
        <Text style={[styles.pillLabel, { color: colors.textMuted }]}>{label}</Text>
        <RightArrowIcon size={12} color={colors.textMuted} />
      </TouchableOpacity>
    );
  }

  return (
    <TouchableOpacity
      style={[
        styles.container,
        { backgroundColor: colors.background, borderColor: colors.border },
      ]}
      onPress={() => setExpanded(false)}
      activeOpacity={0.85}
    >
      {/* Header */}
      <View style={[styles.header, { backgroundColor: colors.secondaryBackground }]}>
        <Text style={styles.pillIcon}>💭</Text>
        <Text style={[styles.pillLabel, { color: colors.textMuted }]}>{label}</Text>
        <RightArrowIcon size={12} color={colors.textMuted} style={{ transform: [{ rotate: '90deg' }] }} />
      </View>
      {/* Content */}
      <View style={styles.body}>
        <MarkdownContent content={text} streaming={!done} />
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  // Collapsed: standalone pill
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 6,
    gap: 6,
    marginVertical: 4,
  },
  // Expanded: outer container merges header + body
  container: {
    borderWidth: 1,
    borderRadius: 12,
    overflow: 'hidden',
    marginVertical: 4,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 8,
    gap: 6,
  },
  body: {
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  pillIcon: { fontSize: 14 },
  pillLabel: { fontSize: 13, flex: 1 },
});
